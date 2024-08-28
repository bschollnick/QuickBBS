import logging
import os

from django.apps import AppConfig
from django.conf import settings
from django.db.utils import IntegrityError, OperationalError, ProgrammingError

logger = logging.getLogger()
# logger.info("in apps.py in cache_watcher")


class cache_startup(AppConfig):
    name = "cache_watcher"
    label = "CacheWatcher"

    def ready(self):
        import cache_watcher.models

        #        logger.info("!! Starting Cache Storage")
        cache_watcher.models.Cache_Storage = cache_watcher.models.fs_Cache_Tracking()


#        logger.info("Cache Storage Established")
