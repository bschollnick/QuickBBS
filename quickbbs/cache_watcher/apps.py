import logging
import os

from django.apps import AppConfig
from django.conf import settings
from django.db.utils import IntegrityError, OperationalError, ProgrammingError

logger = logging.getLogger()
# logger.info("in apps.py in cache_watcher")


class cache_startup(AppConfig):
    """Django AppConfig for cache_watcher application.

    Initializes the cache watcher system and starts the watchdog file monitoring
    when the application is ready.
    """

    name = "cache_watcher"
    label = "CacheWatcher"

    def ready(self) -> None:
        """
        Initialize cache watcher when Django app is ready.

        Sets up the Cache_Storage singleton and starts the watchdog manager for
        filesystem monitoring.

        :return: None
        """
        import cache_watcher.models

        cache_watcher.models.Cache_Storage = cache_watcher.models.fs_Cache_Tracking()

        try:
            cache_watcher.models.watchdog_manager.start()
        except Exception as e:
            logger.error(f"Failed to start watchdog manager: {e}")
