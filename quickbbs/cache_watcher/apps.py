import os

from django.apps import AppConfig
from django.conf import settings
from django.db.utils import IntegrityError, OperationalError, ProgrammingError

# cold_start = False


class cache_startup(AppConfig):
    name = "cache_watcher"
    label = "CacheWatcher"

    def ready(self):
        import cache_watcher.models

        print("!! Starting Cache Storage")
        cache_watcher.models.Cache_Storage = cache_watcher.models.fs_Cache_Tracking()
        print("Cache Storage Established")
