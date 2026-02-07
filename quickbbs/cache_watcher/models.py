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
from typing import Any

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

    __slots__ = ("_events", "_lock", "_max_size")

    def __init__(self, max_size: int = 200):
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
                cleanup_target = int(self._max_size * 0.5)  # Remove 50% of max size
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

    def clear(self) -> None:
        """Clear all buffered events.

        Used during watchdog restarts to prevent stale events from
        being processed after the restart.
        """
        with self._lock:
            logger.debug("Clearing event buffer (%d events)", len(self._events))
            self._events.clear()


# ============================================================================
# MODULE-LEVEL GLOBAL STATE
# ============================================================================
# The following globals are intentionally module-scoped and thread-safe:
#
# 1. optimized_event_buffer: Lock-free event buffer for batch processing
#    - Thread-safe via LockFreeEventBuffer implementation (uses threading.Lock internally)
#    - Global scope required because watchdog event handlers need shared access
#    - Survives watchdog restarts to prevent event loss
#
# 2. processing_semaphore: Serializes cache invalidation operations
#    - MUST be threading.Semaphore (not asyncio.Lock) - watchdog uses OS threads
#    - Acts as mutex (Semaphore(1)) to prevent concurrent cache invalidation
#    - Shared across all handler instances to coordinate multi-process safety
#    - Semaphore used instead of Lock to support timeout operations
#
# Threading Model:
#    - Watchdog observer runs in separate OS threads (not asyncio event loop)
#    - Event handlers are called from watchdog threads
#    - Must use threading primitives (not asyncio) for synchronization
#
# Lifecycle:
#    - Initialized on module import (Django app startup)
#    - Persists for application lifetime
#    - Cleaned up on Django shutdown (atexit handlers)
# ============================================================================

# Global event buffer for batch processing (optimized lock-free version)
optimized_event_buffer = LockFreeEventBuffer()

# Event processing configuration
EVENT_PROCESSING_DELAY = 5  # seconds - debounce delay for batching events
WATCHDOG_RESTART_INTERVAL = 4 * 60 * 60  # 4 hours in seconds

# Global processing semaphore - ensures serialized cache invalidation
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

    __slots__ = ("restart_timer", "lock", "monitor_path", "event_handler", "is_running")

    def __init__(self) -> None:
        self.restart_timer = None
        # MUST be threading.Lock (see class docstring for why)
        self.lock = threading.Lock()
        self.monitor_path = os.path.join(settings.ALBUMS_PATH, "albums")
        self.event_handler = None
        self.is_running = False

    def start(self, force_recreate: bool = False) -> None:
        """Start the watchdog with periodic restart capability.

        Args:
            force_recreate: If True, recreate the observer to prevent memory leaks
        """
        with self.lock:
            if not self.is_running:
                logger.debug("Starting watchdog...")
                self.event_handler = CacheFileMonitorEventHandler()
                try:
                    watchdog.startup(
                        monitor_path=self.monitor_path,
                        event_handler=self.event_handler,
                        force_recreate=force_recreate,
                    )
                    self.is_running = True
                    logger.info("Watchdog started monitoring: %s", self.monitor_path)
                    # Always schedule restart when we start successfully
                    logger.debug("Scheduling restart timer...")
                    self._schedule_restart()
                except Exception as e:
                    # Broad exception catch is intentional - watchdog can raise various exceptions
                    # (OSError, RuntimeError, etc.) and we want to catch all startup failures
                    logger.error("Failed to start watchdog: %s", e, exc_info=True)
                    raise
            else:
                logger.info("Watchdog already running")

    def stop(self) -> None:
        """Stop the watchdog but don't cancel restart timer during restart process."""
        with self.lock:
            if self.is_running:
                try:
                    # Clean up the event handler before stopping
                    if self.event_handler:
                        logger.debug("Cleaning up event handler before stop")
                        self.event_handler.cleanup()

                    # Use stop_observer() instead of shutdown() to avoid sys.exit()
                    watchdog.stop_observer()
                    self.event_handler = None
                    self.is_running = False
                    logger.info("Watchdog stopped")
                except Exception as e:
                    # Broad exception catch is intentional - ensure cleanup continues even if errors occur
                    logger.error("Error stopping watchdog: %s", e)

    def shutdown(self) -> None:
        """Complete shutdown - stop watchdog and cancel restart timer."""
        with self.lock:
            if self.restart_timer:
                self.restart_timer.cancel()
                self.restart_timer = None

            if self.is_running:
                try:
                    # Clean up the event handler before shutdown
                    if self.event_handler:
                        self.event_handler.cleanup()

                    watchdog.shutdown()
                    self.event_handler = None
                    self.is_running = False
                    logger.info("Watchdog completely shut down")
                except Exception as e:
                    # Broad exception catch is intentional - ensure shutdown completes even if errors occur
                    logger.error("Error stopping watchdog: %s", e)

    def _process_pending_events(self) -> None:
        """Process any pending events in the buffer before restart.

        This ensures we don't lose filesystem events during the restart process.
        """
        # Check buffer size before attempting to acquire semaphore
        buffer_size = optimized_event_buffer.size()
        if buffer_size == 0:
            logger.debug("No pending events to process before restart")
            return

        logger.info("Processing %d pending events before restart", buffer_size)

        # Try to acquire the semaphore with blocking
        # Use non-blocking to check if another thread is already processing
        if not processing_semaphore.acquire(blocking=False):
            logger.warning("Could not acquire processing lock - another thread is processing events")
            return

        try:
            # Get unique paths from buffer (automatic deduplication)
            paths_to_process = optimized_event_buffer.get_events_to_process()

            if paths_to_process:
                logger.info("Processing %d unique directory changes before restart", len(paths_to_process))

                # Import here to avoid circular dependency
                from quickbbs.models import (
                    DirectoryIndex,  # pylint: disable=import-outside-toplevel
                )

                # Convert paths to SHAs and batch query for DirectoryIndex objects
                sha_list = [get_dir_sha(path) for path in paths_to_process]
                index_dirs = list(DirectoryIndex.objects.filter(dir_fqpn_sha256__in=sha_list).only("dir_fqpn_sha256", "id", "fqpndirectory"))

                if index_dirs:
                    # Process cache invalidation
                    Cache_Storage.remove_multiple_from_cache_indexdirs(index_dirs)
                    logger.info("Successfully processed pending events before restart")

                # Explicitly delete large objects to free memory
                del paths_to_process
                del sha_list
                del index_dirs

        except (RuntimeError, DatabaseError, OSError, AttributeError) as e:
            logger.error("Error processing pending events before restart: %s", e)
        finally:
            processing_semaphore.release()
            close_old_connections()
            # Force garbage collection to free memory from processed events
            # NOTE: Manual gc.collect() commented out - Python's automatic GC is sufficient
            # See bug_hunt.md issue #7 for details
            # gc.collect()

    def restart(self) -> None:
        """Restart the watchdog process and schedule the next restart."""
        logger.info("Performing scheduled watchdog restart")
        restart_successful = False

        try:
            logger.debug("Calling stop()...")
            self.stop()

            # Process any pending events before clearing the buffer
            # This ensures we don't lose filesystem events during restart
            logger.debug("Processing pending events before restart...")
            self._process_pending_events()

            # Clear the event buffer after processing
            logger.debug("Clearing event buffer...")
            optimized_event_buffer.clear()

            logger.debug("Stop() completed, waiting 1 second...")
            time.sleep(1)  # Brief pause to ensure clean shutdown
            logger.debug("Calling start() with force_recreate=True...")
            # Use force_recreate=True to prevent memory leaks from accumulated observer state
            self.start(force_recreate=True)
            restart_successful = True
            logger.info("Watchdog restart completed successfully")
        except Exception as e:
            # Broad exception catch is intentional - capture all restart failures for logging/recovery
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
            # Broad exception catch is intentional - threading.Timer rarely fails, but catch all errors
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

    def cleanup(self) -> None:
        """
        Clean up resources before disposing of this handler instance.

        Cancels any pending timers to prevent them from executing after
        the handler is replaced. This prevents memory leaks during watchdog restarts.
        """
        with self.timer_lock:
            if self.event_timer is not None:
                logger.debug("Cleaning up event handler %s - cancelling pending timer", self.instance_id)
                self.event_timer.cancel()
                self.event_timer = None
                # Increment generation to invalidate any timers that might still fire
                self.timer_generation += 1

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
        """Buffer events to process them in batches.

        MEMORY OPTIMIZATION: Only creates a new timer if one isn't already running.
        During heavy file activity (e.g., copying thousands of files), this prevents
        creating 10,000+ Timer objects/threads which would consume 500MB-10GB of memory.

        Previous behavior: Cancel and recreate timer for EVERY event (360/min during copies)
        New behavior: Create timer only once per 5-second batch window
        Memory impact: Reduces Timer object creation by 99%+
        """
        try:
            if event.is_directory:
                dirpath = os.path.normpath(event.src_path)
            else:
                dirpath = str(pathlib.Path(os.path.normpath(event.src_path)).parent)

            # Add event to lock-free buffer
            optimized_event_buffer.add_event(dirpath)

            # Only create timer if one doesn't already exist
            with self.timer_lock:
                # Check if timer exists - if so, let it handle all buffered events
                # Don't create a new one for every single filesystem event
                # NOTE: Don't check is_alive() - timer thread completes when it fires,
                # even though processing is still ongoing. Only check if None.
                if self.event_timer is None:
                    # No active timer - create one to process accumulated events
                    self.timer_generation += 1
                    current_generation = self.timer_generation

                    # Create new timer with current generation captured in lambda
                    self.event_timer = threading.Timer(EVENT_PROCESSING_DELAY, lambda: self._process_buffered_events(current_generation))
                    self.event_timer.daemon = True
                    self.event_timer.start()
                # else: Timer exists - events will be picked up when it fires or after processing completes

        except Exception as e:
            # Broad exception catch is intentional - ensure event processing failures don't crash watchdog
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
            # DON'T clear timer yet - keep it to prevent new timer creation during processing
            # Will clear after processing completes

        # Try to acquire the global semaphore without blocking
        # If we can't acquire it, another thread is already processing
        if not processing_semaphore.acquire(blocking=False):
            # Another thread is processing - clear our timer reference and exit
            with self.timer_lock:
                if expected_generation == self.timer_generation:
                    self.event_timer = None
            return

        try:
            # Get unique paths from lock-free buffer (automatic deduplication)
            paths_to_process = optimized_event_buffer.get_events_to_process()

            if paths_to_process:
                logger.info("[Gen %d] Processing %d buffered directory changes", expected_generation, len(paths_to_process))

                # Optimize: Convert paths to SHAs once, then batch query for DirectoryIndex objects
                from quickbbs.models import (
                    DirectoryIndex,  # pylint: disable=import-outside-toplevel
                )

                # Convert paths to SHAs and build path->SHA mapping for reverse lookup
                path_to_sha = {path: get_dir_sha(path) for path in paths_to_process}
                sha_list = list(path_to_sha.values())

                # Load only required fields to reduce memory footprint
                index_dirs = list(DirectoryIndex.objects.filter(dir_fqpn_sha256__in=sha_list).only("dir_fqpn_sha256", "id", "fqpndirectory"))

                # Process existing directories (current behavior)
                if index_dirs:
                    # Wrap DB operation for ASGI compatibility
                    try:
                        # Try async_to_sync wrapper for ASGI compatibility
                        async_to_sync(self._remove_from_cache_indexdirs_async)(index_dirs)
                    except RuntimeError:
                        # Fallback to direct call if not in async context
                        Cache_Storage.remove_multiple_from_cache_indexdirs(index_dirs)

                # NEW: Handle paths that don't exist in DirectoryIndex
                found_shas = {d.dir_fqpn_sha256 for d in index_dirs}
                missing_shas = set(sha_list) - found_shas

                if missing_shas:
                    # Get the original paths for missing SHAs
                    sha_to_path = {sha: path for path, sha in path_to_sha.items()}
                    missing_paths = [sha_to_path[sha] for sha in missing_shas]

                    # Filter to only directories that actually exist on filesystem
                    verified_paths = [p for p in missing_paths if os.path.isdir(p)]

                    if verified_paths:
                        logger.info(
                            "[Gen %d] Found %d new directories not in DirectoryIndex, creating placeholders: %s",
                            expected_generation,
                            len(verified_paths),
                            verified_paths[:5],  # Log first 5 for debugging
                        )

                        # Create placeholder DirectoryIndex entries using add_directory
                        created_dirs = []
                        parent_dirs_to_invalidate = []

                        for path in verified_paths:
                            # Use DirectoryIndex.add_directory which handles parent creation
                            # Returns (success, directory_object)
                            created, dir_obj = DirectoryIndex.add_directory(path)

                            if created and dir_obj:
                                created_dirs.append(dir_obj)
                                logger.debug("Created DirectoryIndex placeholder for: %s", path)

                                # Track parent directory for invalidation
                                if dir_obj.parent_directory:
                                    parent_dirs_to_invalidate.append(dir_obj.parent_directory)

                        # Create invalidated fs_Cache_Tracking entries for new directories
                        if created_dirs:
                            with transaction.atomic():
                                for dir_obj in created_dirs:
                                    fs_Cache_Tracking.objects.update_or_create(
                                        directory=dir_obj,
                                        defaults={
                                            "invalidated": True,
                                            "lastscan": time.time(),
                                        },
                                    )

                            logger.info(
                                "[Gen %d] Created %d fs_Cache_Tracking entries for new directories",
                                expected_generation,
                                len(created_dirs),
                            )

                        # Invalidate parent directories so they rescan and update subdirectory lists
                        if parent_dirs_to_invalidate:
                            # Deduplicate parents
                            unique_parents = list({p.dir_fqpn_sha256: p for p in parent_dirs_to_invalidate if p}.values())

                            if unique_parents:
                                logger.info(
                                    "[Gen %d] Invalidating %d parent directories for new subdirectories",
                                    expected_generation,
                                    len(unique_parents),
                                )
                                try:
                                    async_to_sync(self._remove_from_cache_indexdirs_async)(unique_parents)
                                except RuntimeError:
                                    Cache_Storage.remove_multiple_from_cache_indexdirs(unique_parents)

        except (RuntimeError, DatabaseError, OSError, AttributeError) as e:
            logger.error("Error processing buffered events: %s", e)
        finally:
            # Release the global semaphore to allow next processing run
            processing_semaphore.release()
            # Clear timer reference AFTER processing completes
            # This prevents new timer creation during processing (race condition fix)
            with self.timer_lock:
                if expected_generation == self.timer_generation:
                    self.event_timer = None
            # Watchdog runs in background thread - must close connections
            close_old_connections()
            # Force garbage collection to free memory from processed events
            # NOTE: Manual gc.collect() commented out - Python's automatic GC is sufficient
            # See bug_hunt.md issue #7 for details
            # gc.collect()

    async def _remove_from_cache_indexdirs_async(self, index_dirs: list[Any]) -> None:
        """Async wrapper for cache removal to support ASGI mode.

        Args:
            index_dirs: List of DirectoryIndex objects to remove from cache
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
    (SHA256, path) should be accessed through the OneToOne relationship to DirectoryIndex.
    """

    # Stored as Unix TimeStamp (ms)
    lastscan = models.FloatField(default=0, blank=True)
    invalidated = models.BooleanField(default=False, db_index=True)

    # OneToOne relationship to DirectoryIndex using dir_fqpn_sha256
    # This is the ONLY source of directory information (SHA256 and path)
    directory = models.OneToOneField(
        "quickbbs.DirectoryIndex",
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

    @staticmethod
    def _validate_index_dir(index_dir: Any) -> bool:
        """Validate that an DirectoryIndex object has required attributes.

        Args:
            index_dir: The DirectoryIndex instance to validate

        Returns:
            True if valid, False otherwise
        """
        return bool(index_dir and hasattr(index_dir, "dir_fqpn_sha256") and index_dir.dir_fqpn_sha256)

    def add_from_indexdirs(self, index_dir: Any) -> "fs_Cache_Tracking | None":
        """Add or update a directory in the cache using an DirectoryIndex record.

        Args:
            index_dir: The DirectoryIndex instance containing directory information

        Returns:
            The cache tracking entry or None if error occurred
        """
        # Validate the DirectoryIndex record
        if not self._validate_index_dir(index_dir):
            logger.warning("Attempted to add invalid DirectoryIndex record to cache - rejected")
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
            logger.error("Error adding DirectoryIndex record to cache: %s", e)
            return None

    def add_to_cache(self, dir_path: str) -> "fs_Cache_Tracking" | None:
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
            from quickbbs.directoryindex import DIRECTORYINDEX_SR_CACHE
            from quickbbs.models import (
                DirectoryIndex,  # pylint: disable=import-outside-toplevel
            )

            dir_sha = get_dir_sha(dir_path)
            scan_time = time.time()

            # Fetch the DirectoryIndex instance by dir_sha using optimized cached lookup
            found, index_dir = DirectoryIndex.search_for_directory_by_sha(dir_sha, DIRECTORYINDEX_SR_CACHE, ())
            if not found:
                logger.warning("Cannot add cache entry for %s - DirectoryIndex entry not found", dir_path)
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
        """Remove a directory from cache using an DirectoryIndex record.

        Optimized version that accepts an DirectoryIndex record directly,
        avoiding redundant database lookups when the record is already available.

        Args:
            index_dir: The DirectoryIndex instance to remove from cache

        Returns:
            True if successfully removed, False otherwise
        """
        try:
            if not self._validate_index_dir(index_dir):
                logger.warning("Invalid DirectoryIndex record provided to remove_from_cache_indexdirs")
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
            from quickbbs.directoryindex import DIRECTORYINDEX_SR_CACHE
            from quickbbs.models import (
                DirectoryIndex,  # pylint: disable=import-outside-toplevel
            )

            # Single optimized lookup with prefetched relationships
            found, directory = DirectoryIndex.search_for_directory_by_sha(sha256, DIRECTORYINDEX_SR_CACHE, ())

            if not found:
                logger.warning("Cannot remove cache for SHA %s - DirectoryIndex not found", sha256)
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
        """Remove multiple directories from cache using DirectoryIndex objects.

        Optimized batch version that accepts DirectoryIndex records directly,
        avoiding redundant SHA computation and database lookups.

        :Args:
            index_dirs: List of DirectoryIndex instances to remove from cache

        Returns:
            True if any entries were invalidated, False otherwise
        """
        if not index_dirs:
            return False

        # Extract SHA256 hashes directly from objects (no normalization needed!)
        sha_list = [d.dir_fqpn_sha256 for d in index_dirs if self._validate_index_dir(d)]

        if not sha_list:
            return False

        logger.info("Removing %d directories from cache (object-based)", len(sha_list))

        # Create mapping for later cache clearing (already have the objects!)
        fqpn_by_dir_sha = {d.dir_fqpn_sha256: d for d in index_dirs if self._validate_index_dir(d)}

        # Perform bulk invalidation using helper method
        update_count = self._bulk_invalidate_by_shas(sha_list)

        # Clear layout caches for affected directories - BULK OPERATION
        if update_count > 0:
            self._clear_caches_for_affected_directories(sha_list, fqpn_by_dir_sha)
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

    def _invalidate_cache_entry_indexdirs(self, index_dir: Any) -> "fs_Cache_Tracking" | None:
        """Set a cache entry to invalidated status using an DirectoryIndex record.

        Optimized version that accepts an DirectoryIndex record directly,
        avoiding redundant database lookups.

        Args:
            index_dir: The DirectoryIndex instance

        Returns:
            The updated or created fs_Cache_Tracking entry, or None if invalid
        """
        if not self._validate_index_dir(index_dir):
            logger.warning("Invalid DirectoryIndex record provided to _invalidate_cache_entry_indexdirs")
            return None

        entry, _ = fs_Cache_Tracking.objects.update_or_create(
            directory=index_dir,
            defaults={
                "invalidated": True,
                "lastscan": time.time(),
            },
        )

        # Clear LRU cache to prevent stale DirectoryIndex data
        # This ensures next access will fetch fresh data with updated invalidation status
        from quickbbs.models import (
            directoryindex_cache,  # pylint: disable=import-outside-toplevel
        )

        directoryindex_cache.pop(index_dir.dir_fqpn_sha256, None)

        # Clear cached Cache_Watcher relationship to force fresh query
        # When invalidated=True is set, subsequent is_cached checks should see updated value
        self._clear_cached_relationship(index_dir)

        return entry

    def _invalidate_cache_entry(self, sha256: str) -> "fs_Cache_Tracking" | None:
        """Set a cache entry to invalidated status with current timestamp.

        Args:
            sha256: The SHA256 hash of the directory

        Returns:
            The updated or created fs_Cache_Tracking entry, or None if sha256 is empty or DirectoryIndex not found
        """
        # Reject empty SHA256 values
        if not sha256 or not sha256.strip():
            logger.warning("Attempted to invalidate cache with empty SHA256 - rejected")
            return None

        # Import inside function to avoid circular dependency
        from quickbbs.directoryindex import DIRECTORYINDEX_SR_CACHE
        from quickbbs.models import (
            DirectoryIndex,  # pylint: disable=import-outside-toplevel
        )

        # Fetch the DirectoryIndex instance by dir_sha using optimized cached lookup
        found, index_dir = DirectoryIndex.search_for_directory_by_sha(sha256, DIRECTORYINDEX_SR_CACHE, ())
        if not found:
            logger.warning("Cannot invalidate cache for SHA %s - DirectoryIndex entry not found", sha256)
            return None

        entry, _ = fs_Cache_Tracking.objects.update_or_create(
            directory=index_dir,
            defaults={
                "invalidated": True,
                "lastscan": time.time(),
            },
        )

        # Clear LRU cache to prevent stale DirectoryIndex data
        from quickbbs.models import (
            directoryindex_cache,  # pylint: disable=import-outside-toplevel
        )

        directoryindex_cache.pop(sha256, None)

        # Clear cached Cache_Watcher relationship to force fresh query
        # When invalidated=True is set, subsequent is_cached checks should see updated value
        self._clear_cached_relationship(index_dir)

        return entry

    def _clear_cached_relationship(self, index_dir: Any) -> None:
        """Clear Django's cached Cache_Watcher relationship on a DirectoryIndex object.

        Django caches OneToOne and ForeignKey relationships as _<name>_cache attributes.
        When we update fs_Cache_Tracking.invalidated in the database, we need to clear
        this cached attribute so the next access to is_cached gets fresh data.

        Args:
            index_dir: DirectoryIndex object to clear cached relationship from
        """
        if hasattr(index_dir, "_Cache_Watcher_cache"):
            delattr(index_dir, "_Cache_Watcher_cache")

    def _bulk_invalidate_by_shas(self, sha_list: list[str]) -> int:
        """Perform bulk cache invalidation for a list of SHA256 hashes.

        This is the common logic shared by remove_multiple_from_cache_indexdirs()
        and remove_multiple_from_cache().

        Args:
            sha_list: List of directory SHA256 hashes to invalidate

        Returns:
            Number of cache entries invalidated
        """
        # Import inside function to avoid circular dependency
        from quickbbs.directoryindex import DIRECTORYINDEX_SR_PARENT
        from quickbbs.models import (
            DirectoryIndex,  # pylint: disable=import-outside-toplevel
        )

        # Collect all parent directories using efficient batch query approach
        all_dirs_to_invalidate = DirectoryIndex.get_all_parent_shas(sha_list, DIRECTORYINDEX_SR_PARENT)

        # Update cache entries using bulk operations
        with transaction.atomic():
            # Get all DirectoryIndex records and capture their SHAs
            # Use .only() to load minimal fields, reducing memory footprint
            # Evaluate queryset ONCE and cache results to avoid double query
            index_dirs_list = list(DirectoryIndex.objects.filter(dir_fqpn_sha256__in=all_dirs_to_invalidate).only("dir_fqpn_sha256", "id"))

            # Extract SHAs from already-loaded objects (no additional query)
            found_shas = {d.dir_fqpn_sha256 for d in index_dirs_list}

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
                # Reuse already-loaded objects (no additional query)
                sha_to_indexdir = {d.dir_fqpn_sha256: d for d in index_dirs_list}
                new_entries = [fs_Cache_Tracking(directory=sha_to_indexdir[sha], invalidated=True, lastscan=current_time) for sha in missing_shas]
                fs_Cache_Tracking.objects.bulk_create(new_entries)
                update_count += len(new_entries)
                # Explicitly delete large objects to free memory
                del sha_to_indexdir
                del new_entries

            # Explicitly delete large objects to free memory
            del all_dirs_to_invalidate
            del index_dirs_list
            del found_shas
            del existing_cache_shas
            del missing_shas

        return update_count

    def _clear_caches_for_affected_directories(self, sha_list: list[str], fqpn_by_dir_sha: dict[str, Any]) -> None:
        """Clear layout and DirectoryIndex caches for affected directories.

        Args:
            sha_list: List of directory SHA256 hashes
            fqpn_by_dir_sha: Mapping of SHA256 -> DirectoryIndex objects
        """
        # Build list of affected directories, filtering out None values and objects without pk
        affected_directories = [
            fqpn_by_dir_sha[sha]
            for sha in set(sha_list) & fqpn_by_dir_sha.keys()
            if (fqpn_by_dir_sha[sha] is not None and hasattr(fqpn_by_dir_sha[sha], "pk") and fqpn_by_dir_sha[sha].pk is not None)
        ]

        if affected_directories:
            self._clear_layout_cache_bulk(affected_directories)
            self._clear_directoryindex_cache_bulk(affected_directories)

    def remove_multiple_from_cache(self, dir_names: list[str]) -> bool:
        """Remove multiple directories from cache in a single transaction.

        DEPRECATED: Use remove_multiple_from_cache_indexdirs() instead to avoid redundant
        SHA computation and database lookups.

        :param dir_names: List of directory paths to remove from cache
        :return: True if any entries were invalidated, False otherwise
        """
        warnings.warn(
            "remove_multiple_from_cache(dir_names: list[str]) is deprecated. " "Use remove_multiple_from_cache_indexdirs(index_dirs) instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        if not dir_names:
            return False

        # Import inside function to avoid circular dependency
        from quickbbs.models import (
            DirectoryIndex,  # pylint: disable=import-outside-toplevel
        )

        # Convert all directory names to SHA256 hashes (deduplicate first for efficiency)
        # Compute SHA→path mapping ONCE, then extract SHAs to avoid duplicate computation
        sha_to_path = {get_dir_sha(path): path for path in set(dir_names)}
        sha_list = list(sha_to_path.keys())

        if not sha_list:
            return False

        logger.info("Removing %d directories from cache", len(sha_list))

        # Get affected directories (only load fields needed for cache clearing)
        fqpn_by_dir_sha = {
            d.dir_fqpn_sha256: d for d in DirectoryIndex.objects.filter(dir_fqpn_sha256__in=sha_list).only("dir_fqpn_sha256", "id", "fqpndirectory")
        }

        # Check for missing DirectoryIndex entries and create them
        missing_shas = set(sha_list) - set(fqpn_by_dir_sha.keys())
        if missing_shas:
            logger.info("Creating %d missing DirectoryIndex entries", len(missing_shas))
            for missing_sha in missing_shas:
                dir_path = sha_to_path.get(missing_sha)
                if dir_path:
                    try:
                        _, new_dir = DirectoryIndex.add_directory(dir_path)
                        # Only add to dict if new_dir is valid and has required attributes
                        if new_dir is not None and hasattr(new_dir, "pk") and new_dir.pk is not None:
                            fqpn_by_dir_sha[missing_sha] = new_dir
                            logger.debug("Created DirectoryIndex entry for %s", dir_path)
                        else:
                            logger.warning("DirectoryIndex.add_directory returned invalid object for %s", dir_path)
                    except (DatabaseError, OSError) as e:
                        logger.error("Failed to create DirectoryIndex entry for %s: %s", dir_path, e)

        # Perform bulk invalidation using helper method
        update_count = self._bulk_invalidate_by_shas(sha_list)

        # Clear layout caches for affected directories - BULK OPERATION
        if update_count > 0:
            self._clear_caches_for_affected_directories(sha_list, fqpn_by_dir_sha)
            logger.info("Successfully invalidated %d cache entries", update_count)

        return update_count > 0

    def _clear_layout_cache_bulk(self, directories: list[Any]) -> None:
        """
        Clear layout cache for multiple directories efficiently.

        Uses shared clear_layout_cache_for_directories() function to avoid code duplication.
        Clears ALL sort orderings (0, 1, 2) for each directory.

        Args:
            directories: List of DirectoryIndex objects to clear cache for

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

            # Use shared cache clearing function - extract PKs from directory objects
            directory_ids = {d.pk for d in directories if d and hasattr(d, "pk") and d.pk}
            cleared_count = clear_layout_cache_for_directories(directory_ids)
            logger.debug("Cleared %d layout cache entries for %d directories", cleared_count, len(directory_ids))

        except (KeyError, ImportError, AttributeError) as e:
            logger.error("Error clearing layout cache for directories: %s", e)

    def _clear_directoryindex_cache_bulk(self, directories: list[Any]) -> None:
        """
        Clear DirectoryIndex LRU cache for invalidated directories.

        When directories are invalidated, their cached DirectoryIndex objects must be
        removed from the LRU cache to prevent stale is_cached checks. The cache
        key is the directory's SHA256 hash.

        :Args:
            directories: List of DirectoryIndex objects that were invalidated
        """
        try:
            # pylint: disable=import-outside-toplevel
            from quickbbs.models import directoryindex_cache

            # Extract SHA256s and directly delete from cache
            cleared_count = 0
            for directory in directories:
                if directory and hasattr(directory, "dir_fqpn_sha256"):
                    sha = directory.dir_fqpn_sha256
                    # Get the cached object before removing it
                    cached_obj = directoryindex_cache.pop(sha, None)
                    if cached_obj is not None:
                        # Clear Django ORM relationship cache on the object
                        # This prevents stale is_cached checks if the object is held elsewhere
                        self._clear_cached_relationship(cached_obj)
                        cleared_count += 1

            logger.debug("Cleared %d DirectoryIndex cache entries for %d directories", cleared_count, len(directories))

        except (KeyError, ImportError, AttributeError) as e:
            logger.error("Error clearing DirectoryIndex cache for directories: %s", e)
