# cache_watcher — Design Document

**Version:** 3.99  
**Author:** Benjamin Schollnick  
**Last Updated:** 2026-04-11

---

## 1. Purpose

`cache_watcher` is a Django application that monitors the gallery filesystem for changes
and automatically invalidates directory-level cache entries so that QuickBBS always
serves up-to-date content without requiring manual rescans.

Its two responsibilities are:

1. **Filesystem observation** — detect when files or directories inside the Albums path
   are created, modified, moved, or deleted.
2. **Cache invalidation** — mark affected directories (and their ancestors) as
   `invalidated = True` in the database so the next page request triggers a fresh scan.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Django app startup  (apps.py – cache_startup.ready())   │
│  Sets up Cache_Storage singleton, starts WatchdogManager │
└──────────────────────┬───────────────────────────────────┘
                       │ starts
                       ▼
┌──────────────────────────────────────────────────────────┐
│  WatchdogManager  (models.py)                            │
│  • Holds reference to WatchdogMonitor (watchdogmon.py)   │
│  • Schedules periodic restarts (default: every 4 hours)  │
│  • Drains the event buffer before each restart           │
└──────────────────────┬───────────────────────────────────┘
                       │ schedules
                       ▼
┌──────────────────────────────────────────────────────────┐
│  WatchdogMonitor  (watchdogmon.py)                       │
│  • Thin wrapper around watchdog.observers.Observer       │
│  • Handles startup / stop / shutdown lifecycle           │
└──────────────────────┬───────────────────────────────────┘
                       │ delivers events to
                       ▼
┌──────────────────────────────────────────────────────────┐
│  CacheFileMonitorEventHandler  (models.py)               │
│  on_created / on_deleted / on_modified / on_moved        │
│  → _buffer_event()  →  LockFreeEventBuffer               │
│  → fires threading.Timer after EVENT_PROCESSING_DELAY    │
│  → _process_buffered_events()                            │
└──────────────────────┬───────────────────────────────────┘
                       │ invalidates
                       ▼
┌──────────────────────────────────────────────────────────┐
│  fs_Cache_Tracking  (models.py)                          │
│  One row per DirectoryIndex — records invalidated state  │
│  and last-scan timestamp                                 │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Component Reference

### 3.1 `apps.py` — `cache_startup`

Django `AppConfig` subclass. Its `ready()` method is the entry point for the whole
subsystem.

**Startup logic by execution context:**

| Context | Detection | Action |
|---|---|---|
| Management command (scan, migrate, shell, …) | `sys.argv[1]` is not a server command | Skip — no watchdog needed |
| Dev server child process | `RUN_MAIN=true` or `WERKZEUG_RUN_MAIN=true` | Start watchdog directly |
| Dev server parent (reloader monitor) | Neither env var set | Skip |
| Production WSGI/ASGI worker (gunicorn, uvicorn, hypercorn) | Neither env var, no manage.py | Use `fcntl` file lock to elect one worker |

The file lock (`/tmp/quickbbs_watchdog.lock`) records the winning worker's PID and is
released via `atexit`. On startup, a stale lock (PID no longer alive) is removed
automatically before attempting to acquire.

---

### 3.2 `watchdogmon.py` — `WatchdogMonitor`

Thin wrapper around the third-party `watchdog` library's `Observer`.

**Key methods:**

| Method | Description |
|---|---|
| `startup(monitor_path, event_handler, force_recreate)` | Schedules `event_handler` on `monitor_path` recursively. If `force_recreate=True`, tears down and rebuilds the `Observer` instance to prevent memory leaks. |
| `stop_observer()` | Stops observer threads cleanly with a 5-second join timeout. Clears all references to allow GC. |
| `shutdown(*args)` | Called by `SIGINT` handler. Calls `stop_observer()` then `sys.exit(0)`. |

A module-level singleton `watchdog = WatchdogMonitor()` is exported; `__init__.py`
wires `signal.SIGINT` to `watchdog.shutdown`.

---

### 3.3 `models.py` — `WatchdogManager`

Orchestrates the watchdog lifecycle including scheduled periodic restarts.

**State:**

| Attribute | Type | Purpose |
|---|---|---|
| `monitor_path` | `str` | `settings.ALBUMS_PATH/albums` |
| `event_handler` | `CacheFileMonitorEventHandler` | Active handler instance |
| `restart_timer` | `threading.Timer` | Next scheduled restart |
| `lock` | `threading.Lock` | Protects all state mutations |
| `is_running` | `bool` | Guards double-start |

**Restart cycle (`WATCHDOG_RESTART_INTERVAL`, default 4 hours):**

1. `_schedule_restart()` arms a daemon `threading.Timer`.
2. When it fires, `restart()` is called from a timer thread.
3. `restart()` calls `stop()`, drains the event buffer via `_process_pending_events()`,
   clears the buffer, sleeps 1 second, then calls `start(force_recreate=True)`.
4. `start()` re-schedules the next timer.

If a restart fails the timer is re-armed anyway so the system self-recovers.

---

### 3.4 `models.py` — `LockFreeEventBuffer`

Thread-safe `deque`-backed buffer for incoming filesystem paths.

**Key behaviors:**

- `add_event(dirpath)` — appends a path; if buffer exceeds `max_size` (200), oldest 50%
  are evicted.
- `get_events_to_process()` — returns a `set` (deduplicated), clears the deque.
- Uses `threading.RLock` — **must not** be converted to `asyncio.Lock`; watchdog calls
  event handlers from OS threads outside any event loop.

---

### 3.5 `models.py` — `CacheFileMonitorEventHandler`

`watchdog.FileSystemEventHandler` subclass. Converts raw filesystem events into
batched cache invalidations.

**Event buffering strategy:**

```
event arrives
    → extract directory path
    → add to LockFreeEventBuffer
    → if no timer exists, create threading.Timer(EVENT_PROCESSING_DELAY)
    → (subsequent events during delay window are accumulated in buffer)
timer fires
    → _process_buffered_events(generation)
    → drain buffer, batch-query DirectoryIndex, invalidate cache entries
```

The "create timer only if none exists" design prevents creating thousands of `Timer`
objects during bulk copy operations (a previous design cancelled and recreated the timer
on every single event, consuming 500 MB–10 GB of memory under heavy load).

**Generation counter:** Each new timer carries a monotonically increasing
`timer_generation`. When the timer fires it first checks that its generation still
matches the handler's current generation; mismatched generations mean the handler was
superseded and the callback exits immediately.

**`cleanup()`** cancels the pending timer and increments the generation, preventing any
in-flight timer from executing after the handler is replaced during a restart.

**Processing logic in `_process_buffered_events()`:**

1. Acquire `processing_semaphore` (non-blocking); if another thread holds it, skip.
2. Call `optimized_event_buffer.get_events_to_process()` → unique set of paths.
3. Compute SHA256 for each path, batch-query `DirectoryIndex`.
4. For **known directories** → call `Cache_Storage.remove_multiple_from_cache_indexdirs()`.
5. For **unknown directories** (not in `DirectoryIndex`) that exist on disk → create
   `DirectoryIndex` placeholder via `DirectoryIndex.add_directory()`, create an
   invalidated `fs_Cache_Tracking` entry, and invalidate the parent directory so it
   rescans its child list.
6. Release semaphore, clear timer reference, call `close_old_connections()`.

The async path (`_remove_from_cache_indexdirs_async`) wraps the sync call in
`sync_to_async` and is invoked via `async_to_sync`; if that raises `RuntimeError` (not
in an async context) it falls back to a direct synchronous call.

---

### 3.6 `models.py` — `fs_Cache_Tracking`

The Django ORM model that is the authoritative record of cache state.

| Field | Type | Notes |
|---|---|---|
| `directory` | `OneToOneField` → `DirectoryIndex` | `on_delete=CASCADE`; keyed on `dir_fqpn_sha256`; `related_name="Cache_Watcher"` |
| `lastscan` | `FloatField` | Unix timestamp (float seconds) |
| `invalidated` | `BooleanField` | `True` = needs rescan; indexed |

**Composite index:** `(directory, invalidated)`.

**Key static/instance methods:**

| Method | Description |
|---|---|
| `clear_all_records()` | Bulk-sets `invalidated=True` on every row. Used by `clear_cache` management command. |
| `delete_orphaned_entries()` | Deletes rows where `directory` is null (legacy cleanup). |
| `add_from_indexdirs(index_dir)` | `update_or_create` with `invalidated=False` and current timestamp. Primary write path after a successful scan. |
| `sha_exists_in_cache(sha256)` | Returns `True` if a non-invalidated entry exists for the SHA. |
| `remove_from_cache_indexdirs(index_dir)` | Invalidates thumbnail, sets `invalidated=True`, clears layout cache. |
| `remove_multiple_from_cache_indexdirs(index_dirs)` | Batch version — preferred API; O(1) DB round-trips via bulk update + bulk create. |
| `_bulk_invalidate_by_shas(sha_list)` | Core invalidation primitive. Expands input SHAs to include all ancestors (via `DirectoryIndex.get_all_parent_shas`), bulk-updates existing rows, bulk-creates missing ones, all in one `transaction.atomic()`. |
| `_clear_layout_cache_bulk(directories)` | Clears in-memory layout/pagination cache for the given directories. |
| `_clear_directoryindex_cache_bulk(directories)` | Pops entries from the `directoryindex_cache` LRU and calls `refresh_from_db()` on any held reference. |

**Deprecated methods** (kept for backward compatibility, emit `DeprecationWarning`):

- `add_to_cache(dir_path: str)` → use `add_from_indexdirs()`
- `remove_from_cache_name(dir_path: str)` → use `remove_from_cache_indexdirs()`
- `remove_multiple_from_cache(dir_names: list[str])` → use `remove_multiple_from_cache_indexdirs()`

---

### 3.7 `models.py` — `CacheStatisticsTracking`

Stores periodic snapshots of `MonitoredLRUCache` hit/miss counters for admin display.
Rows are written by a background task; manual create/delete is disabled in admin.

Fields: `cache_name`, `hits`, `misses`, `current_size`, `max_size`, `last_snapshot_at`,
`last_reset_at`. Computed property: `hit_rate` (percentage).

---

### 3.8 `utilities.py`

Module-level helpers for bulk maintenance:

| Function | Description |
|---|---|
| `repair_orphaned_cache_entries()` | Delegates to `fs_Cache_Tracking.delete_orphaned_entries()`. Returns count deleted. |
| `rebuild_cache_entries()` | Finds `DirectoryIndex` records with no `Cache_Watcher` entry, creates them with `invalidated=True`. Returns count created. |

---

### 3.9 `check_cache_status.py`

Standalone diagnostic script (not imported by the app). Prints cache statistics and
optionally checks a specific directory path. Run directly with Python.

---

### 3.10 `admin.py`

- **`Cache_dir_tracking_Index`** — read/write admin for `fs_Cache_Tracking`. Shows
  directory path and SHA256 via `DirectoryIndex` reverse lookup. Supports full-text
  search on `fqpndirectory` and `dir_fqpn_sha256`. Uses autocomplete for the
  `directory` FK.
- **`CacheStatisticsTrackingAdmin`** — read-only view of `CacheStatisticsTracking`.
  All fields are `readonly_fields`; add and delete are disabled.

---

### 3.11 `management/commands/clear_cache.py`

Django management command: `python manage.py clear_cache --clear_cache`

Calls `fs_Cache_Tracking.clear_all_records()`, which bulk-sets all rows to
`invalidated=True`. The next request to any directory triggers a fresh scan.

---

## 4. Threading Model

The entire cache_watcher subsystem operates across three thread domains:

| Domain | Primitives required |
|---|---|
| Watchdog OS threads (filesystem event delivery) | `threading.Lock`, `threading.RLock`, `threading.Semaphore` |
| Timer threads (`threading.Timer` for debounce and restart) | Same as above |
| Django request threads / asyncio event loop | `sync_to_async`, `async_to_sync` for bridging |

**Critical rule:** Do not use `asyncio.Lock` anywhere in this module. Watchdog event
handlers are invoked from OS threads that have no relation to the asyncio event loop.
Converting any lock to `asyncio` primitives will silently break event handling.

---

## 5. Configuration (Settings)

| Setting | Purpose |
|---|---|
| `EVENT_PROCESSING_DELAY` | Seconds the debounce timer waits before processing the event buffer (default: 5 s) |
| `WATCHDOG_RESTART_INTERVAL` | Seconds between scheduled watchdog restarts (default: 14 400 s = 4 hours) |
| `ALBUMS_PATH` | Root path; watchdog monitors `{ALBUMS_PATH}/albums` |

---

## 6. Data Flow: File Change → Cache Invalidated

```
1. User copies files into Albums/foo/bar/

2. macOS FSEvents → watchdog Observer → CacheFileMonitorEventHandler.on_modified()
   (may fire multiple times; macOS sends waves of duplicate events — harmless)

3. _buffer_event():
   - Normalize path to directory (strip filename if file event)
   - Add to LockFreeEventBuffer
   - If no active timer → create threading.Timer(EVENT_PROCESSING_DELAY)

4. (5 seconds pass; more events may accumulate in buffer)

5. Timer fires → _process_buffered_events(generation):
   a. Acquire processing_semaphore (non-blocking; skip if busy)
   b. get_events_to_process() → deduplicated set of paths
   c. path → SHA256 mapping; batch query DirectoryIndex
   d. Known dirs → remove_multiple_from_cache_indexdirs()
      - _bulk_invalidate_by_shas():
        • expand to ancestors via get_all_parent_shas()
        • bulk UPDATE existing fs_Cache_Tracking rows (invalidated=True)
        • bulk CREATE any missing rows
      - _clear_layout_cache_bulk() — remove pagination cache entries
      - _clear_directoryindex_cache_bulk() — evict LRU entries, refresh_from_db
   e. Unknown dirs on disk → DirectoryIndex.add_directory() + new fs_Cache_Tracking
   f. Invalidate parent dirs of new dirs
   g. Release semaphore; clear timer ref; close_old_connections()

6. Next HTTP request for /foo/bar/:
   - sha_exists_in_cache(sha) returns False (invalidated=True)
   - QuickBBS performs fresh directory scan
   - add_from_indexdirs() marks the row invalidated=False with new lastscan
```

---

## 7. Known Behaviors and Limitations

### macOS Duplicate Events

macOS FSEvents delivers multiple waves of events for a single file operation (e.g.,
deletion triggers an initial wave then a delayed directory-metadata wave). This causes
redundant `invalidated=True` updates, which are harmless since invalidation is
idempotent. This is OS-level behavior, not a bug.

### Observer Memory Leak Mitigation

Long-running `watchdog.observers.Observer` instances accumulate internal state. The
periodic restart (`WATCHDOG_RESTART_INTERVAL`) with `force_recreate=True` tears down
and rebuilds the `Observer` to reclaim this memory.

### Event Buffer Overflow Protection

`LockFreeEventBuffer` caps at 200 entries. If the buffer exceeds that, the oldest 50%
are dropped. Under normal gallery usage this limit is never reached; it guards against
pathological bulk-copy scenarios where GC pressure would become a problem.

### ASGI / WSGI Dual-Mode

`_process_buffered_events` attempts `async_to_sync(...)` first and falls back to a
direct synchronous call if a `RuntimeError` is raised. This supports both the
development runserver (sync WSGI) and production ASGI servers (uvicorn, hypercorn)
without separate code paths.

### Manual `gc.collect()` Deliberately Omitted

An earlier version called `gc.collect()` after each event processing run. This was
removed (see `bug_hunt.md` issue #7): Python's automatic GC is sufficient, and manual
collection was causing measurable latency spikes during high-activity periods.

---

## 8. Module Structure Summary

```
cache_watcher/
├── __init__.py              # Version metadata; wires SIGINT to watchdog.shutdown
├── apps.py                  # Django AppConfig; startup/lock logic
├── models.py                # Core logic: WatchdogManager, CacheFileMonitorEventHandler,
│                            #   LockFreeEventBuffer, fs_Cache_Tracking, CacheStatisticsTracking
├── watchdogmon.py           # WatchdogMonitor: thin watchdog.Observer wrapper + singleton
├── utilities.py             # Maintenance helpers: repair_orphaned, rebuild_cache
├── admin.py                 # Django admin registrations
├── check_cache_status.py    # Standalone diagnostic script
├── benchmark_cache_watcher.py
├── management/
│   └── commands/
│       └── clear_cache.py   # "python manage.py clear_cache" command
├── migrations/              # 11 migrations (0001–0011)
├── tests/
│   └── test_cache_watcher.py
├── prototypes/              # Exploratory watchdog experiments (not production)
└── depreciated/             # Old model iterations (not imported)
```
