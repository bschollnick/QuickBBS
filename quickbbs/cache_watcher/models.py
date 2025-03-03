"""
Models for the Cache Watchers for QuickBBS, this is a simple cache watcher that will monitor the directories and files
in the albums directory and all subdirectories for changes.  When a change is detected, the directory will be removed 
from the Cache_Storage table, which will cause it to be rescanned if that directory is accessed.

The Cache_Storage table is used to signify that a directory has been scanned and is up to date.  If the directory is
changed, the watchdog will detect the changes, and remove the directory from the Cache_Storage table.

Thus when accessed, QuickBBS will see it is not up-to-date (since it is not in the Cache_Storage table) and will rescan
the directory, and re-add it to the Cache_Storage table.
"""

import hashlib
import os
import pathlib
import sys
import time
from functools import lru_cache

from cache_watcher.watchdogmon import watchdog
from django.apps import AppConfig
from django.conf import settings
from django.core.cache import cache
from django.db import models
from watchdog.events import FileSystemEventHandler  # , PatternMatchingEventHandler

Cache_Storage = None


class CacheFileMonitorEventHandler(FileSystemEventHandler):
    """
    Event Handler for the Watchdog Monitor for QuickBBS, on any on_created, on_deleted, on_modified, on_any_event
    detections, the directory will be removed from the Cache_Storage table, which will cause it to be rescanned
    if that directory is accessed.

    """

    def on_created(self, event):
        self.on_any_event(event)

    def on_deleted(self, event):
        self.on_any_event(event)

    def on_modified(self, event):
        self.on_any_event(event)

    def on_moved(self, event):
        self.on_any_event(event)

    def on_any_event(self, event):
        if event.is_directory:
            dirpath = os.path.normpath(event.src_path)
        else:
            dirpath = str(pathlib.Path(os.path.normpath(event.src_path)).parent)
        dhash = create_hash(dirpath)
        Cache_Storage.remove_from_cache_hdigest(dhash)


@lru_cache(maxsize=500)
def create_hash(text):
    """
    Create a hash of the text, titlecased, stripped, and normpathed that"""
    if not text.endswith(os.sep):
        text = f"{text}{os.sep}"
    return hashlib.md5(text.title().strip().encode("utf-8")).hexdigest()


class fs_Cache_Tracking(models.Model):
    """
    Cache_Storage table is used to signify that a directory has been scanned and is up to date.  After a rescan, the
    directory is added to the Cache_Storage table.

    The lastscan time is technically not used for aging out the cache, it is there to allow for debugging and to
    generate a human readable time of the last scan (In the admin console).

    """

    Dir_md5_hdigest = models.CharField(
        db_index=True, max_length=32, default="", blank=True, unique=True
    )
    DirName = models.CharField(db_index=False, max_length=384, default="", blank=True)
    # the path from watchdog, titlecased, stripped, and normpathed
    # dirpath = os.path.normpath(event.src_path.title().strip())
    lastscan = models.FloatField()  # Stored as Unix TimeStamp (ms)

    @staticmethod
    def clear_all_records():
        fs_Cache_Tracking.objects.all().delete()

    def add_to_cache(self, DirName):
        entry = fs_Cache_Tracking()
        entry.DirName = DirName  # .title().strip()
        if not entry.DirName.endswith(os.sep):
            entry.DirName = f"{entry.DirName}{os.sep}"
        #       logger.info(f"Adding to cache {entry.DirName}")
        entry.Dir_md5_hdigest = create_hash(entry.DirName)
        if not self.hdigest_exists_in_cache(entry.Dir_md5_hdigest):
            entry.lastscan = time.time()
            entry.save()

    def hdigest_exists_in_cache(self, hdigest):
        return fs_Cache_Tracking.objects.filter(Dir_md5_hdigest=hdigest).exists()

    def name_exists_in_cache(self, DirName):
        Dir_md5_hdigest = create_hash(DirName)
        return self.hdigest_exists_in_cache(hdigest=Dir_md5_hdigest)

    def remove_from_cache_hdigest(self, hdigest):
        items_removed, _ = fs_Cache_Tracking.objects.filter(
            Dir_md5_hdigest=hdigest
        ).delete()
        return items_removed != 0

    def remove_from_cache_name(self, DirName):
        #        logger.info(f"Removing from cache {DirName}")
        Dir_md5_hdigest = create_hash(DirName)
        return self.remove_from_cache_hdigest(Dir_md5_hdigest)


watchdog.startup(
    monitor_path=os.path.join(settings.ALBUMS_PATH, "albums"),
    event_handler=CacheFileMonitorEventHandler(),
)
