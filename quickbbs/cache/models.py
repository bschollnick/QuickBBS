import os
import sys
import time

from django.conf import settings
from django.db import models
from filetypes.models import FILETYPE_DATA

# from cache.cached_exists import cached_exist
#from frontend.config import configdata
from cache.watchdogmon import watchdog

# CACHE = cached_exist(use_modify=True, use_extended=True, FilesOnly=False,
#                      use_filtering=True)
# CACHE.IgnoreDotFiles = True
# CACHE.FilesOnly = False
#
# try:
#     # print("Acceptable extensions", list(FILETYPE_DATA.keys()))
#     CACHE.AcceptableExtensions = list(FILETYPE_DATA.keys())
# except AttributeError:
#     pass
# CACHE.AcceptableExtensions.append("")


def delete_from_cache_tracking(event):
    # global CACHE
    if event.is_directory:
        dirpath = os.path.normpath(event.src_path.title().strip())
        # CACHE.clear_path(path_to_clear=dirpath)
        if fs_Cache_Tracking.objects.filter(DirName=dirpath).exists():
            fs_Cache_Tracking.objects.filter(DirName=dirpath).delete()
            print("\n", time.ctime(), " Deleted %s" % dirpath, "\n")
#        else:
#            print("Does not exist in Cache Tracking %s" % dirpath)

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
