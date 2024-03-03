import hashlib
import os
import pathlib
import sys
import time

from django.apps import AppConfig
from django.conf import settings
from django.core.cache import cache
from django.db import models

# from cache.cached_exists import cached_exist
# from frontend.config import configdata
from cache_watcher.watchdogmon import watchdog


Cache_Storage = None


def delete_from_cache_tracking(event):
    if event.is_directory:
        dirpath = os.path.normpath(event.src_path)
    else:
        dirpath = str(pathlib.Path(os.path.normpath(event.src_path)).parent)
    dhash = create_hash(dirpath)
    test = Cache_Storage.remove_from_cache_hdigest(dhash)
    print(dirpath, test)
    # if Cache_Storage.remove_from_cache_name(dirpath):
    # print(f"{time.ctime()} Deleted {dirpath}\n")


def create_hash(text):
    if not text.endswith(os.sep):
        text = f"{text}{os.sep}"
        print("Fixed name")
    return hashlib.md5(text.title().strip().encode("utf-16")).hexdigest()


class fs_Cache_Tracking(models.Model):
    Dir_md5_hdigest = models.CharField(db_index=True, max_length=32, default="", blank=True, unique=True)
    DirName = models.CharField(db_index=False, max_length=384, default="", blank=True)
    # the path from watchdog, titlecased, stripped, and normpathed
    # dirpath = os.path.normpath(event.src_path.title().strip())
    lastscan = models.FloatField()  # Stored as Unix TimeStamp (ms)

    @staticmethod
    def clear_all_records():
        fs_Cache_Tracking.objects.all().delete()

    def add_to_cache(self, DirName):
        entry = fs_Cache_Tracking()
        entry.DirName = DirName.title().strip()
        if not entry.DirName.endswith(os.sep):
            entry.DirName = f"{entry.DirName}{os.sep}"
        print("Adding to cache ", entry.DirName)
        entry.Dir_md5_hdigest = create_hash(entry.DirName)
        entry.lastscan = time.time()
        entry.save()

    def hdigest_exists_in_cache(self, hdigest):
        return fs_Cache_Tracking.objects.filter(Dir_md5_hdigest=hdigest).exists()

    def name_exists_in_cache(self, DirName):
        Dir_md5_hdigest = create_hash(DirName)
        return self.hdigest_exists_in_cache(hdigest=Dir_md5_hdigest)

    def remove_from_cache_hdigest(self, hdigest):
        items_removed, _ = fs_Cache_Tracking.objects.filter(Dir_md5_hdigest=hdigest).delete()
        return items_removed != 0

    def remove_from_cache_name(self, DirName):
        Dir_md5_hdigest = create_hash(DirName)
        return self.remove_from_cache_hdigest(Dir_md5_hdigest)


if "runserver" in sys.argv or "--host" in sys.argv:
    print("Starting Watchdog - ", os.path.join(settings.ALBUMS_PATH, "albums"))
    watchdog.startup(
        monitor_path=os.path.join(settings.ALBUMS_PATH, "albums"),
        created=delete_from_cache_tracking,
        deleted=delete_from_cache_tracking,
        modified=delete_from_cache_tracking,
        moved=delete_from_cache_tracking,
    )
