import atexit
import fcntl
import logging
import os
import sys

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

        # Determine whether this process should start the watchdog.
        #
        # Three execution contexts to handle:
        #
        # 1. Management commands (scan, taskrunner, migrate, shell, etc.)
        #    argv[0] ends with manage.py and argv[1] is not a web server command.
        #    → Skip watchdog entirely.
        #
        # 2. Dev servers (runserver / runserver_plus via manage.py)
        #    The auto-reloader spawns a parent (monitor) and a child (actual server).
        #    Django sets RUN_MAIN=true / Werkzeug sets WERKZEUG_RUN_MAIN=true only
        #    in the child. We want the watchdog only in the child — one instance, no lock.
        #    MCP servers (django-ai-boost, etc.) also run Django but set neither env var,
        #    so they fall through to "skip" here.
        #    → Start only when RUN_MAIN or WERKZEUG_RUN_MAIN is "true".
        #
        # 3. Production servers (gunicorn/hypercorn/uvicorn)
        #    These never invoke manage.py; argv[0] is the server binary.
        #    Multiple workers each call ready() — use a file lock so only one starts
        #    the watchdog.
        #    → Use file lock, start in the winner.

        is_manage_py = sys.argv[0].endswith("manage.py") and len(sys.argv) > 1
        is_dev_server_cmd = is_manage_py and sys.argv[1] in ("runserver", "runserver_plus")
        is_other_management_cmd = is_manage_py and not is_dev_server_cmd

        if is_other_management_cmd:
            # scan, taskrunner, migrate, shell, etc. — no watchdog needed
            logger.debug("Skipping watchdog startup for management command: %s", sys.argv[1])
            return

        if is_dev_server_cmd:
            # Only the reloader child has RUN_MAIN/WERKZEUG_RUN_MAIN set to "true"
            run_main = os.environ.get("WERKZEUG_RUN_MAIN") or os.environ.get("RUN_MAIN")
            if run_main != "true":
                # Parent monitor process or MCP server — skip
                logger.debug("Skipping watchdog startup (not the reloader child process)")
                return
            try:
                cache_watcher.models.watchdog_manager.start()
                logger.info("Watchdog filesystem monitor started (PID %s, dev server)", os.getpid())
            except (RuntimeError, OSError) as e:
                logger.error("Failed to start watchdog manager: %s", e, exc_info=True)
            return

        # Production server path (gunicorn/hypercorn/uvicorn) — use file lock to
        # ensure only one worker starts the watchdog across multiple processes.
        should_start = False
        lock_file_path = "/tmp/quickbbs_watchdog.lock"

        # Remove stale lock files — if the previous process was killed without
        # running atexit cleanup, the file remains but holds no fcntl lock.
        # Check if the PID recorded in the file is still alive; if not, it's stale.
        try:
            with open(lock_file_path) as lf:
                pid = int(lf.read().strip())
            try:
                os.kill(pid, 0)  # Signal 0 = existence check only, no actual signal
            except (ProcessLookupError, PermissionError):
                # ProcessLookupError: PID is gone — stale lock
                # PermissionError: PID exists but owned by another user — treat as live
                os.remove(lock_file_path)
                logger.info("Removed stale watchdog lock file (PID %s no longer running)", pid)
        except (FileNotFoundError, ValueError):
            pass  # No lock file or unreadable — normal first-start path

        try:
            lock_fd = open(lock_file_path, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            should_start = True
            self._watchdog_lock_fd = lock_fd
            lock_fd.write(f"{os.getpid()}\n")
            lock_fd.flush()
            atexit.register(self._cleanup_lock, lock_fd, lock_file_path)
            logger.info("Acquired watchdog lock (PID %s) - production server worker", os.getpid())
        except (IOError, OSError, BlockingIOError) as e:
            logger.warning("Failed to acquire lock file: %s", e)
            try:
                lock_fd.close()
            except (IOError, OSError, AttributeError) as close_error:
                logger.debug("Failed to close lock file: %s", close_error)
            logger.info("Watchdog already running in another worker (PID %s) - skipping", os.getpid())

        if should_start:
            try:
                cache_watcher.models.watchdog_manager.start()
                logger.info("Watchdog filesystem monitor started (PID %s, production)", os.getpid())
            except (RuntimeError, OSError) as e:
                logger.error("Failed to start watchdog manager: %s", e, exc_info=True)

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
        except (OSError, AttributeError) as e:
            logger.error("Error cleaning up watchdog lock: %s", e)
