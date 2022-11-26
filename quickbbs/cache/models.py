from django.db import models
import sys
import os
from frontend.config import configdata
from cache.watchdogmon import watchdog

def delete_from_cache_tracking(event):
    global CACHE
    if event.is_directory:
        dirpath = os.path.normpath(event.src_path.title().strip())
        CACHE.clear_path(path_to_clear=dirpath)
        if Cache_Tracking.objects.filter(DirName=dirpath).exists():
            Cache_Tracking.objects.filter(DirName=dirpath).delete()
            print("\n\n", time.ctime(), " Deleted %s" % dirpath, "\n\n")
#        else:
#            print("Does not exist in Cache Tracking %s" % dirpath)

class fs_Cache_Tracking(models.Model):
    DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)   # FQFN of the file itself
    lastscan = models.FloatField()   # Stored as Unix TimeStamp (ms)


if 'runserver' in sys.argv or "--host" in sys.argv:
    print("Starting Watchdog - ",os.path.join(configdata["locations"]["albums_path"], "albums"))
    watchdog.startup(monitor_path=os.path.join(configdata["locations"]["albums_path"],
                                               "albums"),
                                               created=delete_from_cache_tracking,
                                               deleted=delete_from_cache_tracking,
                                               modified=delete_from_cache_tracking,
                                               moved=delete_from_cache_tracking)

