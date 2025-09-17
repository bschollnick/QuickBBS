"""
Models for the Cache Watchers for QuickBBS, optimized for performance.
This is a simple cache watcher that will monitor the directories and files
in the albums directory and all subdirectories for changes. When a change is detected,
the directory will be removed from the Cache_Storage table, which will cause it to be rescanned
if that directory is accessed.
"""

import hashlib
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

Cache_Storage = None

# Global event buffer for batch processing
event_buffer = defaultdict(int)
event_buffer_lock = threading.Lock()
EVENT_PROCESSING_DELAY = 5  # seconds


class CacheFileMonitorEventHandler(FileSystemEventHandler):
    """
    Event Handler for the Watchdog Monitor for QuickBBS, optimized to batch process events.
    """

    def __init__(self):
        super().__init__()
        self.event_timer = None

    def on_created(self, event):
        self.buffer_event(event)

    def on_deleted(self, event):
        self.buffer_event(event)

    def on_modified(self, event):
        self.buffer_event(event)

    def on_moved(self, event):
        self.buffer_event(event)

    def buffer_event(self, event):
        """Buffer events to process them in batches"""
        if event.is_directory:
            dirpath = os.path.normpath(event.src_path)
        else:
            dirpath = str(pathlib.Path(os.path.normpath(event.src_path)).parent)

        with event_buffer_lock:
            event_buffer[dirpath] += 1

            # Reset or create timer
            if self.event_timer is not None:
                self.event_timer.cancel()

            self.event_timer = threading.Timer(
                EVENT_PROCESSING_DELAY, self.process_buffered_events
            )
            self.event_timer.daemon = True
            self.event_timer.start()

    def process_buffered_events(self):
        """Process all buffered events at once"""
        paths_to_process = []

        with event_buffer_lock:
            paths_to_process = list(event_buffer.keys())
            event_buffer.clear()

        if paths_to_process:
            Cache_Storage.remove_multiple_from_cache(paths_to_process)


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
        default="", blank=True
    )  # Stored as Unix TimeStamp (ms)
    invalidated = models.BooleanField(default=False)

    @staticmethod
    def clear_all_records():
        fs_Cache_Tracking.objects.all().update(invalidated=True)

    def add_to_cache(self, DirName):
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
            create_defaults=defaults,
        )

    def sha_exists_in_cache(self, sha256):
        return fs_Cache_Tracking.objects.filter(
            directory_sha256=sha256, invalidated=False
        ).exists()

    def remove_from_cache_sha(self, sha256):
        from frontend.views import layout_manager, layout_manager_cache

        from quickbbs.models import IndexDirs

        # try:
        # Get the directory information before Invalidating
        try:
            directory = IndexDirs.objects.get(dir_fqpn_sha256=sha256)
            directory_found = True
            directory.invalidate_thumb()
            directory.save()
        except IndexDirs.DoesNotExist:
            directory_found = False

        scan_time = time.time()
        defaults = {
            "directory_sha256": sha256,
            "lastscan": scan_time,
            "invalidated": True,
        }
        entry, created = fs_Cache_Tracking.objects.update_or_create(
            directory_sha256=sha256,
            defaults=defaults,
            create_defaults=defaults,
        )
        # entry.save()

        # Clear layout cache if needed
        if directory_found:
            layout = layout_manager(directory=directory, sort_ordering=0)
            for page_number in range(1, layout["total_pages"] + 1):
                key = hashkey(
                    page_number=page_number, directory=directory, sort_ordering=0
                )
                if key in layout_manager_cache:
                    del layout_manager_cache[key]

        return True
        # except Exception as e:
        #     # Log the exception
        #     # logger.error(f"Error removing from cache: {e}")
        #     return False

    def remove_from_cache_name(self, DirName):
        sha256 = get_dir_sha(DirName)
        return self.remove_from_cache_sha(sha256)

    def remove_multiple_from_cache(self, dir_names):
        """
        Remove multiple directories from cache in a single transaction
        """
        if not dir_names:
            return False

        try:
            from frontend.views import layout_manager, layout_manager_cache
            from quickbbs.models import IndexDirs

            close_old_connections()
            updates = False
            print("Removal multiple", dir_names)
            # Convert all directory names to SHA256 hashes
            sha_list = set([get_dir_sha(dir_name) for dir_name in dir_names])
            directories = list(IndexDirs.objects.filter(dir_fqpn_sha256__in=sha_list))
            # updated_cnt = IndexDirs.objects.filter(dir_fqpn_sha256__in=sha_list).update(
            #    is_generic_icon=False
            # )

            fqpn_by_dir_sha = {
                d.dir_fqpn_sha256: d for d in directories
            }  # sha + fqpndirectory

            with transaction.atomic():
                # Get all affected directories before deletion
                # Delete the cache entries
                update_cache_entries = fs_Cache_Tracking.objects.filter(
                    directory_sha256__in=sha_list, invalidated=False
                )
                updates = update_cache_entries.exists()
                if updates:
                    update_cache_entries.update(invalidated=True)
            # Clear all affected layout caches

            if updates:
                for sha in sha_list:
                    if sha in fqpn_by_dir_sha:
                        directory = fqpn_by_dir_sha[sha]
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
            # Log the exception if needed
            # logger.error(f"Error in remove_multiple_from_cache: {e}")
            return False
        finally:
            close_old_connections()

        return updates == True


# Initialize watchdog with the optimized event handler
watchdog.startup(
    monitor_path=os.path.join(settings.ALBUMS_PATH, "albums"),
    event_handler=CacheFileMonitorEventHandler(),
)
