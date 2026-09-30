"""Django AppConfig for cache_watcher: single-instance watchdog startup logic."""

from __future__ import annotations

import atexit
import fcntl
import logging
import os
import sys
from typing import TextIO

from django.apps import AppConfig

from quickbbs.server_role import server_role

logger = logging.getLogger(__name__)

WATCHDOG_LOCK_PATH = "/tmp/quickbbs_watchdog.lock"


class CacheWatcherConfig(AppConfig):
    """Django AppConfig for cache_watcher: starts the watchdog in one process per server."""

    name = "cache_watcher"
    label = "CacheWatcher"
    _watchdog_lock_fd: TextIO | None = None

    def ready(self) -> None:
        """Start the watchdog manager if this process should own it.

        Management commands and a dev server's reloader parent skip it. A dev
        server's reloader child starts it directly. Production workers
        (gunicorn/uvicorn/hypercorn) each call `ready()`, so only the worker
        that wins the `fcntl` lock on `WATCHDOG_LOCK_PATH` starts it.
        """
        # Deferred import: models cannot be imported at module level of apps.py
        # (the app registry is not ready yet); the watchdog_manager singleton
        # lives in cache_watcher.models.
        import cache_watcher.models  # pylint: disable=import-outside-toplevel

        role = server_role()
        if role == "not_a_server":
            logger.debug("Skipping watchdog startup: %s is not a serving process", sys.argv[1:2] or sys.argv[0])
            return
        if role == "production_server" and not self._acquire_watchdog_lock():
            return

        try:
            cache_watcher.models.watchdog_manager.start()
            logger.info("Watchdog filesystem monitor started (PID %s, %s)", os.getpid(), role)
        except (RuntimeError, OSError) as e:
            logger.error("Failed to start watchdog manager: %s", e, exc_info=True)

    def _acquire_watchdog_lock(self) -> bool:
        """Take the cross-worker watchdog lock; return True if this worker won it."""
        _remove_stale_lock(WATCHDOG_LOCK_PATH)
        lock_fd = None
        try:
            # Held open for the life of the process; _cleanup_lock closes it at exit.
            lock_fd = open(WATCHDOG_LOCK_PATH, "w", encoding="utf-8")  # pylint: disable=consider-using-with
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            logger.warning("Failed to acquire lock file: %s", e)
            if lock_fd is not None:
                lock_fd.close()
            logger.info("Watchdog already running in another worker (PID %s) - skipping", os.getpid())
            return False

        self._watchdog_lock_fd = lock_fd
        lock_fd.write(f"{os.getpid()}\n")
        lock_fd.flush()
        atexit.register(self._cleanup_lock, lock_fd, WATCHDOG_LOCK_PATH)
        logger.info("Acquired watchdog lock (PID %s) - production server worker", os.getpid())
        return True

    @staticmethod
    def _cleanup_lock(lock_fd: TextIO, lock_file_path: str) -> None:
        """Release and remove the watchdog lock file at process exit."""
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            if os.path.exists(lock_file_path):
                os.remove(lock_file_path)
            if _logging_is_open():
                logger.info("Watchdog lock cleaned up")
        except OSError as e:
            if _logging_is_open():
                logger.error("Error cleaning up watchdog lock: %s", e)


def _remove_stale_lock(lock_file_path: str) -> None:
    """Delete the lock file if the PID recorded in it is no longer running.

    A process killed without running its atexit cleanup leaves the file behind
    holding no `fcntl` lock. A PID owned by another user (PermissionError) is
    treated as live.
    """
    try:
        with open(lock_file_path, encoding="utf-8") as lock_file:
            pid = int(lock_file.read().strip())
    except (FileNotFoundError, ValueError):
        return  # No lock file, or no PID in it: the normal first-start case.
    try:
        os.kill(pid, 0)  # Signal 0 checks existence only.
    except ProcessLookupError:
        os.remove(lock_file_path)
        logger.info("Removed stale watchdog lock file (PID %s no longer running)", pid)
    except PermissionError:
        pass


def _logging_is_open() -> bool:
    """Return True unless the interpreter is finalizing or a logging stream is already closed."""
    if sys.is_finalizing() or getattr(sys.stdout, "closed", False) or getattr(sys.stderr, "closed", False):
        return False
    handlers = [*logger.handlers, *logging.getLogger().handlers]
    return not any(getattr(getattr(handler, "stream", None), "closed", False) for handler in handlers)
