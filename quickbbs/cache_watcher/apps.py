import logging

from django.apps import AppConfig

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
        import os

        import cache_watcher.models

        cache_watcher.models.Cache_Storage = cache_watcher.models.fs_Cache_Tracking()

        # Only start watchdog in the actual running process, not the autoreloader parent
        # Django's autoreloader creates a parent process and a child process
        # WERKZEUG_RUN_MAIN is set by werkzeug (runserver_plus), RUN_MAIN by Django
        run_main = os.environ.get("WERKZEUG_RUN_MAIN") or os.environ.get("RUN_MAIN")

        if run_main == "true":
            try:
                cache_watcher.models.watchdog_manager.start()
            except Exception as e:
                logger.error(f"Failed to start watchdog manager: {e}")
