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
from cachetools.keys import hashkey
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
        Cache_Storage.remove_from_cache_name(dirpath)


@lru_cache(maxsize=1000)
def get_dir_sha(fqpn_directory) -> str:
    """
    Return the SHA256 hash of the file as a hexdigest string

    Args:
        fqfn (str) : The fully qualified filename of the file to be hashed

    Returns: The SHA256 hash of the file + fqfn as a hexdigest string
    """
    # sha = None
    # digest = hashlib.sha256()
    # digest.update(normalize_fqpn(fqpn_directory).encode("utf-8"))
    # sha = digest.hexdigest()
    # return sha
    fqpn_directory = normalize_fqpn(fqpn_directory)
    return hashlib.sha256(fqpn_directory.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1000)
def normalize_fqpn(fqpn_directory) -> str:
    """
    Normalize the directory structure fully qualified pathname for conversion to a md5
    hexdigest string.
        fqpn_directory: String, the fully qualified pathname for the directory
    Returns: normalized string, all lowercase, whitespace stripped, ending with os.sep
    """
    Path = pathlib.Path(fqpn_directory)
    fqpn_directory = str(Path.resolve()).lower().strip()
    if not fqpn_directory.endswith(os.sep):
        fqpn_directory = fqpn_directory + os.sep
    return fqpn_directory


class fs_Cache_Tracking(models.Model):
    """
    Cache_Storage table is used to signify that a directory has been scanned and is up to date.  After a rescan, the
    directory is added to the Cache_Storage table.

    The lastscan time is technically not used for aging out the cache, it is there to allow for debugging and to
    generate a human readable time of the last scan (In the admin console).

    """

    directory_sha256 = models.CharField(db_index=True, blank=True, unique=True, null=True, default=None)
    DirName = models.CharField(db_index=False, max_length=384, default="", blank=True)
    # the path from watchdog, titlecased, stripped, and normpathed
    # dirpath = os.path.normpath(event.src_path.title().strip())
    lastscan = models.FloatField()  # Stored as Unix TimeStamp (ms)

    @staticmethod
    def clear_all_records():
        from frontend.views import layout_manager

        fs_Cache_Tracking.objects.all().delete()
        # layout_manager.cache_clear()

    def add_to_cache(self, DirName):
        entry = fs_Cache_Tracking()
        entry.DirName = normalize_fqpn(DirName)  # .title().strip()
        entry.directory_sha256 = get_dir_sha(entry.DirName)
        if not self.sha_exists_in_cache(entry.directory_sha256):
            entry.lastscan = time.time()
            entry.save()

    def sha_exists_in_cache(self, sha256):
        return fs_Cache_Tracking.objects.filter(directory_sha256=sha256).exists()

    def remove_from_cache_sha(self, sha256):
        from frontend.views import layout_manager, layout_manager_cache

        from quickbbs.models import IndexDirs

        try:
            items_removed, _ = fs_Cache_Tracking.objects.get(directory_sha256=sha256).delete()
        except fs_Cache_Tracking.DoesNotExist:
            items_removed = 0

        if items_removed != 0:
            directory = IndexDirs.objects.get(dir_sha256=sha256)
            layout = layout_manager(directory=directory, sort_ordering=0)
            for page_number in range(1, layout["total_pages"] + 1):
                key = hashkey(page_number=page_number, directory=directory, sort_ordering=0)
                if key in layout_manager_cache:
                    del layout_manager_cache[key]
                else:
                    print("Key not found in cache")
        return items_removed != 0

    def remove_from_cache_name(self, DirName):
        sha256 = get_dir_sha(DirName)
        return self.remove_from_cache_sha(sha256)


watchdog.startup(
    monitor_path=os.path.join(settings.ALBUMS_PATH, "albums"),
    event_handler=CacheFileMonitorEventHandler(),
)
