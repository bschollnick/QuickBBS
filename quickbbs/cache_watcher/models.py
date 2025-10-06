"""Cache Watcher Models for QuickBBS.

Provides filesystem monitoring and cache invalidation for the QuickBBS gallery application.
Uses Watchdog to monitor the albums directory for changes and automatically invalidates
affected cache entries to ensure data consistency.

Key Components:
    - WatchdogManager: Manages the watchdog process with automatic restarts every 4 hours
    - CacheFileMonitorEventHandler: Batches filesystem events for efficient processing
    - fs_Cache_Tracking: Database model for tracking cache invalidation state

The system buffers events for 5 seconds before processing to handle bulk operations efficiently.
"""

import asyncio
import collections
import hashlib
import logging
import os
import pathlib
import sys
import threading
import time
from collections import defaultdict
from functools import lru_cache
from typing import Any, Optional

from asgiref.sync import async_to_sync, iscoroutinefunction
from cache_watcher.watchdogmon import watchdog
from cachetools.keys import hashkey
from django.apps import AppConfig
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, models, transaction
from watchdog.events import FileSystemEvent, FileSystemEventHandler

from quickbbs.common import get_dir_sha, normalize_fqpn

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

# Global watchdog restart timer
# MUST use threading.Lock - accessed by threading.Timer callbacks in OS threads
watchdog_restart_timer = None
watchdog_restart_lock = threading.Lock()

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
                    logger.info(f"Watchdog started monitoring: {self.monitor_path}")
                    # Always schedule restart when we start successfully
                    logger.debug("Scheduling restart timer...")
                    self._schedule_restart()
                except Exception as e:
                    logger.error(f"Failed to start watchdog: {e}", exc_info=True)
                    raise
            else:
                logger.info("Watchdog already running")

    def stop(self) -> None:
        """Stop the watchdog but don't cancel restart timer during restart process."""
        with self.lock:
            if self.is_running:
                try:
                    watchdog.shutdown()
                    self.is_running = False
                    logger.info("Watchdog stopped")
                except Exception as e:
                    logger.error(f"Error stopping watchdog: {e}")

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
                    logger.error(f"Error stopping watchdog: {e}")

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
            logger.error(f"Error during watchdog restart: {e}", exc_info=True)

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
                logger.debug(f"Cancelled existing restart timer (was_alive: {was_alive})")
                self.restart_timer = None

            # Create new timer
            self.restart_timer = threading.Timer(WATCHDOG_RESTART_INTERVAL, self.restart)
            self.restart_timer.daemon = True
            self.restart_timer.start()

            # Verify timer started successfully
            if self.restart_timer.is_alive():
                logger.info(f"✓ Next watchdog restart scheduled in {WATCHDOG_RESTART_INTERVAL/3600:.1f} hours")
                logger.debug(f"Timer object: {self.restart_timer}, thread name: {self.restart_timer.name}")
            else:
                logger.error("⚠ Timer failed to start!")

        except Exception as e:
            logger.error(f"Error scheduling restart: {e}", exc_info=True)


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
        self.instance_id = id(self)
        # Timer generation counter - incremented each time a new timer is created
        # Used to prevent old timers from processing if they fire after being cancelled
        self.timer_generation = 0

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
            logger.error(f"Error buffering event {event.src_path}: {e}")

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
                logger.debug(f"Timer generation {expected_generation} superseded by {self.timer_generation}, skipping")
                return
            # Clear timer reference now that we're executing
            self.event_timer = None

        # Try to acquire the global semaphore without blocking
        # If we can't acquire it, another thread is already processing
        if not processing_semaphore.acquire(blocking=False):
            logger.debug("Already processing events, skipping duplicate call")
            return

        try:
            # Get unique paths from lock-free buffer (automatic deduplication)
            paths_to_process = optimized_event_buffer.get_events_to_process()

            if paths_to_process:
                logger.info(f"Processing {len(paths_to_process)} buffered directory changes")
                # Convert set to list for cache removal function
                # Wrap DB operation for ASGI compatibility - this ensures the operation
                # works correctly whether running under WSGI or ASGI
                try:
                    # Try async_to_sync wrapper for ASGI compatibility
                    async_to_sync(self._remove_from_cache_async)(list(paths_to_process))
                except RuntimeError:
                    # Fallback to direct call if not in async context
                    Cache_Storage.remove_multiple_from_cache(list(paths_to_process))

        except Exception as e:
            logger.error(f"Error processing buffered events: {e}")
        finally:
            # Release the global semaphore to allow next processing run
            processing_semaphore.release()
            # Watchdog runs in background thread - must close connections
            close_old_connections()

    async def _remove_from_cache_async(self, paths: list[str]) -> None:
        """Async wrapper for cache removal to support ASGI mode.

        :param paths: List of directory paths to remove from cache
        """
        from asgiref.sync import sync_to_async

        # Run the synchronous database operation in a thread pool
        await sync_to_async(Cache_Storage.remove_multiple_from_cache)(paths)


class fs_Cache_Tracking(models.Model):
    """
    Cache_Storage table is used to signify that a directory has been scanned and is up to date.
    """

    directory_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )
    DirName = models.CharField(db_index=False, max_length=384, default="", blank=True)
    # Stored as Unix TimeStamp (ms)
    lastscan = models.FloatField(default=0, blank=True)  # Fixed: removed string default
    invalidated = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["directory_sha256", "invalidated"]),
        ]

    @staticmethod
    def clear_all_records() -> int:
        """Mark all records as invalidated.

        :return: Number of records invalidated
        """
        try:
            updated_count = fs_Cache_Tracking.objects.all().update(invalidated=True)
            logger.info(f"Invalidated {updated_count} cache records")
            return updated_count
        except Exception as e:
            logger.error(f"Error clearing all cache records: {e}")
            return 0

    def add_to_cache(self, DirName: str) -> Optional["fs_Cache_Tracking"]:
        """Add or update a directory in the cache.

        :param DirName: The fully qualified pathname of the directory
        :return: The cache tracking entry or None if error occurred
        """
        try:
            dir_sha = get_dir_sha(DirName)
            scan_time = time.time()
            defaults = {
                "directory_sha256": dir_sha,
                "lastscan": scan_time,
                "invalidated": False,
                "DirName": DirName,
            }

            entry, created = fs_Cache_Tracking.objects.update_or_create(
                directory_sha256=dir_sha,
                defaults=defaults,
            )
            action = "Created" if created else "Updated"
            logger.debug(f"{action} cache entry for: {DirName}")
            return entry

        except Exception as e:
            logger.error(f"Error adding {DirName} to cache: {e}")
            return None

    def sha_exists_in_cache(self, sha256: str) -> bool:
        """Check if a directory SHA exists in cache and is not invalidated.

        :param sha256: The SHA256 hash of the directory
        :return: True if SHA exists and is not invalidated, False otherwise
        """
        try:
            return fs_Cache_Tracking.objects.filter(directory_sha256=sha256, invalidated=False).exists()
        except Exception as e:
            logger.error(f"Error checking SHA existence in cache: {e}")
            return False

    def remove_from_cache_sha(self, sha256: str) -> bool:
        """Remove a directory from cache by SHA256.

        :param sha256: The SHA256 hash of the directory
        :return: True if successfully removed, False otherwise
        """
        try:
            from quickbbs.common import safe_get_with_callback
            from quickbbs.models import IndexDirs

            # Get the directory information before updating
            directory_found, directory = safe_get_with_callback(
                IndexDirs,
                found_callback=lambda d: d.invalidate_thumb(),
                dir_fqpn_sha256=sha256,
            )

            # Update cache entry
            scan_time = time.time()
            defaults = {
                "lastscan": scan_time,
                "invalidated": True,
            }

            entry, created = fs_Cache_Tracking.objects.update_or_create(
                directory_sha256=sha256,
                defaults=defaults,
            )

            # Clear layout cache if needed
            if directory_found:
                self._clear_layout_cache(directory)

            logger.debug(f"Removed cache entry for SHA: {sha256}")
            return True

        except Exception as e:
            logger.error(f"Error removing SHA {sha256} from cache: {e}")
            return False

    def remove_from_cache_name(self, DirName: str) -> bool:
        """Remove a directory from cache by name.

        :param DirName: The fully qualified pathname of the directory
        :return: True if successfully removed, False otherwise
        """
        try:
            sha256 = get_dir_sha(DirName)
            return self.remove_from_cache_sha(sha256)
        except Exception as e:
            logger.error(f"Error removing {DirName} from cache: {e}")
            return False

    def remove_multiple_from_cache(self, dir_names: list[str]) -> bool:
        """Remove multiple directories from cache in a single transaction.

        :param dir_names: List of directory paths to remove from cache
        :return: True if any entries were invalidated, False otherwise
        """
        if not dir_names:
            return False

        from quickbbs.models import IndexDirs

        # Convert all directory names to SHA256 hashes (deduplicate first for efficiency)
        sha_list = [get_dir_sha(path) for path in set(dir_names)]

        if not sha_list:
            return False

        logger.info(f"Removing {len(sha_list)} directories from cache")

        # Get affected directories (only load fields needed for cache clearing)
        directories = list(IndexDirs.objects.filter(dir_fqpn_sha256__in=sha_list).only("dir_fqpn_sha256", "id", "fqpndirectory"))
        fqpn_by_dir_sha = {d.dir_fqpn_sha256: d for d in directories}

        # Update cache entries in a single transaction
        with transaction.atomic():
            update_count = fs_Cache_Tracking.objects.filter(directory_sha256__in=sha_list, invalidated=False).update(
                invalidated=True, lastscan=time.time()
            )

        # Clear layout caches for affected directories
        if update_count > 0:
            for sha in set(sha_list) & fqpn_by_dir_sha.keys():
                self._clear_layout_cache(fqpn_by_dir_sha[sha])

            logger.info(f"Successfully invalidated {update_count} cache entries")

        return update_count > 0

    def _clear_layout_cache(self, directory: Any) -> None:
        """Clear layout cache for a specific directory.

        :param directory: The IndexDirs object for the directory
        """
        try:
            # Import inside function to avoid circular dependency:
            # frontend.managers may import cache_watcher.models
            from frontend.managers import (  # pylint: disable=import-outside-toplevel
                layout_manager,
                layout_manager_cache,
            )

            layout = layout_manager(directory=directory, sort_ordering=0)
            for page_number in range(1, layout["total_pages"] + 1):
                key = hashkey(
                    page_number=page_number,
                    directory=directory,
                    sort_ordering=0,
                )
                if key in layout_manager_cache:
                    del layout_manager_cache[key]

        except Exception as e:
            logger.error(f"Error clearing layout cache for directory: {e}")


# Application startup/shutdown hooks removed - handled in apps.py


def shutdown_watchdog() -> None:
    """Graceful shutdown function - call this when the application shuts down."""
    logger.info("Shutting down watchdog manager...")
    watchdog_manager.stop()


# Watchdog initialization removed - now handled exclusively by apps.py
# This prevents duplicate startup attempts
