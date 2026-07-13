"""Cache Watcher Models for QuickBBS.

Provides filesystem monitoring and cache invalidation for the QuickBBS gallery application.
Uses Watchdog to monitor the albums directory for changes and automatically invalidates
affected cache entries to ensure data consistency.

Key Components:
    - WatchdogManager: Manages the watchdog process with automatic restarts every 4 hours
    - CacheFileMonitorEventHandler: Batches filesystem events for efficient processing
    - CacheStatisticsTracking: Database model for cache hit/miss statistic snapshots

Invalidation state itself lives on DirectoryIndex (cache_invalidated /
cache_lastscan fields); the handlers here call DirectoryIndex.invalidate_caches()
to flip it.

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

import logging
import os
import pathlib
import threading
import time
from typing import Any

from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.db import close_old_connections, models
from django.db.utils import DatabaseError
from watchdog.events import FileSystemEvent, FileSystemEventHandler

from cache_watcher.watchdogmon import watchdog
from quickbbs.common import get_dir_sha
from quickbbs.models import DirectoryIndex

# Configure logging
logger = logging.getLogger(__name__)


class LockFreeEventBuffer:
    """
    Thread-safe event buffer for file system events with deduplication at insert.

    Paths are stored in a set, so duplicate events for the same directory
    (the common case — many file events within one directory) occupy a single
    slot. The max_size cap therefore applies to *unique* directories, which
    prevents the previous failure mode where a bulk copy spanning many
    directories overflowed a raw event deque and silently dropped
    invalidations.

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
            max_size: Maximum number of unique directories to buffer before auto-cleanup
        """
        # Deduplicated set of directory paths with pending events
        self._events: set[str] = set()
        # RLock allows recursive locking if needed
        # MUST be threading.RLock (see class docstring for why)
        self._lock = threading.RLock()
        self._max_size = max_size

    def add_event(self, dirpath: str) -> None:
        """
        Add directory path to event buffer (deduplicated).

        Args:
            dirpath: Directory path that had file system changes
        """
        with self._lock:
            self._events.add(dirpath)

            # Safety valve: with insert-time dedup this should realistically
            # never trigger (it requires >max_size *unique* directories in one
            # debounce window). If it does, drop arbitrary entries and say so.
            if len(self._events) > self._max_size:
                cleanup_target = int(self._max_size * 0.5)  # Keep 50% of max size
                dropped = len(self._events) - cleanup_target
                while len(self._events) > cleanup_target:
                    self._events.pop()
                logger.warning(
                    "Event buffer overflow: dropped %d directory invalidation events (max_size=%d)",
                    dropped,
                    self._max_size,
                )

    def get_events_to_process(self) -> set[str]:
        """
        Get unique directory paths and clear buffer.

        Returns:
            Set of unique directory paths that need cache invalidation
        """
        with self._lock:
            if not self._events:
                return set()

            unique_paths = self._events
            self._events = set()
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

# Event processing configuration - sourced from quickbbs_settings
EVENT_PROCESSING_DELAY = settings.EVENT_PROCESSING_DELAY
WATCHDOG_RESTART_INTERVAL = settings.WATCHDOG_RESTART_INTERVAL

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
        """Initialize the manager with no timer or handler running yet."""
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
                # TODO: narrow to watchdog library's specific exception types
                # once they are documented (RuntimeError, OSError, threading errors)
                except Exception as e:
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
                # TODO: narrow to watchdog library's specific exception types
                # once they are documented (RuntimeError, OSError, threading errors)
                except Exception as e:
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

                # Convert paths to SHAs and batch query for DirectoryIndex objects
                sha_list = [get_dir_sha(path) for path in paths_to_process]
                index_dirs = list(DirectoryIndex.objects.filter(dir_fqpn_sha256__in=sha_list).only("dir_fqpn_sha256", "id", "fqpndirectory"))

                if index_dirs:
                    # Process cache invalidation
                    DirectoryIndex.invalidate_caches(index_dirs)
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
        except Exception as e:  # TODO: narrow once watchdog restart failure modes are catalogued (watchdog.observers errors, OSError, RuntimeError)
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

        except Exception as e:  # TODO: narrow to (RuntimeError, threading.Error) — threading.Timer failure modes are not well-documented
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
        """Initialize the event handler with no pending timer."""
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

        except Exception as e:  # TODO: narrow once watchdog event types are enumerated — filesystem events can raise many OS-level errors
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
                        DirectoryIndex.invalidate_caches(index_dirs)

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

                        # Create placeholder DirectoryIndex entries using add_directory.
                        # New rows are born cache_invalidated=True by field default,
                        # so no separate tracking write is needed.
                        created_dirs = []
                        parent_dirs_to_invalidate = []

                        for path in verified_paths:
                            # Use DirectoryIndex.add_directory which handles parent creation
                            # Returns (success, directory_object); these paths are known to be
                            # missing from DirectoryIndex, so success means newly created.
                            success, dir_obj = DirectoryIndex.add_directory(path)

                            if success and dir_obj:
                                created_dirs.append(dir_obj)
                                logger.debug("Created DirectoryIndex placeholder for: %s", path)

                                # Track parent directory for invalidation
                                if dir_obj.parent_directory:
                                    parent_dirs_to_invalidate.append(dir_obj.parent_directory)

                        if created_dirs:
                            logger.info(
                                "[Gen %d] Created %d DirectoryIndex placeholders (born invalidated)",
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
                                    DirectoryIndex.invalidate_caches(unique_parents)

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
        """Async wrapper for cache invalidation to support ASGI mode.

        Args:
            index_dirs: List of DirectoryIndex objects to invalidate
        """
        # Run the synchronous database operation in a thread pool
        await sync_to_async(DirectoryIndex.invalidate_caches)(index_dirs)


class CacheStatisticsTracking(models.Model):
    """
    Periodic snapshot of MonitoredLRUCache hit/miss statistics.

    One row per cache name. Updated by the snapshot_cache_statistics periodic
    task. Provides persistent, history-queryable cache performance data that
    is immune to HTTP caching issues.

    Table name: cache_statistics_tracking
    """

    cache_name = models.CharField(max_length=100, unique=True, db_index=True)
    hits = models.BigIntegerField(default=0)
    misses = models.BigIntegerField(default=0)
    current_size = models.IntegerField(default=0)
    max_size = models.IntegerField(default=0)
    last_snapshot_at = models.DateTimeField(auto_now=True)
    last_reset_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Model metadata: maps this model to the cache_statistics_tracking table."""

        db_table = "cache_statistics_tracking"

    def __str__(self) -> str:
        """Return string representation showing cache name and hit rate."""
        total = self.hits + self.misses
        rate = f"{self.hits / total * 100:.1f}%" if total > 0 else "n/a"
        return f"{self.cache_name}: {rate} hit rate ({self.hits}h/{self.misses}m)"

    @property
    def hit_rate(self) -> float:
        """
        Return hit rate as a percentage (0.0–100.0).

        Returns:
            Float percentage, or 0.0 if no requests recorded.
        """
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0
