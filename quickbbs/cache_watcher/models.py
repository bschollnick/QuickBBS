"""Cache Watcher Models for QuickBBS.

Provides filesystem monitoring and cache invalidation for the QuickBBS gallery application.
Uses Watchdog to monitor the albums directory for changes and automatically invalidates
affected cache entries to ensure data consistency.

Key Components:
    - WatchdogManager: Manages the watchdog process with automatic restarts every 4 hours
    - CacheFileMonitorEventHandler: Batches filesystem events for efficient processing
    - fs_Cache_Tracking: Database model for tracking cache invalidation state

The system buffers events for 5 seconds before processing to handle bulk operations efficiently.

Known Behavior - macOS Duplicate Events:
    macOS's FSEvents can send multiple waves of filesystem events for a single file operation,
    resulting in duplicate cache invalidations. For example, deleting a file may trigger:
    1. Initial deletion events (processed immediately after 5s debounce)
    2. Delayed directory metadata update events (processed 5-10s later)

    While this causes redundant database operations, it is functionally harmless as cache
    invalidation is idempotent. The performance impact is negligible for typical use cases.
    This is OS-level behavior and not a bug in the watchdog implementation.
"""

import collections
import logging
import os
import pathlib
import threading
import time
import warnings
from typing import Any, Optional

from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.db import close_old_connections, models, transaction
from django.db.utils import DatabaseError
from watchdog.events import FileSystemEvent, FileSystemEventHandler

from cache_watcher.watchdogmon import watchdog
from quickbbs.common import get_dir_sha

# Configure logging
logger = logging.getLogger(__name__)

Cache_Storage = None


class LockFreeEventBuffer:
    """
    Thread-safe event buffer for file system events with automatic deduplication.

    Replaces global defaultdict with lock to reduce contention during high file activity.

    IMPORTANT - Threading.Lock Usage:
    This class MUST use threading.RLock (not asyncio.Lock) because:
    1. Watchdog library runs filesystem monitoring in separate OS threads
    2. Event handlers (on_created, on_modified, etc.) are called from Watchdog's threads
    3. These OS threads exist outside the asyncio event loop
    4. threading.Lock protects shared state between multiple OS threads
    5. asyncio.Lock only works within a single asyncio event loop

    Do NOT convert to asyncio.Lock - it will break Watchdog integration.
    """

    def __init__(self, max_size: int = 1000):
        """
        Args:
            max_size: Maximum number of events to buffer before auto-cleanup
        """
        # Thread-safe deque for event paths
        self._events = collections.deque()
        # RLock allows recursive locking if needed
        # MUST be threading.RLock (see class docstring for why)
        self._lock = threading.RLock()
        self._max_size = max_size

    def add_event(self, dirpath: str) -> None:
        """
        Add directory path to event buffer.

        Args:
            dirpath: Directory path that had file system changes
        """
        with self._lock:
            self._events.append(dirpath)

            # Prevent buffer from growing too large to avoid memory issues
            if len(self._events) > self._max_size:
                # Remove oldest events to prevent memory buildup
                cleanup_target = int(self._max_size * 0.8)  # Remove 20% of max size
                while len(self._events) > cleanup_target:
                    self._events.popleft()

    def get_events_to_process(self) -> set[str]:
        """
        Get unique directory paths and clear buffer.

        Returns:
            Set of unique directory paths that need cache invalidation
        """
        with self._lock:
            if not self._events:
                return set()

            # Convert to set for automatic deduplication
            unique_paths = set(self._events)
            self._events.clear()
            return unique_paths

    def size(self) -> int:
        """Get current buffer size."""
        with self._lock:
            return len(self._events)


# Global event buffer for batch processing (optimized lock-free version)
optimized_event_buffer = LockFreeEventBuffer()
EVENT_PROCESSING_DELAY = 5  # seconds
WATCHDOG_RESTART_INTERVAL = 4 * 60 * 60  # 4 hours in seconds

# Global processing semaphore - shared across all handler instances
# This ensures only one cache invalidation runs at a time, even across handler restarts
# MUST use threading.Semaphore - accessed by watchdog threads (OS threads, not asyncio)
processing_semaphore = threading.Semaphore(1)


class WatchdogManager:
    """
    Manages periodic restart of the watchdog process.

    IMPORTANT - Threading.Lock Usage:
    This class MUST use threading.Lock (not asyncio.Lock) because:
    1. Uses threading.Timer for scheduled restarts (runs in OS threads)
    2. Watchdog observer runs in separate OS threads
    3. Lock protects state accessed from timer callbacks and watchdog threads
    4. These threads exist outside any asyncio event loop

    Do NOT convert to asyncio.Lock - it will break timer-based restarts.
    """

    def __init__(self) -> None:
        self.restart_timer = None
        # MUST be threading.Lock (see class docstring for why)
        self.lock = threading.Lock()
        self.monitor_path = os.path.join(settings.ALBUMS_PATH, "albums")
        self.event_handler = None
        self.is_running = False

    def start(self) -> None:
        """Start the watchdog with periodic restart capability."""
        with self.lock:
            if not self.is_running:
                logger.debug("Starting watchdog...")
                self.event_handler = CacheFileMonitorEventHandler()
                try:
                    watchdog.startup(
                        monitor_path=self.monitor_path,
                        event_handler=self.event_handler,
                    )
                    self.is_running = True
                    logger.info("Watchdog started monitoring: %s", self.monitor_path)
                    # Always schedule restart when we start successfully
                    logger.debug("Scheduling restart timer...")
                    self._schedule_restart()
                except Exception as e:
                    # TODO: Research specific watchdog library exceptions
                    logger.error("Failed to start watchdog: %s", e, exc_info=True)
                    raise
            else:
                logger.info("Watchdog already running")

    def stop(self) -> None:
        """Stop the watchdog but don't cancel restart timer during restart process."""
        with self.lock:
            if self.is_running:
                try:
                    # Cancel any pending timers in the event handler before shutdown
                    if self.event_handler:
                        with self.event_handler.timer_lock:
                            if self.event_handler.event_timer:
                                self.event_handler.event_timer.cancel()
                                self.event_handler.event_timer = None
                                logger.debug("Cancelled pending event timer during watchdog stop")

                    watchdog.shutdown()
                    self.is_running = False
                    logger.info("Watchdog stopped")
                except Exception as e:
                    # TODO: Research specific watchdog library exceptions
                    logger.error("Error stopping watchdog: %s", e)

    def shutdown(self) -> None:
        """Complete shutdown - stop watchdog and cancel restart timer."""
        with self.lock:
            if self.restart_timer:
                self.restart_timer.cancel()
                self.restart_timer = None

            if self.is_running:
                try:
                    watchdog.shutdown()
                    self.is_running = False
                    logger.info("Watchdog completely shut down")
                except Exception as e:
                    # TODO: Research specific watchdog library exceptions
                    logger.error("Error stopping watchdog: %s", e)

    def restart(self) -> None:
        """Restart the watchdog process and schedule the next restart."""
        logger.info("Performing scheduled watchdog restart")
        restart_successful = False

        try:
            logger.debug("Calling stop()...")
            self.stop()
            logger.debug("Stop() completed, waiting 1 second...")
            time.sleep(1)  # Brief pause to ensure clean shutdown
            logger.debug("Calling start()...")
            self.start()
            restart_successful = True
            logger.info("Watchdog restart completed successfully")
        except Exception as e:
            # TODO: Research specific watchdog library exceptions
            logger.error("Error during watchdog restart: %s", e, exc_info=True)

        # Always try to schedule next restart, even if this restart failed
        if not restart_successful:
            logger.warning("Restart failed, manually scheduling next restart attempt")
            with self.lock:
                self._schedule_restart()

    def _schedule_restart(self) -> None:
        """Schedule the next restart - must be called while holding self.lock."""
        try:
            # Cancel existing timer if it exists
            if self.restart_timer:
                was_alive = self.restart_timer.is_alive()
                self.restart_timer.cancel()
                logger.debug("Cancelled existing restart timer (was_alive: %s)", was_alive)
                self.restart_timer = None

            # Create new timer
            self.restart_timer = threading.Timer(WATCHDOG_RESTART_INTERVAL, self.restart)
            self.restart_timer.daemon = True
            self.restart_timer.start()

            # Verify timer started successfully
            if self.restart_timer.is_alive():
                logger.info("✓ Next watchdog restart scheduled in %.1f hours", WATCHDOG_RESTART_INTERVAL / 3600)
                logger.debug("Timer object: %s, thread name: %s", self.restart_timer, self.restart_timer.name)
            else:
                logger.error("⚠ Timer failed to start!")

        except Exception as e:
            # TODO: Research threading.Timer exceptions
            logger.error("Error scheduling restart: %s", e, exc_info=True)


# Global watchdog manager instance
watchdog_manager = WatchdogManager()


class CacheFileMonitorEventHandler(FileSystemEventHandler):
    """
    Event Handler for the Watchdog Monitor for QuickBBS, optimized to batch process events.

    IMPORTANT - Threading.Lock Usage:
    This class MUST use threading.Lock (not asyncio.Lock) because:
    1. Event handlers (on_created, on_modified, etc.) are called from Watchdog's OS threads
    2. Uses threading.Timer for delayed event processing (runs in OS threads)
    3. Lock protects timer state accessed from both event handler and timer threads
    4. Watchdog library operates entirely outside the asyncio event loop

    Do NOT convert to asyncio.Lock - event handlers are called from OS threads.
    """

    def __init__(self) -> None:
        super().__init__()
        self.event_timer = None
        # MUST be threading.Lock (see class docstring for why)
        self.timer_lock = threading.Lock()
        # Timer generation counter - incremented each time a new timer is created
        # Used to prevent old timers from processing if they fire after being cancelled
        self.timer_generation = 0
        # Instance ID for debugging - helps track which handler is processing
        self.instance_id = id(self)

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file/directory creation events."""
        self._buffer_event(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file/directory deletion events."""
        self._buffer_event(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file/directory modification events."""
        self._buffer_event(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        """Handle file/directory move events."""
        self._buffer_event(event)

    def _buffer_event(self, event: FileSystemEvent) -> None:
        """Buffer events to process them in batches."""
        try:
            if event.is_directory:
                dirpath = os.path.normpath(event.src_path)
            else:
                dirpath = str(pathlib.Path(os.path.normpath(event.src_path)).parent)

            # Add event to lock-free buffer
            optimized_event_buffer.add_event(dirpath)

            # Reset or create timer with thread safety
            with self.timer_lock:
                # Cancel existing timer if present
                if self.event_timer is not None:
                    self.event_timer.cancel()
                    self.event_timer = None

                # Increment generation counter - this invalidates any pending timers
                self.timer_generation += 1
                current_generation = self.timer_generation

                # Create new timer with current generation captured in lambda
                # If this timer fires after being superseded, it will detect the generation mismatch
                self.event_timer = threading.Timer(EVENT_PROCESSING_DELAY, lambda: self._process_buffered_events(current_generation))
                self.event_timer.daemon = True
                self.event_timer.start()

        except Exception as e:
            # TODO: Research FileSystemEvent and threading.Timer exceptions
            logger.error("Error buffering event %s: %s", event.src_path, e)

    def _process_buffered_events(self, expected_generation: int) -> None:
        """Process all buffered events at once.

        This method runs in a background thread from the watchdog system.

        Uses both a generation counter and a global semaphore to prevent duplicate processing:
        - Generation counter prevents old timers from processing after being superseded
        - Semaphore ensures only one thread processes at a time across all handler instances

        Args:
            expected_generation: The timer generation this callback belongs to.
                                If it doesn't match current generation, this timer was superseded.
        """
        # Check if this timer has been superseded by a newer one
        with self.timer_lock:
            if expected_generation != self.timer_generation:
                return
            # Clear timer reference now that we're executing
            self.event_timer = None

        # Try to acquire the global semaphore without blocking
        # If we can't acquire it, another thread is already processing
        if not processing_semaphore.acquire(blocking=False):
            return

        try:
            # Get unique paths from lock-free buffer (automatic deduplication)
            paths_to_process = optimized_event_buffer.get_events_to_process()

            if paths_to_process:
                logger.info("[Gen %d] Processing %d buffered directory changes", expected_generation, len(paths_to_process))

                # Optimize: Convert paths to SHAs once, then batch query for IndexDirs objects
                from quickbbs.models import (
                    IndexDirs,  # pylint: disable=import-outside-toplevel
                )

                sha_list = [get_dir_sha(path) for path in paths_to_process]
                index_dirs = list(IndexDirs.objects.filter(dir_fqpn_sha256__in=sha_list))

                if index_dirs:
                    # Wrap DB operation for ASGI compatibility
                    try:
                        # Try async_to_sync wrapper for ASGI compatibility
                        async_to_sync(self._remove_from_cache_indexdirs_async)(index_dirs)
                    except RuntimeError:
                        # Fallback to direct call if not in async context
                        Cache_Storage.remove_multiple_from_cache_indexdirs(index_dirs)

        except (RuntimeError, DatabaseError, OSError, AttributeError) as e:
            logger.error("Error processing buffered events: %s", e)
        finally:
            # Release the global semaphore to allow next processing run
            processing_semaphore.release()
            # Watchdog runs in background thread - must close connections
            close_old_connections()

    async def _remove_from_cache_indexdirs_async(self, index_dirs: list[Any]) -> None:
        """Async wrapper for cache removal to support ASGI mode.

        Args:
            index_dirs: List of IndexDirs objects to remove from cache
        """
        # Run the synchronous database operation in a thread pool
        await sync_to_async(Cache_Storage.remove_multiple_from_cache_indexdirs)(index_dirs)

    async def _remove_from_cache_async(self, paths: list[str]) -> None:
        """Async wrapper for cache removal to support ASGI mode.

        DEPRECATED: Use _remove_from_cache_indexdirs_async instead.

        Args:
            paths: List of directory paths to remove from cache
        """
        # Run the synchronous database operation in a thread pool
        await sync_to_async(Cache_Storage.remove_multiple_from_cache)(paths)


class fs_Cache_Tracking(models.Model):
    """
    Cache_Storage table is used to signify that a directory has been scanned and is up to date.

    The directory relationship is the single source of truth - all directory information
    (SHA256, path) should be accessed through the OneToOne relationship to IndexDirs.
    """

    # Stored as Unix TimeStamp (ms)
    lastscan = models.FloatField(default=0, blank=True)
    invalidated = models.BooleanField(default=False, db_index=True)

    # OneToOne relationship to IndexDirs using dir_fqpn_sha256
    # This is the ONLY source of directory information (SHA256 and path)
    directory = models.OneToOneField(
        "quickbbs.IndexDirs",
        on_delete=models.CASCADE,  # Changed from SET_NULL - cache entries should be deleted if directory is deleted
        to_field="dir_fqpn_sha256",
        db_column="directory_data",
        related_name="Cache_Watcher",
        unique=True,  # Enforce uniqueness at DB level
        null=True,  # Temporarily nullable for migration, will be removed after data migration
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(fields=["directory", "invalidated"]),
        ]

    @staticmethod
    def clear_all_records() -> int:
        """Mark all records as invalidated.

        :return: Number of records invalidated
        """
        try:
            updated_count = fs_Cache_Tracking.objects.all().update(invalidated=True)
            logger.info("Invalidated %d cache records", updated_count)
            return updated_count
        except DatabaseError as e:
            logger.error("Error clearing all cache records: %s", e)
            return 0

    @staticmethod
    def delete_orphaned_entries() -> int:
        """
        Delete cache entries that have null directory reference.

        With the new model design where directory is a required FK with CASCADE delete,
        orphaned entries shouldn't exist. This method handles legacy data cleanup where
        cache entries may exist without corresponding directory records.

        Returns:
            Number of entries deleted
        """
        try:
            deleted_count, _ = fs_Cache_Tracking.objects.filter(directory__isnull=True).delete()
            if deleted_count > 0:
                logger.info("Deleted %d orphaned cache entries", deleted_count)
            return deleted_count
        except DatabaseError as e:
            logger.error("Error deleting orphaned cache entries: %s", e)
            return 0

    def add_from_indexdirs(self, index_dir: Any) -> "fs_Cache_Tracking | None":
        """Add or update a directory in the cache using an IndexDirs record.

        Args:
            index_dir: The IndexDirs instance containing directory information

        Returns:
            The cache tracking entry or None if error occurred
        """
        # Validate the IndexDirs record
        if not index_dir or not hasattr(index_dir, "dir_fqpn_sha256") or not index_dir.dir_fqpn_sha256:
            logger.warning("Attempted to add invalid IndexDirs record to cache - rejected")
            return None

        try:
            scan_time = time.time()

            defaults = {
                "lastscan": scan_time,
                "invalidated": False,
            }

            entry, created = fs_Cache_Tracking.objects.update_or_create(
                directory=index_dir,
                defaults=defaults,
            )
            action = "Created" if created else "Updated"
            logger.debug("%s cache entry for: %s", action, index_dir.fqpndirectory)
            return entry

        except DatabaseError as e:
            logger.error("Error adding IndexDirs record to cache: %s", e)
            return None

    def add_to_cache(self, dir_path: str) -> Optional["fs_Cache_Tracking"]:
        """Add or update a directory in the cache.

        DEPRECATED: Use add_from_indexdirs() instead to avoid redundant SHA computation
        and database lookups.

        Args:
            dir_path: The fully qualified pathname of the directory

        Returns:
            The cache tracking entry or None if error occurred
        """
        warnings.warn(
            "add_to_cache(dir_path: str) is deprecated. Use add_from_indexdirs(index_dir) instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        # Reject empty directory names
        if not dir_path or not dir_path.strip():
            logger.warning("Attempted to add empty directory path to cache - rejected")
            return None

        try:
            # Import inside function to avoid circular dependency
            from quickbbs.models import (
                IndexDirs,  # pylint: disable=import-outside-toplevel
            )

            dir_sha = get_dir_sha(dir_path)
            scan_time = time.time()

            # Fetch the IndexDirs instance by dir_sha using optimized cached lookup
            found, index_dir = IndexDirs.search_for_directory_by_sha(dir_sha)
            if not found:
                logger.warning("Cannot add cache entry for %s - IndexDirs entry not found", dir_path)
                return None

            defaults = {
                "lastscan": scan_time,
                "invalidated": False,
            }

            entry, created = fs_Cache_Tracking.objects.update_or_create(
                directory=index_dir,
                defaults=defaults,
            )
            action = "Created" if created else "Updated"
            logger.debug("%s cache entry for: %s", action, dir_path)
            return entry

        except DatabaseError as e:
            logger.error("Error adding %s to cache: %s", dir_path, e)
            return None

    def sha_exists_in_cache(self, sha256: str) -> bool:
        """Check if a directory SHA exists in cache and is not invalidated.

        Args:
            sha256: The SHA256 hash of the directory

        Returns:
            True if SHA exists and is not invalidated, False otherwise
        """
        try:
            return fs_Cache_Tracking.objects.filter(directory__dir_fqpn_sha256=sha256, invalidated=False).exists()
        except DatabaseError as e:
            logger.error("Error checking SHA existence in cache: %s", e)
            return False

    def remove_from_cache_indexdirs(self, index_dir: Any) -> bool:
        """Remove a directory from cache using an IndexDirs record.

        Optimized version that accepts an IndexDirs record directly,
        avoiding redundant database lookups when the record is already available.

        Args:
            index_dir: The IndexDirs instance to remove from cache

        Returns:
            True if successfully removed, False otherwise
        """
        try:
            if not index_dir or not hasattr(index_dir, "dir_fqpn_sha256"):
                logger.warning("Invalid IndexDirs record provided to remove_from_cache_indexdirs")
                return False

            # Invalidate thumbnail
            index_dir.invalidate_thumb()

            # Update cache entry using optimized helper method
            self._invalidate_cache_entry_indexdirs(index_dir)

            # Clear layout cache
            self._clear_layout_cache_bulk([index_dir])

            logger.debug("Removed cache entry for: %s", index_dir.fqpndirectory)
            return True

        except (DatabaseError, AttributeError) as e:
            logger.error("Error removing directory from cache: %s", e)
            return False

    def remove_from_cache_sha(self, sha256: str) -> bool:
        """Remove a directory from cache by SHA256.

        Args:
            sha256: The SHA256 hash of the directory

        Returns:
            True if successfully removed, False otherwise
        """
        try:
            # Import inside function to avoid circular dependency
            from quickbbs.models import (
                IndexDirs,  # pylint: disable=import-outside-toplevel
            )

            # Single optimized lookup with prefetched relationships
            found, directory = IndexDirs.search_for_directory_by_sha(sha256)

            if not found:
                logger.warning("Cannot remove cache for SHA %s - IndexDirs not found", sha256)
                return False

            # Invalidate thumbnail
            directory.invalidate_thumb()

            # Update cache entry using optimized helper method (no additional lookup)
            self._invalidate_cache_entry_indexdirs(directory)

            # Clear layout cache
            self._clear_layout_cache_bulk([directory])

            logger.debug("Removed cache entry for SHA: %s", sha256)
            return True

        except (DatabaseError, AttributeError) as e:
            logger.error("Error removing SHA %s from cache: %s", sha256, e)
            return False

    def remove_multiple_from_cache_indexdirs(self, index_dirs: list[Any]) -> bool:
        """Remove multiple directories from cache using IndexDirs objects.

        Optimized batch version that accepts IndexDirs records directly,
        avoiding redundant SHA computation and database lookups.

        :Args:
            index_dirs: List of IndexDirs instances to remove from cache

        :Returns:
            True if any entries were invalidated, False otherwise
        """
        if not index_dirs:
            return False

        # Import inside function to avoid circular dependency
        from quickbbs.models import IndexDirs  # pylint: disable=import-outside-toplevel

        # Extract SHA256 hashes directly from objects (no normalization needed!)
        sha_list = [d.dir_fqpn_sha256 for d in index_dirs if d and hasattr(d, "dir_fqpn_sha256") and d.dir_fqpn_sha256]

        if not sha_list:
            return False

        logger.info("Removing %d directories from cache (object-based)", len(sha_list))

        # Create mapping for later cache clearing (already have the objects!)
        fqpn_by_dir_sha = {d.dir_fqpn_sha256: d for d in index_dirs if d and hasattr(d, "dir_fqpn_sha256") and d.dir_fqpn_sha256}

        # Collect all parent directories using efficient batch query approach
        all_dirs_to_invalidate = IndexDirs.get_all_parent_shas(sha_list)

        # Update cache entries using bulk operations
        with transaction.atomic():
            # Get all IndexDirs records and capture their SHAs
            index_dirs_queryset = IndexDirs.objects.filter(dir_fqpn_sha256__in=all_dirs_to_invalidate)
            found_shas = {d.dir_fqpn_sha256 for d in index_dirs_queryset}

            # Bulk update existing cache entries
            current_time = time.time()
            update_count = fs_Cache_Tracking.objects.filter(directory__dir_fqpn_sha256__in=found_shas).update(invalidated=True, lastscan=current_time)

            # Find SHAs that don't have cache entries (set difference)
            existing_cache_shas = set(
                fs_Cache_Tracking.objects.filter(directory__dir_fqpn_sha256__in=found_shas).values_list("directory__dir_fqpn_sha256", flat=True)
            )
            missing_shas = found_shas - existing_cache_shas

            # Bulk create missing cache entries
            if missing_shas:
                sha_to_indexdir = {d.dir_fqpn_sha256: d for d in index_dirs_queryset}
                new_entries = [fs_Cache_Tracking(directory=sha_to_indexdir[sha], invalidated=True, lastscan=current_time) for sha in missing_shas]
                fs_Cache_Tracking.objects.bulk_create(new_entries)
                update_count += len(new_entries)

        # Clear layout caches for affected directories - BULK OPERATION
        if update_count > 0:
            # Build list of affected directories, filtering out None values and objects without pk
            affected_directories = [
                fqpn_by_dir_sha[sha]
                for sha in set(sha_list) & fqpn_by_dir_sha.keys()
                if (fqpn_by_dir_sha[sha] is not None and hasattr(fqpn_by_dir_sha[sha], "pk") and fqpn_by_dir_sha[sha].pk is not None)
            ]

            if affected_directories:
                self._clear_layout_cache_bulk(affected_directories)
                self._clear_indexdirs_cache_bulk(affected_directories)

            logger.info("Successfully invalidated %d cache entries (object-based)", update_count)

        return update_count > 0

    def remove_from_cache_name(self, dir_path: str) -> bool:
        """Remove a directory from cache by path.

        DEPRECATED: Use remove_from_cache_indexdirs() instead to avoid redundant SHA
        computation and database lookups.

        Args:
            dir_path: The fully qualified pathname of the directory

        Returns:
            True if successfully removed, False otherwise
        """
        warnings.warn(
            "remove_from_cache_name(dir_path: str) is deprecated. Use remove_from_cache_indexdirs(index_dir) instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        try:
            sha256 = get_dir_sha(dir_path)
            return self.remove_from_cache_sha(sha256)
        except (OSError, DatabaseError, AttributeError) as e:
            logger.error("Error removing %s from cache: %s", dir_path, e)
            return False

    def _invalidate_cache_entry_indexdirs(self, index_dir: Any) -> Optional["fs_Cache_Tracking"]:
        """Set a cache entry to invalidated status using an IndexDirs record.

        Optimized version that accepts an IndexDirs record directly,
        avoiding redundant database lookups.

        Args:
            index_dir: The IndexDirs instance

        Returns:
            The updated or created fs_Cache_Tracking entry, or None if invalid
        """
        if not index_dir or not hasattr(index_dir, "dir_fqpn_sha256"):
            logger.warning("Invalid IndexDirs record provided to _invalidate_cache_entry_indexdirs")
            return None

        entry, _ = fs_Cache_Tracking.objects.update_or_create(
            directory=index_dir,
            defaults={
                "invalidated": True,
                "lastscan": time.time(),
            },
        )
        return entry

    def _invalidate_cache_entry(self, sha256: str) -> Optional["fs_Cache_Tracking"]:
        """Set a cache entry to invalidated status with current timestamp.

        Args:
            sha256: The SHA256 hash of the directory

        Returns:
            The updated or created fs_Cache_Tracking entry, or None if sha256 is empty or IndexDirs not found
        """
        # Reject empty SHA256 values
        if not sha256 or not sha256.strip():
            logger.warning("Attempted to invalidate cache with empty SHA256 - rejected")
            return None

        # Import inside function to avoid circular dependency
        from quickbbs.models import IndexDirs  # pylint: disable=import-outside-toplevel

        # Fetch the IndexDirs instance by dir_sha using optimized cached lookup
        found, index_dir = IndexDirs.search_for_directory_by_sha(sha256)
        if not found:
            logger.warning("Cannot invalidate cache for SHA %s - IndexDirs entry not found", sha256)
            return None

        entry, _ = fs_Cache_Tracking.objects.update_or_create(
            directory=index_dir,
            defaults={
                "invalidated": True,
                "lastscan": time.time(),
            },
        )
        return entry

    def remove_multiple_from_cache(self, dir_names: list[str]) -> bool:
        """Remove multiple directories from cache in a single transaction.

        DEPRECATED: Use remove_multiple_from_cache_indexdirs() instead to avoid redundant
        SHA computation and database lookups.

        :param dir_names: List of directory paths to remove from cache
        :return: True if any entries were invalidated, False otherwise
        """
        warnings.warn(
            "remove_multiple_from_cache(dir_names: list[str]) is deprecated. "
            "Use remove_multiple_from_cache_indexdirs(index_dirs) instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        if not dir_names:
            return False

        # Import inside function to avoid circular dependency
        from quickbbs.models import IndexDirs  # pylint: disable=import-outside-toplevel

        # Convert all directory names to SHA256 hashes (deduplicate first for efficiency)
        # Compute SHA→path mapping ONCE, then extract SHAs to avoid duplicate computation
        sha_to_path = {get_dir_sha(path): path for path in set(dir_names)}
        sha_list = list(sha_to_path.keys())

        if not sha_list:
            return False

        logger.info("Removing %d directories from cache", len(sha_list))

        # Get affected directories (only load fields needed for cache clearing)
        fqpn_by_dir_sha = {
            d.dir_fqpn_sha256: d for d in IndexDirs.objects.filter(dir_fqpn_sha256__in=sha_list).only("dir_fqpn_sha256", "id", "fqpndirectory")
        }

        # Check for missing IndexDirs entries and create them
        missing_shas = set(sha_list) - set(fqpn_by_dir_sha.keys())
        if missing_shas:
            logger.info("Creating %d missing IndexDirs entries", len(missing_shas))
            for missing_sha in missing_shas:
                dir_path = sha_to_path.get(missing_sha)
                if dir_path:
                    try:
                        _, new_dir = IndexDirs.add_directory(dir_path)
                        # Only add to dict if new_dir is valid and has required attributes
                        if new_dir is not None and hasattr(new_dir, "pk") and new_dir.pk is not None:
                            fqpn_by_dir_sha[missing_sha] = new_dir
                            logger.debug("Created IndexDirs entry for %s", dir_path)
                        else:
                            logger.warning("IndexDirs.add_directory returned invalid object for %s", dir_path)
                    except (DatabaseError, OSError) as e:
                        logger.error("Failed to create IndexDirs entry for %s: %s", dir_path, e)

        # Collect all parent directories using efficient batch query approach
        # This replaces the N*M loop with D queries (where D = max directory depth)
        all_dirs_to_invalidate = IndexDirs.get_all_parent_shas(sha_list)

        # Update cache entries using bulk operations
        with transaction.atomic():
            # Get all IndexDirs records and capture their SHAs
            index_dirs = IndexDirs.objects.filter(dir_fqpn_sha256__in=all_dirs_to_invalidate)
            found_shas = {d.dir_fqpn_sha256 for d in index_dirs}

            # Bulk update existing cache entries
            current_time = time.time()
            update_count = fs_Cache_Tracking.objects.filter(directory__dir_fqpn_sha256__in=found_shas).update(invalidated=True, lastscan=current_time)

            # Find SHAs that don't have cache entries (set difference)
            existing_cache_shas = set(
                fs_Cache_Tracking.objects.filter(directory__dir_fqpn_sha256__in=found_shas).values_list("directory__dir_fqpn_sha256", flat=True)
            )
            missing_shas = found_shas - existing_cache_shas

            # Bulk create missing cache entries
            if missing_shas:
                sha_to_indexdir = {d.dir_fqpn_sha256: d for d in index_dirs}
                new_entries = [fs_Cache_Tracking(directory=sha_to_indexdir[sha], invalidated=True, lastscan=current_time) for sha in missing_shas]
                fs_Cache_Tracking.objects.bulk_create(new_entries)
                update_count += len(new_entries)

        # Clear layout caches for affected directories - BULK OPERATION
        if update_count > 0:
            # Build list of affected directories, filtering out None values and objects without pk
            affected_directories = [
                fqpn_by_dir_sha[sha]
                for sha in set(sha_list) & fqpn_by_dir_sha.keys()
                if (fqpn_by_dir_sha[sha] is not None and hasattr(fqpn_by_dir_sha[sha], "pk") and fqpn_by_dir_sha[sha].pk is not None)
            ]

            if affected_directories:
                self._clear_layout_cache_bulk(affected_directories)
                self._clear_indexdirs_cache_bulk(affected_directories)

            logger.info("Successfully invalidated %d cache entries", update_count)

        return update_count > 0

    def _clear_layout_cache_bulk(self, directories: list[Any]) -> None:
        """
        Clear layout cache for multiple directories efficiently.

        Uses shared clear_layout_cache_for_directories() function to avoid code duplication.
        Clears ALL sort orderings (0, 1, 2) for each directory.

        Args:
            directories: List of IndexDirs objects to clear cache for

        Performance:
            Old: 3N database queries + P cache deletions (N=dirs, P=pages)
            New: 0 database queries + K cache scans (K=cache size ~500)
        """
        if not directories:
            return

        try:
            # Import inside function to avoid circular dependency
            from frontend.managers import (  # pylint: disable=import-outside-toplevel
                clear_layout_cache_for_directories,
            )

            # Use shared cache clearing function
            cleared_count = clear_layout_cache_for_directories(directories)
            logger.debug("Cleared %d layout cache entries for %d directories", cleared_count, len(directories))

        except (KeyError, ImportError, AttributeError) as e:
            logger.error("Error clearing layout cache for directories: %s", e)

    def _clear_indexdirs_cache_bulk(self, directories: list[Any]) -> None:
        """
        Clear indexdirs LRU cache for invalidated directories.

        When directories are invalidated, their cached IndexDirs objects must be
        removed from the LRU cache to prevent stale is_cached checks. The cache
        key is the directory's SHA256 hash.

        :Args:
            directories: List of IndexDirs objects that were invalidated
        """
        try:
            # pylint: disable=import-outside-toplevel
            from quickbbs.models import indexdirs_cache

            # Extract SHA256s and directly delete from cache
            cleared_count = 0
            for directory in directories:
                if directory and hasattr(directory, "dir_fqpn_sha256"):
                    sha = directory.dir_fqpn_sha256
                    if sha in indexdirs_cache:
                        del indexdirs_cache[sha]
                        cleared_count += 1

            logger.debug("Cleared %d indexdirs cache entries for %d directories", cleared_count, len(directories))

        except (KeyError, ImportError, AttributeError) as e:
            logger.error("Error clearing indexdirs cache for directories: %s", e)
