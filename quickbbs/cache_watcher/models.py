"""
Models for the Cache Watchers for QuickBBS, optimized for performance.
This is a simple cache watcher that will monitor the directories and files
in the albums directory and all subdirectories for changes. When a change is detected,
the directory will be removed from the Cache_Storage table, which will cause it to be rescanned
if that directory is accessed.
"""

import hashlib
import logging
import os
import pathlib
import sys
import threading
import time
from collections import defaultdict
from functools import lru_cache

from cache_watcher.watchdogmon import watchdog
from cachetools.keys import hashkey
from django.apps import AppConfig
from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections, models, transaction
from watchdog.events import FileSystemEventHandler

from quickbbs.common import get_dir_sha, normalize_fqpn

# Configure logging
logger = logging.getLogger(__name__)

Cache_Storage = None

# Global event buffer for batch processing
event_buffer = defaultdict(int)
event_buffer_lock = threading.Lock()
EVENT_PROCESSING_DELAY = 5  # seconds
# WATCHDOG_RESTART_INTERVAL = 12 * 60 * 60  # 12 hours in seconds
WATCHDOG_RESTART_INTERVAL = 0.5 * 60 * 60  # 30 minutes in seconds

# Global watchdog restart timer
watchdog_restart_timer = None
watchdog_restart_lock = threading.Lock()


class WatchdogManager:
    """Manages periodic restart of the watchdog process"""

    def __init__(self):
        self.restart_timer = None
        self.lock = threading.Lock()
        self.monitor_path = os.path.join(settings.ALBUMS_PATH, "albums")
        self.event_handler = None
        self.is_running = False

    def start(self):
        """Start the watchdog with periodic restart capability"""
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

    def stop(self):
        """Stop the watchdog but don't cancel restart timer during restart process"""
        with self.lock:
            if self.is_running:
                try:
                    watchdog.shutdown()
                    self.is_running = False
                    logger.info("Watchdog stopped")
                except Exception as e:
                    logger.error(f"Error stopping watchdog: {e}")

    def shutdown(self):
        """Complete shutdown - stop watchdog and cancel restart timer"""
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

    def restart(self):
        """Restart the watchdog process and schedule the next restart"""
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

    def _schedule_restart(self):
        """Schedule the next restart - must be called while holding self.lock"""
        try:
            # Cancel existing timer if it exists
            if self.restart_timer:
                was_alive = self.restart_timer.is_alive()
                self.restart_timer.cancel()
                logger.debug(
                    f"Cancelled existing restart timer (was_alive: {was_alive})"
                )
                self.restart_timer = None

            # Create new timer
            self.restart_timer = threading.Timer(
                WATCHDOG_RESTART_INTERVAL, self.restart
            )
            self.restart_timer.daemon = True
            self.restart_timer.start()

            # Verify timer started successfully
            if self.restart_timer.is_alive():
                logger.info(
                    f"✓ Next watchdog restart scheduled in {WATCHDOG_RESTART_INTERVAL/3600:.1f} hours"
                )
                logger.debug(
                    f"Timer object: {self.restart_timer}, thread name: {self.restart_timer.name}"
                )
            else:
                logger.error("⚠ Timer failed to start!")

        except Exception as e:
            logger.error(f"Error scheduling restart: {e}", exc_info=True)


# Global watchdog manager instance
watchdog_manager = WatchdogManager()


class CacheFileMonitorEventHandler(FileSystemEventHandler):
    """
    Event Handler for the Watchdog Monitor for QuickBBS, optimized to batch process events.
    """

    def __init__(self):
        super().__init__()
        self.event_timer = None
        self.timer_lock = threading.Lock()

    def on_created(self, event):
        self._buffer_event(event)

    def on_deleted(self, event):
        self._buffer_event(event)

    def on_modified(self, event):
        self._buffer_event(event)

    def on_moved(self, event):
        self._buffer_event(event)

    def _buffer_event(self, event):
        """Buffer events to process them in batches"""
        try:
            if event.is_directory:
                dirpath = os.path.normpath(event.src_path)
            else:
                dirpath = str(pathlib.Path(os.path.normpath(event.src_path)).parent)

            with event_buffer_lock:
                event_buffer[dirpath] += 1

                # Reset or create timer with thread safety
                with self.timer_lock:
                    if self.event_timer is not None:
                        self.event_timer.cancel()

                    self.event_timer = threading.Timer(
                        EVENT_PROCESSING_DELAY, self._process_buffered_events
                    )
                    self.event_timer.daemon = True
                    self.event_timer.start()

        except Exception as e:
            logger.error(f"Error buffering event {event.src_path}: {e}")

    def _process_buffered_events(self):
        """Process all buffered events at once"""
        paths_to_process = []

        #       try:
        with event_buffer_lock:
            if event_buffer:  # Only process if there are events
                paths_to_process = list(event_buffer.keys())
                event_buffer.clear()

        if paths_to_process:
            logger.info(
                f"Processing {len(paths_to_process)} buffered directory changes"
            )
            Cache_Storage.remove_multiple_from_cache(paths_to_process)


#        except Exception as e:
#            logger.error(f"Error processing buffered events: {e}")


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
    lastscan = models.FloatField(
        default=0, blank=True  # Fixed: removed string default
    )  # Stored as Unix TimeStamp (ms)
    invalidated = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["directory_sha256", "invalidated"]),
        ]

    @staticmethod
    def clear_all_records():
        """Mark all records as invalidated"""
        try:
            updated_count = fs_Cache_Tracking.objects.all().update(invalidated=True)
            logger.info(f"Invalidated {updated_count} cache records")
            return updated_count
        except Exception as e:
            logger.error(f"Error clearing all cache records: {e}")
            return 0

    def add_to_cache(self, DirName):
        """Add or update a directory in the cache"""
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

    def sha_exists_in_cache(self, sha256):
        """Check if a directory SHA exists in cache and is not invalidated"""
        try:
            return fs_Cache_Tracking.objects.filter(
                directory_sha256=sha256, invalidated=False
            ).exists()
        except Exception as e:
            logger.error(f"Error checking SHA existence in cache: {e}")
            return False

    def remove_from_cache_sha(self, sha256):
        """Remove a directory from cache by SHA256"""
        try:
            from frontend.views import layout_manager, layout_manager_cache
            from quickbbs.models import IndexDirs

            # Get the directory information before updating
            directory_found = False
            try:
                directory = IndexDirs.objects.get(dir_fqpn_sha256=sha256)
                directory_found = True
                directory.invalidate_thumb()
                directory.save()
            except IndexDirs.DoesNotExist:
                pass

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

    def remove_from_cache_name(self, DirName):
        """Remove a directory from cache by name"""
        try:
            sha256 = get_dir_sha(DirName)
            return self.remove_from_cache_sha(sha256)
        except Exception as e:
            logger.error(f"Error removing {DirName} from cache: {e}")
            return False

    def remove_multiple_from_cache(self, dir_names):
        """Remove multiple directories from cache in a single transaction"""
        if not dir_names:
            return False
        #
        #        try:
        from frontend.views import layout_manager, layout_manager_cache
        from quickbbs.models import IndexDirs

        close_old_connections()
        # Convert all directory names to SHA256 hashes
        sha_list = list(set([get_dir_sha(dir_name) for dir_name in dir_names]))

        if not sha_list:
            return False

        logger.info(f"Removing {len(sha_list)} directories from cache")

        # Get affected directories
        directories = list(IndexDirs.objects.filter(dir_fqpn_sha256__in=sha_list))
        fqpn_by_dir_sha = {d.dir_fqpn_sha256: d for d in directories}

        # Update cache entries in a single transaction
        with transaction.atomic():
            update_count = fs_Cache_Tracking.objects.filter(
                directory_sha256__in=sha_list, invalidated=False
            ).update(invalidated=True, lastscan=time.time())

        # Clear layout caches for affected directories
        if update_count > 0:
            for sha in sha_list:
                if sha in fqpn_by_dir_sha:
                    self._clear_layout_cache(fqpn_by_dir_sha[sha])

            logger.info(f"Successfully invalidated {update_count} cache entries")

        return update_count > 0

        # except Exception as e:
        #     logger.error(f"Error in remove_multiple_from_cache: {e}")
        #     return False
        #       finally:
        close_old_connections()

    def _clear_layout_cache(self, directory):
        """Clear layout cache for a specific directory"""
        try:
            from frontend.views import layout_manager, layout_manager_cache

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


# Application startup/shutdown hooks
class CacheWatcherConfig(AppConfig):
    """Django app configuration for cache watcher"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "cache_watcher"

    def ready(self):
        """Start watchdog when Django app is ready"""
        try:
            watchdog_manager.start()
        except Exception as e:
            logger.error(f"Failed to start watchdog manager: {e}")


def shutdown_watchdog():
    """Graceful shutdown function - call this when the application shuts down"""
    logger.info("Shutting down watchdog manager...")
    watchdog_manager.stop()


# Initialize watchdog (kept for backward compatibility)
# Consider removing this in favor of the app config approach
try:
    watchdog_manager.start()
except Exception as e:
    logger.error(f"Failed to initialize watchdog: {e}")
