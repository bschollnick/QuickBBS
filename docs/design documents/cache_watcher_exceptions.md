# cache_watcher — Exception Taxonomy

**Date Created:** 2026-08-07  
**Last Updated:** 2026-09-25  
**Last Reviewed:** 2026-09-25

**Companion to:** [`cache_watcher_design.md`](cache_watcher_design.md)
**Author:** Benjamin Schollnick

---

## What this is

`cache_watcher` defines no custom exception classes. This document lists every
standard exception it catches or raises on purpose, in `cache_watcher/apps.py`,
`cache_watcher/models.py` and `cache_watcher/watchdogmon.py`. The catches fall into
three groups: electing the one worker process that runs the watchdog, broad catches
around the third-party `watchdog` library (which documents no exception types), and
database errors while applying buffered filesystem events. `admin.py` and the
`clear_cache` management command catch nothing.

---

## Startup: electing one worker to run the watchdog

[`CacheWatcherConfig.ready()`](cache_watcher_design.md#ready) and the helpers it calls
in `apps.py` make sure exactly one worker process starts the watchdog in a
multi-worker production deployment:

- **Stale-lock detection** (`_remove_stale_lock()`) — reads the PID recorded in
  `/tmp/quickbbs_watchdog.lock` and signals it with `os.kill(pid, 0)` to check liveness.
  `ProcessLookupError` means the PID is gone, so the lock is stale: the file is
  removed and the removal is logged at INFO. `PermissionError` means the PID exists
  but is owned by another user, so it is treated as still running and the file is
  kept. `(FileNotFoundError, ValueError)` around reading and parsing the file — no
  file, or no PID in it — is the normal first-start case and returns without action.
- **Lock acquisition** (`_acquire_watchdog_lock()`) — catches `OSError` (which
  includes `BlockingIOError`) around opening the lock file and
  `fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`. Failing to acquire the lock
  means another worker already holds it, so this worker logs a WARNING, closes the
  file, logs an INFO that the watchdog is running elsewhere, and does not start its
  own watchdog.
- **Watchdog start itself** — both the dev-server path and the production-worker path
  call `watchdog_manager.start()` inside one `except (RuntimeError, OSError)` in
  `ready()`, which logs at ERROR with a traceback and continues; the application
  still boots when the watchdog fails to start. Any other exception type from
  `start()` propagates out of `ready()`.
- **[`_cleanup_lock`](cache_watcher_design.md#41-appspy)** (registered via `atexit`)
  catches `OSError` around releasing the flock and removing the lock file, and logs it
  at ERROR. `_logging_is_open()` skips that logging, and the INFO on success, when the
  interpreter is finalizing or a stdout, stderr or handler stream is already closed.

## Broad catches around the `watchdog` library

Six sites in [`WatchdogManager`](cache_watcher_design.md#44-modelspy),
[`CacheFileMonitorEventHandler`](cache_watcher_design.md#45-modelspy) and
[`WatchdogMonitor`](cache_watcher_design.md#42-watchdogmonpy) catch `Exception`, each
with a comment giving the reason:

- **`WatchdogManager.start(force_recreate)`** — catches around `watchdog.startup()` and
  scheduling the restart timer, logs at ERROR with a traceback, and **re-raises** (bare
  `raise`). This is the one site in the group where the caller still sees the failure.
- **`WatchdogManager.stop()`** and **`WatchdogManager.shutdown()`** — catch around
  cleaning up the event handler and calling `watchdog.stop_observer()` /
  `watchdog.shutdown()`, log at ERROR without a traceback, and swallow the exception
  (`SystemExit` from `watchdog.shutdown()` is not an `Exception`; see below).
  `is_running` stays `True` when the stop failed.
- **`WatchdogManager.restart()`** — wraps the whole stop, flush pending events, clear
  buffer, start sequence, and logs at ERROR with a traceback. After a failure it logs
  a WARNING and schedules the next restart attempt, so the cycle continues. Until that
  attempt runs, `WATCHDOG_RESTART_INTERVAL` later, the watchdog may be stopped and
  filesystem changes go unnoticed.
- **`WatchdogManager._schedule_restart()`** — catches around cancelling the old
  `threading.Timer` and creating and starting the new one, logs at ERROR with a
  traceback, and swallows the exception. A timer that starts but is not alive is
  logged at ERROR without raising.
- **[`CacheFileMonitorEventHandler._buffer_event(event)`](cache_watcher_design.md#_buffer_eventevent)**
  — catches around buffering one filesystem event and starting the processing timer,
  logs the `event.src_path` that failed at ERROR without a traceback, and continues.
  It runs on the `watchdog` observer thread, where an escaping exception would stop
  event delivery.
- **[`WatchdogMonitor.stop_observer()`](cache_watcher_design.md#stop_observer)**
  — catches around unscheduling the watch and `Observer.stop()` / `.join()`, logs at
  ERROR with a traceback, and still clears the observer, event-handler and watch
  references, so a failed stop does not leave a stale reference blocking a future
  restart.

**`WatchdogMonitor.shutdown()` raises `SystemExit` on purpose.** It calls
`sys.exit(0)`, after stopping the observer when `RUN_MAIN` is `"true"`;
`cache_watcher/__init__.py` installs it as the `SIGINT` handler, so Control-C ends the
process. `WatchdogManager.stop()` calls `watchdog.stop_observer()` instead, so a
restart does not exit. `WatchdogManager.shutdown()` does call `watchdog.shutdown()`:
the `SystemExit` passes through its `except Exception` and ends the process. Only the
tests call `WatchdogManager.shutdown()`.

## Database errors during event processing

Both `WatchdogManager._process_pending_events()` (called during `restart()` to avoid
losing buffered events) and
[`CacheFileMonitorEventHandler._process_buffered_events(expected_generation)`](cache_watcher_design.md#_process_buffered_eventsexpected_generation)
(the timer-fired handler) pass the buffered paths to `_apply_directory_changes()`,
which invalidates their
[`DirectoryIndex`](quickbbs_app_design.md#42-directoryindexpy) rows and adds rows
for new directories. Both catch the same tuple, `(RuntimeError, DatabaseError,
OSError, AttributeError)`, log at ERROR without a traceback, and continue. A `finally`
block releases the processing semaphore, so a failed batch neither leaves it held nor
blocks the next processing run, and calls `close_old_connections()`, since both run on
background threads. `_process_buffered_events` also clears its timer reference there.
`DatabaseError` is Django's `django.db.utils.DatabaseError`; `quickbbs` defines no
exception types of its own (see [`quickbbs_exceptions.md`](quickbbs_exceptions.md)).
