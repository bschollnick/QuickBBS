# cache_watcher — Design Document

**Version:** 4.5  
**Author:** Benjamin Schollnick

**Date Created:** 2026-08-08  
**Last Updated:** 2026-09-25  
**Last Reviewed:** 2026-09-25

**See also:** [`cache_watcher_erd.md`](cache_watcher_erd.md) for the entity-relationship
diagram; [`cache_watcher_exceptions.md`](cache_watcher_exceptions.md) for the
exception taxonomy.

---

## 1. Guiding Principles

`cache_watcher` implements the live half of the invalidation strategy that
[`quickbbs_app_design.md`](quickbbs_app_design.md) Section 1.1 describes at the data layer: the
filesystem is the source of truth, and a directory record just knows whether it can still
be trusted. This app is the mechanism that notices the filesystem changed in the first
place, so its principles are about noticing quickly and cheaply, not about what happens
with that knowledge afterward.

### 1.1 Notice, don't verify

Carried down from [quickbbs Section 1.1](quickbbs_app_design.md#11-the-filesystem-is-the-source-of-truth-the-database-is-a-cache).
The data layer already owns re-derivation — rescanning, reconciling membership, deciding
what changed. The watcher's only job is telling it *that* something changed and *where*,
as fast as it can, and then getting out of the way.

- **The rule.** An event handler never performs the rescan itself. It marks the affected
  directory (and its ancestors) invalidated, registers a row for any new directory it has
  not seen before (without listing that directory's contents), and stops.
- **Consequence: the watcher never blocks on slow filesystem work.** Actually rescanning
  a directory means statting files, rebuilding listings — work whose cost scales with
  directory size. Doing that inline in the event handler would make the handler itself
  slow, and a slow handler is where the real danger lies: filesystem event delivery is
  a queue with finite capacity, and a handler that falls behind risks a backlog forming
  behind it or, worse, events being dropped from the queue before they are ever seen.
  Keeping the handler's own work narrow and fast is what keeps that queue draining.

### 1.2 No scheduled sweep here either

Carried down from [quickbbs Section 1.1](quickbbs_app_design.md#11-the-filesystem-is-the-source-of-truth-the-database-is-a-cache).
The watcher runs inside whichever process `ready()` elects (Section 4.1) — there is no
standalone watcher process, and nothing here polls the filesystem on a timer. A directory
changed while no watcher was running is invisible to this app entirely; the `scan` management
command (data layer, not this app) is the intended way to catch up externally. This app
does not attempt to compensate for that gap itself.

### 1.3 Bundle repeated hits to the same directory

A single filesystem operation — a bulk copy, a large delete — can generate a long run of
individual events against the same directory in a short span. Reacting to each one
individually would mean invalidating (and logging) the same directory dozens of times
for what is, from the data layer's point of view, one change.

- **The rule.** Events for a directory are collected for a short debounce window and
  processed together as one batch, rather than triggered on every single event.
- **Consequence: one processing pass per burst, not one per event.** Bundling exists to
  stop the same directory being invalidated repeatedly for one change; it was not added
  to fix a measured memory or performance problem.

---

## 2. Purpose

`cache_watcher` is a Django application that observes the gallery filesystem for changes
and marks the affected `DirectoryIndex` records invalidated, so the next visit to a
changed directory rescans it instead of serving its stale listing.

It owns:

- **Filesystem observation** — a `watchdog`-backed observer on the albums root,
  detecting file and directory creation, deletion, modification, and moves.
- **Event debouncing and batching** — collapsing bursts of events for the same
  directory into a single invalidation pass.
- **Single-instance startup** — starting an observer only in a server process, and
  electing one among a production server's workers so several workers do not each run
  one (Section 4.1).

It does not own rescanning, listing reconstruction, or any decision about *what* a
directory now contains — that is `quickbbs.directoryindex.DirectoryIndex`'s
responsibility, triggered the next time the directory is visited or explicitly scanned.

---

## 3. High-Level Architecture

```
Django app startup                               apps.py: CacheWatcherConfig.ready()
  │                      quickbbs.server_role.server_role() decides; production workers
  │                                             elect one watcher with an fcntl lock
  ▼
WatchdogManager.start()                                        models.py
  │                                    creates CacheFileMonitorEventHandler
  │                  schedules restart timer (WATCHDOG_RESTART_INTERVAL, 4 hours)
  ▼
WatchdogMonitor.startup()                                   watchdogmon.py
  │                                thin wrapper around watchdog.observers.Observer
  ▼
CacheFileMonitorEventHandler                                        models.py
  on_created / on_deleted / on_modified / on_moved
  │                                     → _buffer_event()  → LockFreeEventBuffer
  │                              → threading.Timer(EVENT_PROCESSING_DELAY)
  ▼
_process_buffered_events()                                          models.py
  │                        → _apply_directory_changes()
  │                        → DirectoryIndex.invalidate_caches(known directories)
  │                     → DirectoryIndex.add_directory() (new directories on disk)
  ▼
DirectoryIndex (cache_invalidated / cache_lastscan)          quickbbs/directoryindex.py
```

---

## 4. Component Reference

### 4.1 `apps.py`

**What does this do?** Decides, when the server first starts up, which single process
is allowed to be the one watching the gallery for filesystem changes, so the whole
system doesn't end up with several watchers all reacting to the same change at once.

**What is its purpose?** Defines `CacheWatcherConfig`, the Django `AppConfig` subclass whose
`ready()` hook is the entry point for the whole subsystem. The process classification comes
from `quickbbs.server_role.server_role()`, which `QuickbbsConfig.ready()` also uses to run its
start-up checks once per server.

---

#### `ready()`

**What does this do?** Decides, once per process, whether *this* process is the one
that gets to watch the filesystem — so that running several worker processes (as a
production server normally does) doesn't mean several observers all reacting to the
same changes.

**What is its purpose?** `AppConfig.ready()` hook: asks which of three roles the current
process has, and starts `watchdog_manager` only where that role calls for it.

`quickbbs.server_role.server_role()` classifies the process from `sys.argv` and the
`QUICKBBS_SERVER` environment variable; `ready()` acts on its answer. Starting a watchdog in every process that
loads Django would mean several observers reacting to the same filesystem, each
repeating the same work.

| Role | Detection | Action |
|---|---|---|
| `dev_server`: the development server's reloader child | `manage.py runserver`/`runserver_plus` with `RUN_MAIN` or `WERKZEUG_RUN_MAIN` set to `"true"` | Start the watchdog directly, with no lock |
| `not_a_server`: any other `manage.py` command, or the development server's reloader parent | `argv[0]` ends with `manage.py` and the row above does not match | Skip |
| `production_server`: an ASGI server worker | `QUICKBBS_SERVER=1` in the environment; every `start_*.sh` server script exports it | Start the watchdog only in the worker that wins the `fcntl` lock |
| `not_a_server`: everything else — pytest, scripts that call `django.setup()`, the `django-ai-boost` MCP server | none of the above | Skip |

A server started by hand, without a start script, needs `QUICKBBS_SERVER=1` set, or it
serves requests with no watchdog and skips `QuickbbsConfig.ready()`'s start-up checks.
The development server's reloader child takes no lock, so a development server and a
production server started at the same time each run a watchdog.

The production election (`_acquire_watchdog_lock()`) writes the winning worker's PID to
`WATCHDOG_LOCK_PATH` (`/tmp/quickbbs_watchdog.lock`) and releases it via `atexit`. Before
the attempt, `_remove_stale_lock()` deletes a lock file whose recorded PID is no longer
running; a PID owned by another user counts as running, and its file is kept.

---

### 4.2 `watchdogmon.py`

**What does this do?** Gives the rest of the app one simple switch to turn filesystem
watching on and off, instead of every caller needing to know how the underlying
watchdog library actually works.

**What is its purpose?** Defines `WatchdogMonitor`, a thin wrapper around the
third-party `watchdog` library's `Observer`, exposing `startup`, `stop_observer` and
`shutdown` instead of the `Observer` API directly. It also defines an `on_event()`
method that does nothing and has no caller.

A module-level singleton `watchdog = WatchdogMonitor()` is exported. `__init__.py` wires
`signal.SIGINT` to `watchdog.shutdown` when the `cache_watcher` package is imported,
which happens in every process that loads Django.

---

#### `startup(monitor_path, event_handler, force_recreate)`

**What does this do?** Turns on filesystem watching for a path, without the caller
needing to know anything about the underlying `watchdog` library's API.

**What is its purpose?** Schedules `event_handler` on `monitor_path`, recursively. If
`force_recreate=True`, tears down the existing `Observer` first and creates a new one;
otherwise any handler already scheduled on the existing `Observer` is unscheduled and the
`Observer` is reused.

---

#### `stop_observer()`

**What does this do?** Turns off filesystem watching cleanly, without killing the
process — the operation used for restarts and ordinary shutdown alike.

**What is its purpose?** Unschedules the current watch, stops the observer threads with
a 5-second join timeout (logging a warning if they are still alive), then clears all
references so they can be garbage collected. The references are cleared even when
stopping raises.

---

#### `shutdown(*args)`

**What does this do?** The last thing that runs when the whole server process is told
to stop — makes sure the filesystem watcher doesn't keep running past the server it
belongs to.

**What is its purpose?** Bound to `SIGINT`. Calls `stop_observer()` only when `RUN_MAIN`
is `"true"` (the development server's reloader child), then calls `sys.exit(0)` in every
case.

---

### 4.3 `models.py`

**What does this do?** Collects up all the directories that changed during a burst of
filesystem activity — like copying in a whole folder of files — into one pending list,
instead of reacting separately to every single file that changed.

**What is its purpose?** Defines `LockFreeEventBuffer`, the deduplicating buffer for
pending directory paths that implements Section 1.3's bundling.

Despite its name, every method takes a `threading.RLock`. It is a `threading` lock, not
an `asyncio.Lock`, because watchdog delivers events from OS threads outside any asyncio
event loop, and an `asyncio.Lock` would not exclude those threads at all.

---

#### `add_event(dirpath)`

**What does this do?** Records that something changed in a directory, without piling
up a separate record for every individual file event inside a bulk operation.

**What is its purpose?** Adds `dirpath` to the pending set. Paths are stored in a
`set` rather than a list, so repeated events for the same directory — the common case
within one debounce window — collapse to a single entry at insert time rather than
being deduplicated later.

`max_size` (200) caps *unique* directories pending, not raw events. When an insert takes
the set past that cap, arbitrary entries are removed until 100 (half of `max_size`)
remain, and a warning logs how many were dropped. A set has no order, so which
directories are dropped is not predictable, and their invalidations are lost. The cap
guards against one burst spanning more than 200 distinct directories; a bulk copy
into a few directories does not approach it.

---

#### `get_events_to_process()`

**What does this do?** Hands over everything that has piled up since the last check,
and clears the slate for what comes next.

**What is its purpose?** Atomically swaps the internal set for an empty one and returns
the previous contents — the deduplicated set of directory paths pending invalidation.

---

### 4.4 `models.py`

**What does this do?** Keeps the filesystem watcher alive and healthy over the long
run, giving it a fresh start every so often instead of letting it run forever
unattended.

**What is its purpose?** Defines `WatchdogManager`, which orchestrates the watchdog's
lifecycle, including its own periodic restart.

**State:**

| Attribute | Type | Purpose |
|---|---|---|
| `monitor_path` | `str` | `{ALBUMS_PATH}/albums`, read once when the manager is constructed (at import of `cache_watcher.models`) |
| `event_handler` | `CacheFileMonitorEventHandler \| None` | Currently active handler |
| `restart_timer` | `threading.Timer \| None` | Next scheduled restart |
| `lock` | `threading.Lock` | Guards all state mutation |
| `is_running` | `bool` | Prevents double-start |

---

#### `start(force_recreate)`

**What does this do?** Turns filesystem watching on, and makes sure it stays on by
scheduling its own future restart at the same time.

**What is its purpose?** Creates a `CacheFileMonitorEventHandler`, hands it to
`watchdog.startup()`, and — on success — calls `_schedule_restart()` so the periodic
restart cycle described below is armed from the moment watching begins. If the manager
is already running it logs that and does nothing; if `watchdog.startup()` raises, it
logs the error and re-raises.

---

#### `restart()`

**What does this do?** Periodically gives the filesystem watcher a clean restart, on a
fixed schedule, rather than letting it run indefinitely without ever being reset.

**What is its purpose?** Stops the watchdog, drains and processes any events still
sitting in the buffer via `_process_pending_events()` (so a restart can't silently lose
a burst that hadn't debounced yet), clears the buffer, pauses one second, then starts
again with `force_recreate=True`.

**Restart cycle** (`WATCHDOG_RESTART_INTERVAL`, default 4 hours): `_schedule_restart()`
arms a daemon `threading.Timer`; when it fires, this method runs.

On this fixed schedule, the `Observer` and its internal state are recreated from a
clean baseline. This is a precaution; no leak in the `Observer` has been confirmed. If a
restart itself fails, the timer is re-armed anyway, keeping the cycle running.

---

### 4.5 `models.py`

**What does this do?** Listens for anything happening on disk — a file added, removed,
changed, or moved — and turns that into the signal the rest of the app needs to know a
directory's listing can no longer be trusted as-is.

**What is its purpose?** Defines `CacheFileMonitorEventHandler`, a
`watchdog.FileSystemEventHandler` subclass that converts raw filesystem events into
batched `DirectoryIndex` invalidations — the concrete implementation of Section 1.1 and Section 1.3.

```
event arrives (on_created / on_deleted / on_modified / on_moved)
    → _buffer_event(): reduce to a directory path, add to LockFreeEventBuffer
    → if no debounce timer is currently running, start one (EVENT_PROCESSING_DELAY)
      (further events during that window just add to the buffer; no new timer)
timer fires
    → _process_buffered_events(generation)
```

---

#### `_buffer_event(event)`

**What does this do?** Notes that something changed in a directory, without doing
anything expensive right away — the actual work waits until a short quiet period has
passed.

**What is its purpose?** Reduces the event to a directory path, adds it to the shared
`LockFreeEventBuffer`, and, if no debounce timer is currently running for this handler,
starts one for `EVENT_PROCESSING_DELAY` seconds. Any exception is logged and swallowed,
because one escaping would stop event delivery on the observer thread.

**Which directory.** A directory event contributes its own path; a file event
contributes the file's parent directory. A move uses `src_path` only, so `on_moved`
never adds the destination directory. On macOS the destination directory receives its
own directory-modified event, which invalidates it; other platforms have not been
checked.

**Debounce, not per-event dispatch.** A timer is created only if none is already
running for this handler — subsequent events during the window are folded into the same
buffer rather than resetting or multiplying the timer. This is what bundles a burst of
events for one directory (e.g. copying a folder full of files) into a single invalidation
pass instead of one per file — see Section 1.3.

**Generation counter.** Each new timer carries a monotonically increasing
`timer_generation`. When a timer fires, it first checks that its generation still
matches the handler's current one; a mismatch means `cleanup()` ran on this handler
after the timer was created, and the callback exits without doing anything.
`WatchdogManager.stop()` and `shutdown()` call `cleanup()`, which cancels a pending timer
and bumps the generation, so no timer from a replaced handler processes events.

---

#### `_process_buffered_events(expected_generation)`

**What does this do?** Turns everything that piled up during the last quiet period into
the actual database updates that tell the rest of QuickBBS a directory needs rescanning
— and, for directories the database doesn't know about yet, creates a record for them.

**What is its purpose?** Drains the event buffer, resolves each path to a
`DirectoryIndex` row (or creates one if none exists yet), and marks the affected rows
invalidated.

1. Return at once if `expected_generation` no longer matches the handler's
   `timer_generation` (see the generation counter above).
2. Acquire `processing_semaphore` (non-blocking). If another thread already holds it,
   clear the timer reference and return. The buffered paths stay in the buffer until
   the next event starts a new timer, or the next restart flushes them.
3. `get_events_to_process()` — drain the buffer to a deduplicated set of paths.
4. `_apply_directory_changes()`, which `_process_pending_events()` also calls before a
   restart:
   - Compute each path's directory SHA256 and batch-query `DirectoryIndex` for matches.
   - **Known directories** → `DirectoryIndex.invalidate_caches(...)`.
   - **Paths with no `DirectoryIndex` row that are directories on disk** →
     `DirectoryIndex.add_directory()` creates a row, born `cache_invalidated=True` (the
     field's default). The new rows' parent directories are then invalidated, so each
     parent's subdirectory listing picks up the new entry on its next scan.
5. Release the semaphore, clear the timer reference, `close_old_connections()`.

`invalidate_caches()` itself — expanding to ancestor directories, clearing the layout and
`directoryindex_cache` entries — lives in `quickbbs.directoryindex.DirectoryIndex`, not
here; this handler only decides *which* SHAs need invalidating and hands them off.

---

### 4.6 `models.py` — `CacheStatisticsTracking`

**What does this do?** Records how well the app's in-memory caches are performing, so
an administrator can see whether each one is actually helping.

**What is its purpose?** Defines `CacheStatisticsTracking`, a Django model (table
`cache_statistics_tracking`) holding one row per cache with its latest hit/miss counters,
for display in the Django administration site. Rows are written by
`quickbbs.tasks.snapshot_cache_statistics()`, which the gallery view calls on each
request when `CACHE_MONITORING` is on and which writes at most once per
`SNAPSHOT_MIN_INTERVAL` seconds. `quickbbs.tasks.reconcile_cache_statistics_rows()`
deletes rows for caches that are no longer registered. Adding and deleting rows by hand
is disabled in the administration site (`admin.py`).

Fields: `cache_name`, `hits`, `misses`, `current_size`, `max_size`, `last_snapshot_at`,
`last_reset_at`.

This model is unrelated to directory invalidation — it is a read side-channel for
observing the health of the LRU caches described in
[`quickbbs_app_design.md`](quickbbs_app_design.md) Section 5, not part of the invalidation path
itself.

---

#### `hit_rate` (property)

**What does this do?** Turns raw hit/miss counts into the single number an
administrator wants to glance at.

**What is its purpose?** Returns `hits / (hits + misses)` as a percentage from 0.0 to
100.0, or `0.0` if no requests have been recorded yet.

---

### 4.7 `admin.py`

**What does this do?** Lets whoever runs the gallery look at how well each in-memory
cache is sized, and gives them a plain-language hint about whether a given cache
looks too small, too large, or fine — without having to interpret the raw hit/miss
numbers by hand.

**What is its purpose?** `CacheStatisticsTrackingAdmin` — a read-only administration
view of `CacheStatisticsTracking`. Every field is in `readonly_fields`; add and delete are
both disabled, since rows are written only by the snapshot and reconciliation functions
(Section 4.6).

**Sizing Advice column.** A low hit rate alone doesn't say what to do about it — it
has two unrelated causes (see
[`quickbbs_app_design.md` Section 4.5](quickbbs_app_design.md#45-monitoredcachepy) for the
full reasoning): eviction pressure,
where a key is really being reused but doesn't survive long enough in the cache to be
there for the second lookup, and cold-key traffic, where most keys are inherently
one-shot and no `maxsize` would ever turn a miss into a hit. `get_sizing_advice()`
distinguishes the two using `current_size` relative to `max_size` from the same
snapshot row. A hit rate below 60% is low; a cache at 90% or more of `max_size` is full;
one at 50% or less is underused.

| Condition | Verdict |
|---|---|
| Fewer than 50 combined hits and misses | "Not enough traffic yet" |
| `max_size` is 0 or less | "—" |
| Healthy hit rate, underused | "Healthy, oversized — could shrink `<NAME>_CACHE_SIZE`" |
| Healthy hit rate, otherwise | "Healthy" |
| Low hit rate, full | "Full + low hit rate — consider raising `<NAME>_CACHE_SIZE`" |
| Low hit rate, underused | Likely one-shot traffic; raising `maxsize` probably won't help |
| Low hit rate, between 50% and 90% full | "Low hit rate — inconclusive, watch over more traffic" |

The verdicts suggest rather than instruct, because one snapshot cannot tell the two
causes apart with certainty. The changelist page carries a legend (through
`change_list_template`) explaining the same two-cause reasoning for anyone reading the
table.

---

### 4.8 `management/commands/clear_cache.py`

`python manage.py clear_cache` — an operational escape hatch, not part of the
event-driven invalidation path.

---

#### `handle()`

**What does this do?** Gives an operator a manual button to force every directory to
rescan, for the cases the filesystem watcher itself cannot cover — most notably changes
made while no server was running.

**What is its purpose?** Calls `DirectoryIndex.invalidate_all_caches()` directly. It
also accepts a `--clear_cache` flag, which changes nothing: every run invalidates. This
is a full, unconditional invalidation of every `DirectoryIndex` row, not a
`cache_watcher`-specific operation; the command lives in this app only because it is the
operational entry point for "force everything to rescan."

---

## 5. Threading Model

The subsystem spans three thread domains, and the placement of every lock in it follows
directly from that:

| Domain | What runs there |
|---|---|
| Watchdog OS threads | Filesystem event delivery (`on_created`, `on_modified`, …) |
| Timer threads | `threading.Timer` callbacks for both debounce and periodic restart |
| Django request threads / asyncio event loop | Everything else in the web server |

**The rule.** Every in-process lock in this app is a `threading` primitive (`Lock`,
`RLock`, `Semaphore`), never `asyncio.Lock`; the only other lock is the cross-process
`fcntl` file lock that elects the production watcher (Section 4.1). Watchdog's OS threads and `threading.Timer` callbacks
have no relation to any asyncio event loop; an `asyncio.Lock` would simply not
synchronize against them, and would silently reintroduce the races the locks exist to
prevent.

---

## 6. Configuration

All three are Django settings; the first two are defined in
`quickbbs/quickbbs_settings.py`.

| Setting | Purpose |
|---|---|
| `EVENT_PROCESSING_DELAY` | Debounce window, in seconds, before buffered events are processed (default: 5) |
| `WATCHDOG_RESTART_INTERVAL` | Seconds between periodic `Observer` restarts (default: 14400 — 4 hours) |
| `ALBUMS_PATH` | Root path; the watcher observes `{ALBUMS_PATH}/albums` |

---

## 7. Known Behaviors

### macOS duplicate events

macOS's FSEvents delivers multiple waves of events for a single file operation — for
example, a deletion produces an immediate wave and then a delayed directory-metadata
wave. This produces redundant invalidations. It is harmless, since invalidation is
idempotent, and it is OS-level behavior rather than a bug in this app.

### Event buffer overflow

`LockFreeEventBuffer` caps at 200 unique pending directories; beyond that, arbitrary
entries are dropped until 100 remain, with a logged warning (Section 4.3). Ordinary
gallery use does not approach this limit; only a burst spanning more than 200 distinct
directories at once reaches it.

### ASGI / WSGI dual-mode

Event processing runs on a `threading.Timer` thread (or the restart timer's thread,
for the pre-restart flush), never inside Django's async request path, so no `sync_to_async`/`async_to_sync` bridging is needed in the
handler itself — it calls `DirectoryIndex.invalidate_caches()` directly and closes its
own database connections afterward with `close_old_connections()`.

---

## 8. Module Structure Summary

```
cache_watcher/
├── __init__.py              # Version metadata; wires SIGINT to watchdog.shutdown
├── apps.py                  # Django AppConfig; single-instance startup/lock logic
├── models.py                # WatchdogManager, CacheFileMonitorEventHandler,
│                            #   LockFreeEventBuffer, CacheStatisticsTracking
├── watchdogmon.py           # WatchdogMonitor: thin watchdog.Observer wrapper + singleton
├── admin.py                 # Django administration registration for CacheStatisticsTracking
├── management/
│   └── commands/
│       └── clear_cache.py   # "python manage.py clear_cache" — full invalidation
├── migrations/               # Schema history: CacheStatisticsTracking and the removed fs_Cache_Tracking model
├── tests/
│   ├── test_apps.py              # Stale watchdog lock-file handling
│   ├── test_cache_statistics.py  # CacheStatisticsTracking
│   ├── test_event_handling.py    # Event buffer and event handler
│   └── test_watchdog_manager.py  # WatchdogManager lifecycle (mocked)
├── prototypes/               # Holds no source files, only a stale __pycache__/
└── depreciated/              # Holds no source files, only a stale __pycache__/
```

---

## 9. Future Ideas

No open ideas are currently tracked for this app.
