import hashlib
import os
import pathlib
import sys
import time

from django.apps import AppConfig
from django.conf import settings
from django.core.cache import cache
from django.db import models

from watchdog.events import FileSystemEventHandler  # , PatternMatchingEventHandler
from cache_watcher.watchdogmon import watchdog


Cache_Storage = None


class CacheFileMonitorEventHandler(FileSystemEventHandler):
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
        test = Cache_Storage.remove_from_cache_hdigest(dhash)


def create_hash(text):
    if not text.endswith(os.sep):
        text = f"{text}{os.sep}"
    return hashlib.md5(text.title().strip().encode("utf-16")).hexdigest()


class fs_Cache_Tracking(models.Model):
    Dir_md5_hdigest = models.CharField(
        db_index=True, max_length=32, default="", blank=True, unique=True
    )
    DirName = models.CharField(db_index=False, max_length=384, default="", blank=True)
    # the path from watchdog, titlecased, stripped, and normpathed
    # dirpath = os.path.normpath(event.src_path.title().strip())
    lastscan = models.FloatField()  # Stored as Unix TimeStamp (ms)

    @staticmethod
    def clear_all_records():
        #        logger.info("Clearing all cache entries")
        fs_Cache_Tracking.objects.all().delete()

    def add_to_cache(self, DirName):
        entry = fs_Cache_Tracking()
        entry.DirName = DirName.title().strip()
        if not entry.DirName.endswith(os.sep):
            entry.DirName = f"{entry.DirName}{os.sep}"
        #       logger.info(f"Adding to cache {entry.DirName}")
        entry.Dir_md5_hdigest = create_hash(entry.DirName)
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


# if "runserver" in sys.argv or "--host" in sys.argv:
# logger.info("Starting Watchdog - " + os.path.join(settings.ALBUMS_PATH, "albums"))
watchdog.startup(
    monitor_path=os.path.join(settings.ALBUMS_PATH, "albums"),
    event_handler=CacheFileMonitorEventHandler(),
)
