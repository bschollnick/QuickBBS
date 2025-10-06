import atexit
import fcntl
import logging
import os

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class cache_startup(AppConfig):
    """Django AppConfig for cache_watcher application.

    Initializes the cache watcher system and starts the watchdog file monitoring
    when the application is ready.
    """

    name = "cache_watcher"
    label = "CacheWatcher"
    _watchdog_lock_fd = None

    def ready(self) -> None:
        """
        Initialize cache watcher when Django app is ready.

        Sets up the Cache_Storage singleton and starts the watchdog manager for
        filesystem monitoring.

        Handles multiple server environments:
        - Django runserver (dev): Uses RUN_MAIN env var
        - Werkzeug runserver_plus: Uses WERKZEUG_RUN_MAIN env var
        - Gunicorn/Uvicorn/Hypercorn: Uses file lock to ensure single startup

        :return: None
        """
        import cache_watcher.models

        cache_watcher.models.Cache_Storage = cache_watcher.models.fs_Cache_Tracking()

        # Determine if we should start the watchdog
        should_start = False

        # Check for Django/Werkzeug development servers
        run_main = os.environ.get("WERKZEUG_RUN_MAIN") or os.environ.get("RUN_MAIN")

        if run_main == "true":
            # Django development server or werkzeug - start in child process only
            should_start = True
            logger.info("Starting watchdog in Django/Werkzeug development server")
        else:
            # Production servers (Gunicorn/Uvicorn/Hypercorn) with multiple workers
            # Use file lock to ensure only ONE worker starts the watchdog
            lock_file_path = "/tmp/quickbbs_watchdog.lock"

            try:
                # Create/open lock file
                lock_fd = open(lock_file_path, "w")

                # Try to acquire exclusive, non-blocking lock
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Success! This is the first worker
                should_start = True
                self._watchdog_lock_fd = lock_fd

                # Write PID for debugging
                lock_fd.write(f"{os.getpid()}\n")
                lock_fd.flush()

                # Register cleanup on process exit
                atexit.register(self._cleanup_lock, lock_fd, lock_file_path)

                logger.info(f"Acquired watchdog lock (PID {os.getpid()}) - starting watchdog in this worker")

            except (IOError, OSError, BlockingIOError) as e:
                # Lock already held by another worker - don't start
                should_start = False
                if hasattr(lock_fd, "close"):
                    lock_fd.close()
                logger.info(f"Watchdog already running in another worker (PID {os.getpid()}) - skipping startup")

        # Start watchdog if this is the designated process
        if should_start:
            try:
                cache_watcher.models.watchdog_manager.start()
                logger.info("Watchdog filesystem monitor started successfully")
            except Exception as e:
                logger.error(f"Failed to start watchdog manager: {e}", exc_info=True)

    @staticmethod
    def _cleanup_lock(lock_fd, lock_file_path: str) -> None:
        """Clean up lock file on process exit.

        Args:
            lock_fd: File descriptor for the lock file
            lock_file_path: Path to the lock file
        """
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            if os.path.exists(lock_file_path):
                os.remove(lock_file_path)
            logger.info("Watchdog lock cleaned up")
        except Exception as e:
            logger.error(f"Error cleaning up watchdog lock: {e}")
