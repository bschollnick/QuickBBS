import os
import sys
import time

from django.core.cache import cache
from django.conf import settings
from django.db import models
from filetypes.models import FILETYPE_DATA

# from cache.cached_exists import cached_exist
# from frontend.config import configdata
from cache.watchdogmon import watchdog


def delete_from_cache_tracking(event):
    if event.is_directory:
        dirpath = os.path.normpath(event.src_path.title().strip())
        # if fs_Cache_Tracking.objects.filter(DirName=dirpath).exists():
        fs_Cache_Tracking.objects.filter(DirName=dirpath).delete()
        print(f"{time.ctime()} Deleted {dirpath}\n")
        cache.clear()

class fs_Cache_Tracking(models.Model):
    DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)
    # the path from watchdog, titlecased, stripped, and normpathed
    # dirpath = os.path.normpath(event.src_path.title().strip())
    lastscan = models.FloatField()  # Stored as Unix TimeStamp (ms)


if 'runserver' in sys.argv or "--host" in sys.argv:
    print("Starting Watchdog - ", os.path.join(settings.ALBUMS_PATH, "albums"))
    watchdog.startup(monitor_path=os.path.join(settings.ALBUMS_PATH,
                                               "albums"),
                     created=delete_from_cache_tracking,
                     deleted=delete_from_cache_tracking,
                     modified=delete_from_cache_tracking,
                     moved=delete_from_cache_tracking)
