# cache_watcher — Exception Taxonomy

**Companion to:** [`cache_watcher_design.md`](cache_watcher_design.md)
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

---

## What this is

`cache_watcher` defines no custom exception classes. This document covers the
standard exceptions it catches as a deliberate part of its startup-coordination and
filesystem-event-handling design — the lock-file dance that elects one worker to run
the watchdog, and the broad catches around the third-party `watchdog` library's
undocumented exception surface. Verified directly against `cache_watcher/apps.py`,
`cache_watcher/models.py`, and `cache_watcher/watchdogmon.py`.

---

## Startup: electing one worker to run the watchdog

[`cache_startup.ready()`](cache_watcher_design.md#ready) (`apps.py:25–134`) runs
through several exception-handling steps to make sure exactly one worker process
starts the watchdog in a multi-worker production deployment:

- **Stale-lock detection** — reads the PID recorded in `/tmp/quickbbs_watchdog.lock`
  and signals it with `os.kill(pid, 0)` to check liveness. Catches
  `(ProcessLookupError, PermissionError)` (`apps.py:102`): `ProcessLookupError` means
  the PID is gone, so the lock is stale and gets removed; `PermissionError` means the
  PID exists but is owned by another user, so it's treated as still live. Catches
  `(FileNotFoundError, ValueError)` (`apps.py:107`) around reading/parsing the file
  itself — no file, or an unreadable one, is the normal first-start case and is
  silently passed over.
- **Lock acquisition** — catches `(IOError, OSError, BlockingIOError)`
  (`apps.py:120`) around `fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`: failing
  to acquire the lock means another worker already holds it, so this worker logs and
  skips starting its own watchdog. Nested inside that handler, closing the now-useless
  file descriptor is itself wrapped in `(IOError, OSError, AttributeError)`
  (`apps.py:125`), logged at DEBUG rather than WARNING/ERROR — a failure to close an
  already-unusable handle isn't worth escalating.
- **Watchdog start itself** — both the dev-server path and the production-worker path
  call `watchdog_manager.start()` inside `except (RuntimeError, OSError)`
  (`apps.py:85, 133`), logging and continuing either way; the app still boots even if
  the watchdog fails to start.
- **[`_cleanup_lock`](cache_watcher_design.md#44-modelspy--watchdogmanager)**
  (`apps.py:137–158`, registered via `atexit`) catches `(OSError, AttributeError)`
  (`apps.py:154`) around releasing the flock and removing the lock file, guarding its
  own logging against a closed stdout/stderr stream during interpreter shutdown.

## Broad catches around the `watchdog` library's undocumented exception surface

Several sites in
[`WatchdogManager`](cache_watcher_design.md#44-modelspy--watchdogmanager) and
[`WatchdogMonitor`](cache_watcher_design.md#42-watchdogmonpy--watchdogmonitor) use a
deliberately broad `except Exception`, each with a `TODO` comment naming what it would
narrow to once the underlying library's failure modes are catalogued:

- **`WatchdogManager.start(force_recreate)`** (`models.py:224`) — catches, logs, and
  **re-raises** (bare `raise`) after `watchdog.startup()` fails; this is the one site
  in the group where the caller still sees the failure, unlike the others below.
- **`WatchdogManager.stop()`** (`models.py:249`) and **`WatchdogManager.shutdown()`**
  (`models.py:271`) — both catch, log, and swallow around `watchdog.stop_observer()` /
  `watchdog.shutdown()`.
- **`WatchdogManager.restart()`** (`models.py:351`) — wraps the whole
  stop-then-start-again sequence; on failure, logs and falls through to manually
  reschedule the next restart attempt rather than leaving the watchdog un-monitored.
- **`WatchdogManager._schedule_restart()`** (`models.py:382`) — catches around
  creating and starting the `threading.Timer` itself.
- **[`CacheFileMonitorEventHandler._buffer_event(event)`](cache_watcher_design.md#_buffer_eventevent)**
  (`models.py:485`) — catches around buffering one filesystem event; logs the specific
  `event.src_path` that failed and continues.
- **[`WatchdogMonitor.stop_observer()`](cache_watcher_design.md#stop_observer)**
  (`watchdogmon.py:151`) — catches around `Observer.stop()`/`.join()`; still clears
  the observer/event-handler references even when the stop itself failed, so a failed
  stop doesn't leave a stale reference blocking a future restart.

## Database errors during event processing

Both `WatchdogManager._process_pending_events()` (`models.py:314`, called during
`restart()` to avoid losing buffered events) and
[`CacheFileMonitorEventHandler._process_buffered_events(expected_generation)`](cache_watcher_design.md#_process_buffered_eventsexpected_generation)
(`models.py:597`, the timer-fired handler that turns buffered filesystem paths into
[`DirectoryIndex`](quickbbs_app_design.md#42-directoryindexpy--directoryindex)
writes) catch the identical tuple, `(RuntimeError, DatabaseError, OSError,
AttributeError)`, log-and-continue, and use a `finally` block to release the
processing semaphore regardless of outcome — a failed batch of directory-cache
invalidations doesn't leave the semaphore held or block the next processing run.
`DatabaseError` here is Django's `django.db.utils.DatabaseError`; this app catches the
generic Django exception, not any exception type
[`quickbbs`](quickbbs_exceptions.md) defines, since `quickbbs` defines none of its own
(see [`quickbbs_exceptions.md`](quickbbs_exceptions.md)).
