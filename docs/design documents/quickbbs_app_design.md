# quickbbs — Application Design Document

**Version:** 3.99  
**Author:** Benjamin Schollnick  
**Last Updated:** 2026-04-11

---

## 1. Purpose

The `quickbbs` package is the **core domain layer** of the QuickBBS gallery
application. It owns:

- The two primary ORM models (`DirectoryIndex`, `FileIndex`) that represent the
  complete gallery index
- The filesystem synchronization logic that keeps the database consistent with disk
- All shared utility primitives: hashing, path normalization, sorting, caching
- The central cache registry and background task definitions
- Django configuration (settings, URL routing, ASGI/WSGI entry points)

Every other Django app (`cache_watcher`, `filetypes`, `frontend`, `thumbnails`,
`user_preferences`) depends on `quickbbs`; `quickbbs` depends on `filetypes` and
`thumbnails` only — and then only at function-call time using deferred imports to
break circular dependency chains.

---

## 2. High-Level Architecture

```
quickbbs/
├── settings.py / quickbbs_settings.py  ← Django + gallery configuration
├── urls.py                              ← URL routing for entire project
├── asgi.py / wsgi.py                   ← Server entry points
│
├── common.py         ← Hashing, path normalization, sort matrices, thread pool
├── MonitoredCache.py ← LRUCache wrapper with hit/miss tracking
├── cache_registry.py ← Shared cache instances + cross-cutting invalidation
├── natsort_model.py  ← NaturalSortField Django model field
│
├── models.py         ← Re-export facade for DirectoryIndex, FileIndex, Owners, Favorites
├── directoryindex.py ← DirectoryIndex model + filesystem sync methods
├── fileindex.py      ← FileIndex model + file metadata + link resolution
│
└── tasks.py          ← django-dbtasks background tasks (thumbnails, cleanup, stats)
```

---

## 3. Data Model

### 3.1 `DirectoryIndex` (`directoryindex.py`)

The master index for gallery directories. One row per unique filesystem path.

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `fqpndirectory` | `CharField(unique)` | Fully-qualified normalized path (lowercase, resolved, trailing `/`) |
| `dir_fqpn_sha256` | `CharField(unique)` | SHA256 of `fqpndirectory` — primary lookup key |
| `parent_directory` | `FK(self, SET_NULL)` | Self-referential parent link; `None` for the albums root |
| `lastscan` | `FloatField` | Unix timestamp of last filesystem sync |
| `lastmod` | `FloatField` | mtime from OS `stat()` |
| `name_sort` | `NaturalSortField` | Auto-computed natural-sort key over `fqpndirectory` |
| `is_generic_icon` | `BooleanField` | True if no real cover image is available |
| `delete_pending` | `BooleanField(indexed)` | Soft-delete flag; row excluded from all queries |
| `filetype` | `FK(filetypes, ".dir")` | Always the `.dir` filetype entry |
| `thumbnail` | `FK(FileIndex, SET_NULL)` | The cover-image file for this directory |

**Database indexes (Meta):**

| Fields | Purpose |
|---|---|
| `(parent_directory, delete_pending)` | Efficient `dirs_in_dir()` queries |
| `(dir_fqpn_sha256, delete_pending)` | Efficient SHA-based directory lookups |

**Reverse relationships:**

| Attribute | Source |
|---|---|
| `Cache_Watcher` | `fs_Cache_Tracking.directory` (OneToOne) |
| `parent_dir` | `DirectoryIndex.parent_directory` (self) |
| `FileIndex_entries` | `FileIndex.home_directory` |
| `Virtual_FileIndex` | `FileIndex.virtual_directory` |

---

### 3.2 `FileIndex` (`fileindex.py`)

The master index for all gallery files. One row per unique file location.

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `file_sha256` | `CharField` | SHA256 of file content; not unique (identical files share one value) |
| `unique_sha256` | `CharField(unique)` | SHA256 of `content + title-cased path`; the stable external identifier |
| `lastscan` | `FloatField` | Unix timestamp of last sync |
| `lastmod` | `FloatField` | mtime from OS `stat()` |
| `name` | `CharField` | Title-cased filename |
| `name_sort` | `NaturalSortField` | Auto-computed natural-sort key over `name` |
| `duration` | `BigIntegerField` | Video duration in milliseconds; `NULL` for non-video |
| `size` | `BigIntegerField` | File size in bytes |
| `home_directory` | `FK(DirectoryIndex, SET_NULL)` | Physical parent directory |
| `virtual_directory` | `FK(DirectoryIndex, SET_NULL)` | Target directory for `.link`/`.alias` shortcut files |
| `is_animated` | `BooleanField` | True for animated GIFs |
| `ignore` | `BooleanField` | Excluded from gallery display |
| `delete_pending` | `BooleanField(indexed)` | Soft-delete flag |
| `cover_image` | `BooleanField` | Marks this file as the directory's cover image |
| `filetype` | `FK(filetypes, ".none")` | Extension lookup; CASCADE-deletes if filetype removed |
| `is_generic_icon` | `BooleanField` | True if thumbnail is the filetype fallback icon |
| `new_ftnail` | `FK(ThumbnailFiles, SET_NULL)` | Link to generated thumbnail record |
| `ownership` | `OneToOne(Owners)` | Per-file ownership (permissions prototype) |

**Why two SHA256 fields?**  
`file_sha256` identifies identical content across multiple locations. `unique_sha256`
identifies a file at a specific path and is regenerable after a database rebuild
(unlike the old UUID primary key which was random and lost after deletion). All
external URLs use `unique_sha256`.

**Class-level caches:**

| Cache | Key | Purpose |
|---|---|---|
| `_encoding_cache` | text content | Avoids re-reading and re-decoding text/markdown files |
| `_alias_cache` | alias path | Caches resolved macOS `.alias` target paths |

---

### 3.3 `Owners` and `Favorites` (`models.py`)

Placeholder models for a future permissions/favourites system. `Owners` links a
`FileIndex` to a Django auth user via a `OneToOneField`. `Favorites` is currently
empty beyond its primary key.

---

### 3.4 `models.py` — Re-export Facade

`models.py` serves as a single import point for external code:

```python
from quickbbs.models import DirectoryIndex, FileIndex
```

It defines `Owners` and `Favorites` first (to satisfy `FileIndex`'s FK to `Owners`),
then imports and re-exports `DirectoryIndex`, `FileIndex`, and their associated caches.
All bottom-of-file imports are required to break the mutual dependency between
`directoryindex.py` and `fileindex.py`, which would cause `ImportError` if placed
at the top.

---

## 4. Filesystem Synchronization

### 4.1 `update_database_from_disk(directory)` (`directoryindex.py`)

Top-level sync entry point called by the gallery view and management commands.

```
update_database_from_disk(directory):
    1. return_disk_listing_sync(directory.fqpndirectory)
       → dict of {title_cased_name: DirEntry}
    2. directory.sync_subdirectories(fs_entries)
       → compare DB vs FS directory sets; add/update/delete
    3. directory.sync_files(fs_entries, bulk_size)
       → compare DB vs FS file sets; create/update/delete using bulk ops
    4. directory.update_cache_entry()
       → mark fs_Cache_Tracking invalidated=False with current timestamp
    Returns: updated DirectoryIndex instance
```

### 4.2 `sync_subdirectories(fs_entries)` (`directoryindex.py`)

Compares database directory records against the filesystem:

- **Update:** directories in both DB and FS with changed `mtime` → `bulk_update`
  with `SELECT FOR UPDATE (skip_locked)` to prevent concurrent modification
- **Create:** directories on FS not in DB → `add_directory()` per entry (no bulk
  create because `add_directory()` must recursively create parent chains)
- **Delete:** directories in DB not on FS → delete the rows; the CASCADE removes
  their `fs_Cache_Tracking` entries

New and deleted directory operations both call
`Cache_Storage.remove_from_cache_indexdirs()` on the parent to force the next page
request to rescan.

### 4.3 `sync_files(fs_entries, bulk_size)` (`directoryindex.py`)

Compares database `FileIndex` records against the filesystem:

1. **New files:** present on FS, absent in DB
   - `process_new_files()` builds `FileIndex(**metadata)` dicts
   - SHA256 computed in parallel via `_batch_compute_file_shas()` for batches above
     `SHA256_PARALLEL_THRESHOLD`
   - Written via `FileIndex.bulk_sync()`

2. **Updated files:** present in both, with changed `mtime` or `size`
   - Dynamic field selection: only appends `duration`, `file_sha256`, `unique_sha256`,
     `virtual_directory` to the bulk_update field list if _any_ record in the batch
     actually needs them — avoids writing unchanged columns

3. **Deleted files:** in DB but not on FS
   - Marked `delete_pending=True` rather than hard-deleted immediately

4. `FileIndex.bulk_sync()` executes delete/update/create in batched transactions and
   calls `clear_layout_cache_for_directories()` for every affected directory.

### 4.4 `FileIndex.from_filesystem(fs_entry, directory_id, precomputed_sha)` (`fileindex.py`)

Factory classmethod that converts a `Path` / `DirEntry` to a metadata dict suitable
for `FileIndex(**metadata)` or `bulk_create`. Special handling:

- **Link files** (`.link`, `.alias`): SHA computed immediately; calls
  `process_link_file()` to resolve the target `DirectoryIndex`
- **Animated GIFs**: calls `is_animated_gif()` via PIL
- **Videos**: duration populated by `_get_video_info()` (lazily imports AVFoundation
  on macOS or falls back to ffmpeg on other platforms)
- **Directories**: returns `None` — handled by `sync_subdirectories()`

---

## 5. Hashing Strategy (`common.py`)

### Two SHA256 values per file

| Hash | Input | Uniqueness | Used for |
|---|---|---|---|
| `file_sha256` | File content only | Not unique (same file in two places) | Deduplication, thumbnail sharing |
| `unique_sha256` | Content + title-cased FQFN | Unique per location | External URLs, gallery navigation |

### Directory SHA

`get_dir_sha(fqpn)` computes SHA256 of the normalized directory path string. Used as
the primary lookup key in `DirectoryIndex` and `fs_Cache_Tracking`. Cached in
`directory_sha_cache`.

### `_batch_compute_file_shas(file_paths)`

Uses a module-level singleton `ThreadPoolExecutor` (lazy-initialized, atexit cleanup)
to hash files in parallel when the batch exceeds `SHA256_PARALLEL_THRESHOLD`.

**Why `ThreadPoolExecutor` and not `ProcessPoolExecutor`?**  
`get_file_sha()` does not touch the Django ORM, so thread-safety is not a concern.
`ProcessPoolExecutor` cannot spawn child processes from daemon threads (the
`sync_to_async` worker pool in ASGI mode). The thread pool reuses workers across calls
to amortize thread-spawn overhead. Falls back to sequential processing on any executor
error.

---

## 6. Sorting (`common.py`)

Two sort matrices are defined to avoid unnecessary JOINs:

**`SORT_MATRIX`** — for mixed directory+file queries (joins to `filetypes` for
`is_dir` and `is_link` flags, so directories always sort first):

| Mode | Fields |
|---|---|
| 0 (name) | `-filetype__is_dir`, `-filetype__is_link`, `name_sort`, `lastmod` |
| 1 (date) | `-filetype__is_dir`, `-filetype__is_link`, `lastmod`, `name_sort` |
| 2 (name only) | `-filetype__is_dir`, `-filetype__is_link`, `name_sort` |

**`DIR_SORT_MATRIX`** — for directory-only queries (`dirs_in_dir()`). Omits the
`filetype__is_dir` / `filetype__is_link` fields because all directory rows have
`filetype=".dir"` — those fields are constant and the JOIN is wasted.

| Mode | Fields |
|---|---|
| 0 (name) | `name_sort`, `lastmod` |
| 1 (date) | `lastmod`, `name_sort` |
| 2 (name only) | `name_sort` |

---

## 7. Natural Sort (`natsort_model.py`)

`NaturalSortField` is a custom `CharField` that auto-computes its value from another
model field in `pre_save`. It:

1. Lowercases and strips the source string
2. Removes a leading "the " (article-insensitive sorting)
3. Zero-pads all digit sequences to 8 characters (`"photo2"` → `"photo00000002"`)

Used by both `DirectoryIndex.name_sort` (over `fqpndirectory`) and
`FileIndex.name_sort` (over `name`). Stored in the database so sorting requires no
Python-side post-processing — the database ORDER BY on `name_sort` produces natural
sort order.

---

## 8. Cache Architecture

### 8.1 Cache instances

All caches are created via `create_cache(maxsize, name, monitored)` from
`MonitoredCache.py`. When `CACHE_MONITORING = True`, a `MonitoredLRUCache` is
returned (tracks hits/misses/hit-rate); otherwise a plain `cachetools.LRUCache`.

| Cache | Location | Key | Invalidated by |
|---|---|---|---|
| `directoryindex_cache` | `directoryindex.py` | `hashkey(sha256)` | `cache_watcher`, `invalidate_thumb()`, `delete_directory_record()` |
| `get_view_url_cache` | `directoryindex.py` | `DirectoryIndex` instance | Never (URLs are stable) |
| `distinct_files_cache` | `cache_registry.py` | `hashkey(directory_instance, sort)` | `clear_layout_cache_for_directories()` |
| `layout_manager_cache` | `cache_registry.py` | `hashkey(page, dir.pk, sort, show_dupes)` | `clear_layout_cache_for_directories()` |
| `fileindex_cache` | `fileindex.py` | `hashkey(sha, unique, select_related)` | Never evicted explicitly (LRU) |
| `fileindex_download_cache` | `fileindex.py` | `hashkey(sha, unique, select_related)` | Never evicted explicitly (LRU) |
| `normalized_strings_cache` | `common.py` | input string | Never (pure function) |
| `directory_sha_cache` | `common.py` | directory path | Never (pure function) |
| `normalized_paths_cache` | `common.py` | directory path | Never (pure function) |

### 8.2 `cache_registry.py` — Central invalidation

`clear_layout_cache_for_directories(directory_ids: set[int])` is the single shared
function for flushing both `layout_manager_cache` and `distinct_files_cache`. Used by:

- `cache_watcher` on filesystem change events
- `FileIndex.bulk_sync()` after add/update/delete
- `generate_missing_thumbnails` task after new thumbnails are written

**Why the registry lives in `quickbbs` (not `frontend`)?**  
Cache objects and their invalidation function are imported by `cache_watcher`,
`thumbnails`, `frontend`, and `quickbbs` itself. Placing them in `frontend` would
force `cache_watcher` to import `frontend`, creating a circular dependency.

**`distinct_files_cache` invalidation uses stub instances:**  
The key for this cache is `hashkey(directory_instance, sort)`. Django model instances
hash by PK, so a `DirectoryIndex(pk=pk)` stub with no fields loaded matches the
cached entry for the real object. This avoids loading full objects just to construct
invalidation keys.

**`layout_manager_cache` invalidation scans keys:**  
Key format is `hashkey(page_number, directory_pk, sort, show_duplicates)`. Page number
is unbounded, so keys cannot be constructed for invalidation — the registry scans all
keys and removes those where `key[1] in directory_ids`.

### 8.3 `MonitoredLRUCache` (`MonitoredCache.py`)

Subclass of `cachetools.LRUCache` that overrides `__getitem__` to increment `hits` or
`misses`. Adds `hit_rate` property (0–100%) and `stats()` / `reset_stats()` methods.

Performance interpretation guidance (from module docstring):

| Hit rate | Action |
|---|---|
| > 80% | Cache size is adequate |
| 60–80% | Consider increasing cache size |
| < 60% | Increase cache size |

---

## 9. Background Tasks (`tasks.py`)

All tasks use the `django-dbtasks` backend (`@task()` decorator from `django.tasks`).
Executed by a separate `python manage.py taskrunner` process.

### `generate_missing_thumbnails(files_needing_thumbnails, directory_pk, batch_size)`

Batch thumbnail generation with pre-filtering and bulk write.

**Flow:**

```
1. Pre-filter: query ThumbnailFiles for SHAs that already have small_thumb
   → skip these, mark as success (avoids advisory lock + re-processing)
2. For each remaining SHA:
   a. ThumbnailFiles.get_or_create_thumbnail_record(suppress_save=True)
   b. Collect modified ThumbnailFiles objects
   c. Handle OrphanedThumbnail / OrphanedFileIndex exceptions → delete record
3. bulk_update(thumbnails_to_update, ["small_thumb", "medium_thumb", "large_thumb"])
4. clear_layout_cache_for_directories({directory_pk})
```

**Priority convention:**
- `priority=50` — web-request-triggered thumbnail generation
- `priority=0` — bulk maintenance (`--add_thumbnails` management command)

Higher priority number = processed first by `taskrunner`.

### `daily_cleanup_finished_jobs()`

Deletes `ScheduledTask` records older than `TASK_RETAIN_DAYS` (configurable) where
`status` is `SUCCESSFUL` or `FAILED`. Safety net for records that escaped the
runner's own `delete_tasks()` loop (e.g., completed while the runner was offline).
Registered as a periodic task to run daily at midnight via `TASKS` settings.

### `snapshot_cache_statistics()`

Not a `@task` — a regular function called synchronously from `new_viewgallery()` on
each gallery request when `CACHE_MONITORING = True`.

Reads hit/miss counters from all `MonitoredLRUCache` instances registered in
`_MONITORED_CACHE_LOCATIONS` (14 caches across 6 modules). Upserts one
`CacheStatisticsTracking` row per cache. Skips writes for caches whose stats haven't
changed since the last snapshot. **Must be called from the web server process** — a
separate `taskrunner` process would see freshly-initialized (zero-count) caches.

---

## 10. `DirectoryIndex` Methods Reference

| Method | Type | Description |
|---|---|---|
| `add_directory(fqpn)` | `@staticmethod` | `update_or_create` with stat + recursive parent creation. Returns `(False, None)` if path doesn't exist on disk. |
| `search_for_directory_by_sha(sha)` | `@staticmethod @cached` | Primary lookup, cached in `directoryindex_cache`. Always loads full `DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE_PARENT` relations. |
| `search_for_directory(fqpn)` | `@staticmethod` | Delegates to `search_for_directory_by_sha` — not cached independently to prevent duplicate cache entries. |
| `get_all_parent_shas(sha_list, select_related)` | `@staticmethod` | Iterative batch parent traversal (O(depth) queries). Expands input SHAs to include all ancestors. |
| `delete_directory_record(index_dir, cache_only)` | `@staticmethod` | Removes from `fs_Cache_Tracking` cache; optionally hard-deletes the row. |
| `files_in_dir(sort, distinct, ...)` | instance | Returns `FileIndex` queryset for this directory. `distinct=True` uses PostgreSQL `DISTINCT ON(file_sha256)` + re-sort query to match gallery collation. |
| `dirs_in_dir(sort, fields_only, ...)` | instance | Returns `DirectoryIndex` queryset for subdirectories. `fields_only` skips joins for lightweight path/ID queries. |
| `get_distinct_file_shas(sort)` | instance `@cached` | Returns list of `unique_sha256` strings, cached in `distinct_files_cache`. 94% less memory than caching full objects. |
| `get_cover_image()` | instance | Finds cover image by priority filename matching (`DIRECTORY_COVER_NAMES`) or falls back to first thumbnailable file. |
| `get_prev_next_siblings(sort_order)` | instance | Returns `(prev_dict, next_dict)` for sibling navigation in parent directory. |
| `invalidate_thumb()` | instance | Bulk-updates `thumbnail=NULL`, pops from `directoryindex_cache`. |
| `is_cached` | `@property` | Checks `Cache_Watcher.invalidated` via the preloaded OneToOne relation. |
| `name` | `@property` | Last path component of `fqpndirectory`. |
| `get_view_url()` | instance `@cached` | Constructs the URL-encoded gallery browse URL. Cached in `get_view_url_cache`. |
| `get_thumbnail_url(size)` | instance | Returns `thumbnail2_dir` URL with SHA arg. |
| `numdirs` / `numfiles` | `@property` | Return `None` — stub for template API compatibility with `FileIndex`. |

**`files_in_dir(distinct=True)` — two-query deduplication:**  
PostgreSQL `DISTINCT ON` requires `file_sha256` as the first `ORDER BY` field, which
disrupts user sort order. A second query re-sorts by `unique_sha256` PKs using the
user's requested sort. This ensures navigation order in the item viewer matches the
gallery listing — previously, Python re-sorting used ASCII collation (`'-' < '_'`)
while PostgreSQL uses `en_US.UTF-8` (`'_' < '-'`), causing navigation mismatches.

---

## 11. `FileIndex` Methods Reference

| Method | Type | Description |
|---|---|---|
| `get_by_sha256(sha, unique, select_related)` | `@staticmethod` | Manual cache (not `@cached`) — never caches `None` since a missing record may appear shortly after (during thumbnail creation). |
| `get_by_sha256_for_download(sha, unique, sr)` | `@staticmethod @cached` | Download-optimized: `.only("name", "filetype__mimetype", ...)`. Separate cache from `fileindex_cache`. |
| `from_filesystem(fs_entry, dir_id, precomputed_sha)` | `@classmethod` | Factory: builds metadata dict for bulk_create. Handles links, GIF animation, video duration. |
| `bulk_sync(to_update, to_create, to_delete, bulk_size)` | `@classmethod` | Batched delete→update→create in transactions. Collects affected directory IDs before each operation for cache clearing. |
| `link_to_thumbnail(file_sha256, thumbnail)` | `@classmethod` | Links all `FileIndex` rows with matching `file_sha256` to a `ThumbnailFiles` record. Only records with `new_ftnail=NULL` are updated (prevents overwriting existing links). |
| `set_generic_icon_for_sha(sha, is_generic)` | `@classmethod` | Shared setter for `is_generic_icon` flag across all copies of a file. Clears layout cache for affected directories. |
| `process_link_file(fs_entry, filetype, filename)` | `@staticmethod` | Parses `.link` filename encoding or resolves macOS `.alias`; finds/creates target `DirectoryIndex`. |
| `is_animated_gif(fs_entry)` | `@staticmethod` | Opens file with PIL, checks `img.is_animated`. |
| `find_files_without_sha(start_path)` | `@classmethod` | QuerySet of rows with `file_sha256=NULL` for maintenance commands. |
| `find_broken_link_files(start_path)` | `@classmethod` | QuerySet of link files with `virtual_directory=NULL`. |
| `fqpndirectory` | `@property` | Raises `ValueError` for orphaned records (no `home_directory`). |
| `full_filepathname` | `@property` | `fqpndirectory + name`. |

**Link file format (`.link`):**  
Filename encodes the target path: `<display_name>*<path_with_slashes_as_underscores>`
e.g., `Paris Trip*albums__2024__paris.link` → `/albums/2024/paris/`.

**`get_by_sha256` — why not `@cached`?**  
The `@cached` decorator from `cachetools` stores `None` results. A `None` return means
"record not found", but a thumbnail generation task may create the record moments
later. A cached `None` would mask it until LRU eviction. The manual pattern
(`cache.get()` → DB → `cache[key] = result`) explicitly skips caching `None`.

---

## 12. URL Routing (`urls.py`)

| URL pattern | View | Name |
|---|---|---|
| `/albums/<path>/` | `frontend.views.new_viewgallery` | `directories` |
| `/view_item/<sha256>/` | `frontend.views.htmx_view_item` | `view_item` |
| `/download_file/` | `frontend.views.download_file` | `download_file` |
| `/search/` | `frontend.views.search_viewresults` | `search_viewresults` |
| `/thumbnail2_file/<sha256>` | `thumbnails.views.thumbnail2_file` | `thumbnail2_file` |
| `/thumbnail2_directory/<dir_sha256>` | `thumbnails.views.thumbnail2_dir` | `thumbnail2_dir` |
| `/resources/<path>` | `frontend.serve_up.static_or_resources` | `resources` |
| `/static/<path>` | `frontend.serve_up.static_or_resources` | `static` |
| `/reports/duplicate_files.html` | `frontend.report_views.duplicate_files_report` | `duplicate_files_report` |
| `/preferences/toggle-duplicates/` | `user_preferences.views.toggle_show_duplicates` | `toggle_show_duplicates` |
| `/accounts/` | `allauth.urls` | — |
| `/grappelli/` | `grappelli.urls` | — |
| `/Admin/` | `django.contrib.admin` | — |
| `/` | `RedirectView → /albums` | `home` |

---

## 13. Circular Dependency Map

The models form a mutual dependency cycle that is handled with deferred imports:

```
models.py
  └── imports from directoryindex.py (bottom of file)
  └── imports from fileindex.py     (bottom of file)

directoryindex.py
  └── imports from fileindex.py     (FILEINDEX_SR_FILETYPE — bottom of file)
  └── imports cache_watcher.models  (deferred, inside methods)

fileindex.py
  └── imports from models.py        (Owners — bottom of file, after class defs)
  └── imports from directoryindex.py (deferred, inside methods)
  └── imports cache_registry.py     (deferred, inside methods)
```

**Rule:** No cross-model import at module top level. All `DirectoryIndex`↔`FileIndex`
references use `TYPE_CHECKING` blocks for type annotations and deferred
`import-inside-function` for runtime use.

---

## 14. Module Structure Summary

```
quickbbs/
├── __init__.py            # Empty
├── asgi.py                # ASGI entry point (uvicorn/hypercorn)
├── wsgi.py                # WSGI entry point (gunicorn)
├── settings.py            # Django settings (imports from quickbbs_settings.py)
├── quickbbs_settings.py   # Gallery-specific settings (paths, cache sizes, file types, FTYPES)
├── secrets.py             # SECRET_KEY and credentials (not committed to repo)
├── urls.py                # Project URL configuration
├── admin.py               # Django admin registrations
│
├── common.py              # Hashing, path normalization, sort matrices, thread pool
├── MonitoredCache.py      # MonitoredLRUCache + create_cache() factory
├── cache_registry.py      # distinct_files_cache, layout_manager_cache, clear_layout_cache_for_directories()
├── natsort_model.py       # NaturalSortField custom Django model field
│
├── models.py              # Re-export facade: Owners, Favorites, DirectoryIndex, FileIndex
├── directoryindex.py      # DirectoryIndex model + sync methods + select_related constants
├── fileindex.py           # FileIndex model + file metadata + link resolution + bulk ops
│
├── tasks.py               # Background tasks: generate_missing_thumbnails, daily_cleanup, snapshot_cache_statistics
│
├── pdf_repair.py          # PDF repair utilities (used by management commands)
├── 3rd_party_libraries.py # Third-party library initialization/configuration
└── natsort_model.py       # NaturalSortField
```
