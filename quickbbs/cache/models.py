import hashlib
import os
import sys
import time

from django.conf import settings
from django.core.cache import cache
from django.db import models

# from cache.cached_exists import cached_exist
# from frontend.config import configdata
from cache.watchdogmon import watchdog


def delete_from_cache_tracking(event):
    if event.is_directory:
        dirpath = os.path.normpath(event.src_path)
        dhash = create_hash(dirpath)
        if Cache_Storage.remove_from_cache_hdigest(dhash):
            print(f"{time.ctime()} Deleted {dirpath}\n")
    # print(cache.keys()[:5])


#        count, _ = fs_Cache_Tracking.objects.filter(DirName=dirpath).delete()
#        if count:
#            print(f"{time.ctime()} Deleted {dirpath}\n")
#        cache.clear()


def create_hash(text):
    # return hashlib.md5(text.title().strip().encode("utf-8")).hexdigest()
    return hashlib.md5(text.title().strip().encode("utf-16")).hexdigest()


class fs_Cache_Tracking(models.Model):
    Dir_md5_hdigest = models.CharField(
        db_index=True, max_length=32, default="", blank=True, unique=True
    )
    DirName = models.CharField(db_index=False, max_length=384, default="", blank=True)
    # the path from watchdog, titlecased, stripped, and normpathed
    # dirpath = os.path.normpath(event.src_path.title().strip())
    lastscan = models.FloatField()  # Stored as Unix TimeStamp (ms)

    def clear_all_records(self):
        fs_Cache_Tracking.objects.all().delete()

    def add_to_cache(self, DirName):
        entry = fs_Cache_Tracking()
        entry.DirName = DirName.title().strip()
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
        return items_removed is True

    def remove_from_cache_name(self, DirName):
        items_removed, _ = fs_Cache_tracking.objects.filter(
            DirName=DirName.title()
        ).delete()
        return items_removed is True


Cache_Storage = fs_Cache_Tracking()

if "runserver" in sys.argv or "--host" in sys.argv:
    print("Starting Watchdog - ", os.path.join(settings.ALBUMS_PATH, "albums"))
    watchdog.startup(
        monitor_path=os.path.join(settings.ALBUMS_PATH, "albums"),
        created=delete_from_cache_tracking,
        deleted=delete_from_cache_tracking,
        modified=delete_from_cache_tracking,
        moved=delete_from_cache_tracking,
    )
