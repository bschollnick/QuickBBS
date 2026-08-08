# cache_watcher — Design Document

**Version:** 4.4
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

**See also:** [`cache_watcher_erd.md`](cache_watcher_erd.md) for the entity-relationship
diagram; [`cache_watcher_exceptions.md`](cache_watcher_exceptions.md) for the
exception taxonomy.

---

## 1. Guiding Principles

`cache_watcher` implements the live half of the invalidation strategy that
[`quickbbs_app_design.md`](quickbbs_app_design.md) §1.1 describes at the data layer: the
filesystem is the source of truth, and a directory record just knows whether it can still
be trusted. This app is the mechanism that notices the filesystem changed in the first
place, so its principles are about noticing quickly and cheaply, not about what happens
with that knowledge afterward.

### 1.1 Notice, don't verify

Carried down from [quickbbs §1.1](quickbbs_app_design.md#11-the-filesystem-is-the-source-of-truth-the-database-is-a-cache).
The data layer already owns re-derivation — rescanning, reconciling membership, deciding
what changed. The watcher's only job is telling it *that* something changed and *where*,
as fast as it can, and then getting out of the way.

- **The rule.** An event handler never performs the rescan itself. It marks the affected
  directory (and its ancestors) invalidated and stops.
- **Consequence: the watcher never blocks on slow filesystem work.** Actually rescanning
  a directory means statting files, rebuilding listings — work whose cost scales with
  directory size. Doing that inline in the event handler would make the handler itself
  slow, and a slow handler is where the real danger lies: filesystem event delivery is
  a queue with finite capacity, and a handler that falls behind risks a backlog forming
  behind it or, worse, events being dropped from the queue before they are ever seen.
  Keeping the handler's own work narrow and fast is what keeps that queue draining.

### 1.2 No scheduled sweep here either

Carried down from [quickbbs §1.1](quickbbs_app_design.md#11-the-filesystem-is-the-source-of-truth-the-database-is-a-cache).
The watcher only runs inside a running web server process — there is no standalone
watcher process, and nothing here polls the filesystem on a timer. A directory changed
while no server was running is invisible to this app entirely; the `scan` management
command (data layer, not this app) is the intended way to catch up externally. This app
does not attempt to compensate for that gap itself.

### 1.3 Bundle repeated hits to the same directory

A single filesystem operation — a bulk copy, a large delete — can generate a long run of
individual events against the same directory in a short span. Reacting to each one
individually would mean invalidating (and logging) the same directory dozens of times
for what is, from the data layer's point of view, one change.

- **The rule.** Events for a directory are collected for a short debounce window and
  processed together as one batch, rather than triggered on every single event.
- **Consequence: one processing pass per burst, not one per event.** The goal is
  minimizing repeated hits to the same directory, not a resource-usage fix — no memory
  or performance problem has actually been observed from the naive per-event approach;
  bundling is done because it is the more sensible way to handle a burst of events
  describing the same change.

---

## 2. Purpose

`cache_watcher` is a Django application that observes the gallery filesystem for changes
and marks the affected `DirectoryIndex` records invalidated, so QuickBBS never serves a
stale directory listing without an explicit, deliberate cache lookup to justify it.

It owns:

- **Filesystem observation** — a `watchdog`-backed observer on the albums root,
  detecting file and directory creation, deletion, modification, and moves.
- **Event debouncing and batching** — collapsing bursts of events for the same
  directory into a single invalidation pass.
- **Single-instance startup** — ensuring exactly one observer runs regardless of how
  many worker processes the web server spawns.

It does not own rescanning, listing reconstruction, or any decision about *what* a
directory now contains — that is `quickbbs.directoryindex.DirectoryIndex`'s
responsibility, triggered the next time the directory is visited or explicitly scanned.

---

## 3. High-Level Architecture

```
Django app startup                                    apps.py: cache_startup.ready()
  │                                        elects one instance (dev child / prod flock)
  ▼
WatchdogManager.start()                                        models.py
  │                                    creates CacheFileMonitorEventHandler
  │                                        schedules 4-hour restart timer
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
  │                        → DirectoryIndex.invalidate_caches(known dirs)
  │                     → DirectoryIndex.add_directory() (unknown dirs on disk)
  ▼
DirectoryIndex (cache_invalidated / cache_lastscan)          quickbbs/directoryindex.py
```

---

## 4. Component Reference

### 4.1 `apps.py`

**What does this do?** Decides, when the server first starts up, which single process
is allowed to be the one watching the gallery for filesystem changes, so the whole
system doesn't end up with several watchers all reacting to the same change at once.

**What is its purpose?** Defines `cache_startup`, the Django `AppConfig` subclass whose
`ready()` hook is the entry point for the whole subsystem.

---

#### `ready()`

**What does this do?** Decides, once per process, whether *this* process is the one
that gets to watch the filesystem — so that running several worker processes (as a
production server normally does) doesn't mean several observers all reacting to the
same changes.

**What is its purpose?** `AppConfig.ready()` hook: detects which of three execution
contexts the current process is running in, and starts `watchdog_manager` only in the
one process that should own it.

Three execution contexts are distinguished by argv and environment, because the
alternative — starting a watchdog in every process that happens to import Django — would
mean multiple observers reacting to the same filesystem, each doing the same redundant
work over again.

| Context | Detection | Action |
|---|---|---|
| Management command (`scan`, `migrate`, `shell`, …) | `argv[1]` is not `runserver`/`runserver_plus` | Skip — no watchdog needed |
| Dev server reloader child | `RUN_MAIN=true` or `WERKZEUG_RUN_MAIN=true` | Start watchdog directly |
| Dev server reloader parent / MCP servers | Neither env var set | Skip |
| Production WSGI/ASGI worker (gunicorn, uvicorn, hypercorn) | Neither dev-server env var, `argv[0]` is not `manage.py` | Elect one worker via `fcntl` file lock |

The production election writes the winning worker's PID to `/tmp/quickbbs_watchdog.lock`
and releases it via `atexit`. On startup, a lock file whose recorded PID is no longer
alive is treated as stale and removed before a new attempt.

---

### 4.2 `watchdogmon.py`

**What does this do?** Gives the rest of the app one simple switch to turn filesystem
watching on and off, instead of every caller needing to know how the underlying
watchdog library actually works.

**What is its purpose?** Defines `WatchdogMonitor`, a thin wrapper around the
third-party `watchdog` library's `Observer`, exposing one small surface (`startup`,
`stop_observer`, `shutdown`) instead of the `Observer` API directly.

A module-level singleton `watchdog = WatchdogMonitor()` is exported; `__init__.py` wires
`signal.SIGINT` to `watchdog.shutdown`.

---

#### `startup(monitor_path, event_handler, force_recreate)`

**What does this do?** Turns on filesystem watching for a path, without the caller
needing to know anything about the underlying `watchdog` library's API.

**What is its purpose?** Schedules `event_handler` on `monitor_path`, recursively. If
`force_recreate=True`, tears down and rebuilds the `Observer` instance first.

---

#### `stop_observer()`

**What does this do?** Turns off filesystem watching cleanly, without killing the
process — the operation used for restarts and ordinary shutdown alike.

**What is its purpose?** Stops observer threads with a 5-second join timeout, then
clears all references so they can be garbage collected.

---

#### `shutdown(*args)`

**What does this do?** The last thing that runs when the whole server process is told
to stop — makes sure the filesystem watcher doesn't keep running past the server it
belongs to.

**What is its purpose?** Bound to `SIGINT`. Calls `stop_observer()`, then `sys.exit(0)`.

---

### 4.3 `models.py`

**What does this do?** Collects up all the directories that changed during a burst of
filesystem activity — like copying in a whole folder of files — into one pending list,
instead of reacting separately to every single file that changed.

**What is its purpose?** Defines `LockFreeEventBuffer`, the deduplicating buffer for
pending directory paths that implements §1.3's bundling.

Uses `threading.RLock`, not `asyncio.Lock` — watchdog delivers events from OS threads
that exist outside any asyncio event loop, so an `asyncio.Lock` here would simply never
be contended correctly and would silently break the buffering.

---

#### `add_event(dirpath)`

**What does this do?** Records that something changed in a directory, without piling
up a separate record for every individual file event inside a bulk operation.

**What is its purpose?** Adds `dirpath` to the pending set. Paths are stored in a
`set` rather than a list, so repeated events for the same directory — the common case
within one debounce window — collapse to a single entry at insert time rather than
being deduplicated later.

`max_size` (200) caps *unique* directories pending, not raw events; if that cap is
exceeded the oldest 50% are evicted with a logged warning. Under ordinary gallery
activity this limit is not reached — it exists as a safety valve against a
pathologically wide burst of changes across many directories at once, not against
ordinary bulk-copy volume within a few directories.

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
| `monitor_path` | `str` | `{ALBUMS_PATH}/albums` |
| `event_handler` | `CacheFileMonitorEventHandler` | Currently active handler |
| `restart_timer` | `threading.Timer` | Next scheduled restart |
| `lock` | `threading.Lock` | Guards all state mutation |
| `is_running` | `bool` | Prevents double-start |

---

#### `start(force_recreate)`

**What does this do?** Turns filesystem watching on, and makes sure it stays on by
scheduling its own future restart at the same time.

**What is its purpose?** Creates a `CacheFileMonitorEventHandler`, hands it to
`watchdog.startup()`, and — on success — calls `_schedule_restart()` so the periodic
restart cycle described below is armed from the moment watching begins.

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

On this fixed schedule, the `Observer` and its internal state — including its event
counters — get recreated from a clean baseline, rather than running indefinitely. If a
restart itself fails, the timer is re-armed anyway, keeping the cycle running.

---

### 4.5 `models.py`

**What does this do?** Listens for anything happening on disk — a file added, removed,
changed, or moved — and turns that into the signal the rest of the app needs to know a
directory's listing can no longer be trusted as-is.

**What is its purpose?** Defines `CacheFileMonitorEventHandler`, a
`watchdog.FileSystemEventHandler` subclass that converts raw filesystem events into
batched `DirectoryIndex` invalidations — the concrete implementation of §1.1 and §1.3.

```
event arrives (on_created / on_deleted / on_modified / on_moved)
    → _buffer_event(): normalize to a directory path, add to LockFreeEventBuffer
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

**What is its purpose?** Normalizes the event to a directory path, adds it to the
shared `LockFreeEventBuffer`, and, if no debounce timer is currently running for this
handler, starts one for `EVENT_PROCESSING_DELAY` seconds.

**Debounce, not per-event dispatch.** A timer is created only if none is already
running for this handler — subsequent events during the window are folded into the same
buffer rather than resetting or multiplying the timer. This is what bundles a burst of
events for one directory (e.g. copying a folder full of files) into a single invalidation
pass instead of one per file — see §1.3.

**Generation counter.** Each new timer carries a monotonically increasing
`timer_generation`. When a timer fires, it first checks that its generation still
matches the handler's current one; a mismatch means this handler was superseded (a
restart happened mid-flight) and the callback exits without doing anything.
`cleanup()` cancels any pending timer and bumps the generation, so no in-flight timer
can fire after its handler has been replaced.

---

#### `_process_buffered_events(expected_generation)`

**What does this do?** Turns everything that piled up during the last quiet period into
the actual database updates that tell the rest of QuickBBS a directory needs rescanning
— and, for directories the database doesn't know about yet, creates a record for them.

**What is its purpose?** Drains the event buffer, resolves each path to a
`DirectoryIndex` row (or creates one if none exists yet), and marks the affected rows
invalidated.

1. Acquire `processing_semaphore` (non-blocking); if another thread already holds it,
   skip this run — the next debounce window will pick up whatever is left in the buffer.
2. `get_events_to_process()` — drain the buffer to a deduplicated set of paths.
3. Compute each path's directory SHA256, batch-query `DirectoryIndex` for matches.
4. **Known directories** → `DirectoryIndex.invalidate_caches(...)`.
5. **Paths not found in `DirectoryIndex` that still exist on disk** →
   `DirectoryIndex.add_directory()` is called only for these missing paths, creating a
   new row (born `cache_invalidated=True`, the field's default for every row regardless
   of how it was created); its parent directory is then invalidated so the parent's
   subdirectory listing picks up the new entry on its next scan. A path that already has
   a `DirectoryIndex` row skips this step entirely — it was already handled in step 4.
6. Release the semaphore, clear the timer reference, `close_old_connections()`.

`invalidate_caches()` itself — expanding to ancestor directories, clearing the layout and
`directoryindex_cache` entries — lives in `quickbbs.directoryindex.DirectoryIndex`, not
here; this handler only decides *which* SHAs need invalidating and hands them off.

---

### 4.6 `models.py`

**What does this do?** Keeps a history of how well the app's in-memory caches are
performing, so an administrator can look back and see whether they're actually helping.

**What is its purpose?** Defines `CacheStatisticsTracking`, a Django model storing
periodic snapshots of in-memory LRU cache hit/miss counters for admin display. Rows are
written by a background snapshot task; manual create/delete is disabled in admin
(`admin.py`).

Fields: `cache_name`, `hits`, `misses`, `current_size`, `max_size`, `last_snapshot_at`,
`last_reset_at`.

This model is unrelated to directory invalidation — it is a read side-channel for
observing the health of the LRU caches described in
[`quickbbs_app_design.md`](quickbbs_app_design.md) §5, not part of the invalidation path
itself.

---

#### `hit_rate` (property)

**What does this do?** Turns raw hit/miss counts into the single number an admin
actually wants to glance at.

**What is its purpose?** Returns `hits / (hits + misses)` as a percentage, or `0.0` if
no requests have been recorded yet.

---

### 4.7 `admin.py`

**What does this do?** Lets whoever runs the gallery look at how well each in-memory
cache is sized, and gives them a plain-language hint about whether a given cache
looks too small, too large, or fine — without having to interpret the raw hit/miss
numbers by hand.

**What is its purpose?** `CacheStatisticsTrackingAdmin` — a read-only admin view of
`CacheStatisticsTracking`. Every field is `readonly_fields`; add and delete are both
disabled, since rows are managed exclusively by the snapshot task.

**Sizing Advice column.** A low hit rate alone doesn't say what to do about it — it
has two unrelated causes (see
[`quickbbs_app_design.md` §4.5](quickbbs_app_design.md#45-monitoredcachepy) for the
full reasoning): eviction pressure,
where a key is really being reused but doesn't survive long enough in the cache to be
there for the second lookup, and cold-key traffic, where most keys are inherently
one-shot and no `maxsize` would ever turn a miss into a hit. `get_sizing_advice()`
distinguishes the two using `current_size` relative to `max_size` from the same
snapshot row: a cache running near full with a low hit rate is flagged as
eviction-pressured (worth raising its `*_CACHE_SIZE` setting); a cache running well
under its `max_size` with a low hit rate is flagged as likely cold-key traffic
(raising the size probably won't help, and shrinking an oversized-but-healthy cache
is suggested instead). Below the minimum sample size (50 combined hits and misses),
the column reports "Not enough traffic yet" rather than guessing from too little
data. Every verdict is deliberately phrased as "consider" language, never a command —
the heuristic is a hint from one snapshot, not a decision, and the changelist page
carries a legend (via `change_list_template`) explaining the same two-cause reasoning
inline for anyone reading the table.

---

### 4.8 `management/commands/clear_cache.py`

`python manage.py clear_cache` — an operational escape hatch, not part of the
event-driven invalidation path.

---

#### `handle()`

**What does this do?** Gives an operator a manual button to force every directory to
rescan, for the cases the filesystem watcher itself cannot cover — most notably changes
made while no server was running.

**What is its purpose?** Calls `DirectoryIndex.invalidate_all_caches()` directly. This
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

**The rule.** Every lock in this app is a `threading` primitive (`Lock`, `RLock`,
`Semaphore`), never `asyncio.Lock`. Watchdog's OS threads and `threading.Timer` callbacks
have no relation to any asyncio event loop; an `asyncio.Lock` would simply not
synchronize against them, and would silently reintroduce the races the locks exist to
prevent.

---

## 6. Configuration

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

`LockFreeEventBuffer` caps at 200 unique pending directories; beyond that, the oldest
50% are dropped with a logged warning (§4.3). Ordinary gallery usage does not approach
this limit — it guards against an unusually wide burst spanning many distinct
directories at once, not against high event volume within a few.

### ASGI / WSGI dual-mode

Event processing is triggered from a watchdog OS thread, never from inside Django's
async request path, so no `sync_to_async`/`async_to_sync` bridging is needed in the
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
├── admin.py                 # Django admin registration for CacheStatisticsTracking
├── management/
│   └── commands/
│       └── clear_cache.py   # "python manage.py clear_cache" — full invalidation
├── migrations/               # Schema history for CacheStatisticsTracking
├── tests/
│   └── test_cache_watcher.py
├── prototypes/               # Exploratory watchdog experiments — not imported by the app
└── depreciated/              # Superseded model iterations — not imported by the app
```

---

## 9. Future Ideas

Nothing below is committed or scheduled — recorded so the reasoning is not lost, not as
a roadmap.

No open ideas are currently tracked for this app.
