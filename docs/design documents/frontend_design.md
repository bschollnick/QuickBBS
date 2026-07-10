# frontend — Design Document

**Version:** 4.00  
**Author:** Benjamin Schollnick  
**Last Updated:** 2026-07-10

---

## 1. Purpose

`frontend` is the Django application that handles all HTTP request/response logic for
the QuickBBS gallery. It owns:

- **Views** — gallery listing, item viewer, search, file download, and administrative
  reports
- **Layout management** — database-level pagination of directory/file content
- **File serving** — sync and async HTTP file delivery, byte-range streaming for video
- **Directory scanning** — filtered filesystem directory listings
- **Path utilities** — filesystem-to-web-path conversion and breadcrumb generation

The app is fully async (ASGI) at the view layer, with sync helper functions wrapped
via `sync_to_async` at all DB/filesystem boundaries.

---

## 2. High-Level Architecture

```
HTTP Request
    │
    ▼
Django URL router
    │
    ├── new_viewgallery()        Gallery directory listing
    ├── htmx_view_item()         Single-item viewer (HTMX)
    ├── search_viewresults()     Gallery search
    ├── download_file()          File download / inline video
    └── duplicate_files_report() Admin report
    │
    ▼
views.py  (async ASGI views)
    │
    ├── _find_directory()        DB lookup + create if missing + cache invalidation
    ├── _determine_template()    HTMX partial vs full-page template selection
    ├── _create_base_context()   Shared context dict for all views
    │
    ├── managers.py
    │   ├── layout_manager()     Paginated dir+file SHA lists (cached)
    │   └── build_context_info() Single-item navigation context (cached lookup)
    │
    ├── file_listings.py
    │   └── return_disk_listing()  Filtered os.scandir → dict
    │
    ├── utilities.py
    │   ├── convert_to_webpath()   Filesystem path → web-relative path (cached)
    │   └── return_breadcrumbs()   URI → breadcrumb list (cached)
    │
    └── serve_up.py
        ├── send_file_response()           FileResponse / RangedFileResponse
        ├── build_async_ranged_response()  Async byte-range streaming for video
        └── static_or_resources()         Static/resource file serving
```

---

## 3. Component Reference

### 3.1 `apps.py` — `FrontendConfig`

`AppConfig` subclass. `ready()` calls `configure_pil()` (from `quickbbs.settings`) to
set PIL/Pillow global options before any image operations can occur.

---

### 3.2 `views.py` — Request Handlers

All views are `async def` decorated with `@vary_on_headers("HX-Request")` where HTMX
partial responses are supported.

---

#### `new_viewgallery(request)`

Primary gallery view. Renders a paginated list of subdirectories and files for a
given URL path.

**Request flow:**

```
1. Decode and normalize request.path
2. _get_show_duplicates_preference() — user pref from TTL cache or DB
3. _determine_template() — partial vs full page based on HX-Request header
4. _find_directory() — DB lookup/create/validate (sync_to_async)
5. update_database_from_disk() — sync directory contents with filesystem
6. _create_base_context() — shared base dict
7. async_layout_manager() — paginated SHA lists (cached)
8. dirs_in_dir() filtered by layout SHA list — annotated with file/dir counts
9. files_in_dir() filtered by layout SHA list — split into files + links
10. _check_and_enqueue_missing_thumbnails() — enqueue thumbnail tasks
11. async_render() with Jinja2 template
12. Set Cache-Control: private for authenticated users
13. snapshot_cache_statistics() if CACHE_MONITORING enabled
```

**Item ordering on page:** directories first, then symlink/shortcut items, then files.

**Thumbnail enqueueing:** computed _after_ the layout cache lookup so thumbnail
generation does not invalidate the cached layout data. Priority 50 (vs priority 0
for bulk maintenance tasks).

---

#### `htmx_view_item(request, sha256)`

Single-item viewer supporting HTMX navigation (previous/next/first/last).

**Request flow:**

```
1. _get_show_duplicates_preference()
2. _determine_template() — item partial vs full page
3. async_build_context_info() — navigation context from managers.py
4. _check_and_enqueue_missing_thumbnails() — warms thumbnails for the item's directory
5. async_render() with Jinja2 template
```

Uses the `DirectoryIndex` cached in `build_context_info` context rather than
re-fetching it, avoiding a redundant DB round-trip.

---

#### `search_viewresults(request)`

Searches both `DirectoryIndex.fqpndirectory` and `FileIndex.name` using a
separator-agnostic regex pattern, with DB-level pagination.

**Two-phase query pattern:**

1. `_get_paginated_search_results()` — COUNT total items; compute
   `calculate_page_bounds()`; fetch only SHA values for the current page using
   LIMIT/OFFSET slices.
2. Hydrate full objects for this page only via `__in` lookups with `prefetch_related`
   and `annotate` (file/dir counts).

This mirrors the `layout_manager` pattern: only current-page data is ever loaded.

**Cache behaviour:** Response headers force `no-store` to prevent HTMX history caching
from showing stale results on subsequent searches.

**`create_search_regex_pattern(text)`** converts spaces, underscores, and dashes to
`[\s_-]+` for separator-agnostic matching. Falls back to `icontains` if the database
rejects the regex. Pattern is capped at 500 characters to prevent ReDoS.

---

#### `download_file(request)`

Serves a file by `unique_sha256` passed as `?usha=`. Calls
`FileIndex.async_inline_sendfile()` which chooses between `RangedFileResponse` (for
videos) and a plain `FileResponse`. Handles `asyncio.CancelledError` without logging
(expected for client disconnections).

---

#### `duplicate_files_report(request)`

Administrative report. Two queries:

1. `file_sha256` values with `COUNT > 5` ordered by count descending.
2. All `FileIndex` rows matching those SHAs with `home_directory` joined, grouped by
   SHA into a structured list.

Rendered with Jinja2 template `reports/duplicate_files.jinja`.

---

#### Helper functions in `views.py`

| Function | Description |
|---|---|
| `_determine_template(request, template_type)` | Returns partial or complete Jinja2 template path based on `request.htmx.boosted` and `HX-Request` header |
| `_create_base_context(request)` | Builds shared context dict (debug flag, sort, page, image sizes, user, empty placeholder lists) |
| `_find_directory(paths)` | Looks up `DirectoryIndex` by SHA; creates if missing via `add_directory()`; validates physical path still exists; clears parent cache on creation |
| `_check_and_enqueue_missing_thumbnails(directory, sort, batch_limit)` | Gets files needing thumbnails, enqueues `generate_missing_thumbnails` task at priority 50 |
| `get_sort_param(request)` | Reads `?sort=` query param; validates against `SORT_MATRIX`; returns `DEFAULT_SORT_ORDER` on invalid input |
| `_get_show_duplicates_preference(request)` | Reads `UserPreferences.show_duplicates`; caches in `_user_pref_cache` TTL cache keyed on `user.pk` |
| `async_render(request, template, context)` | `sync_to_async` wrapper around Django's `render()` |

**`_user_pref_cache`** is a module-level `TTLCache(maxsize=USER_PREF_CACHE_SIZE,
ttl=USER_PREF_CACHE_TTL)`. It is explicitly cleared by
`user_preferences/views.toggle_show_duplicates()` when the user changes their
preference.

---

### 3.3 `managers.py` — Layout and Context Building

#### `layout_manager(page_number, directory, sort_ordering, show_duplicates)`

Computes pagination data for a gallery page. Cached via `layout_manager_cache`
(from `quickbbs.cache_registry`); keyed on `(page_number, directory.pk,
sort_ordering, show_duplicates)`.

**Why `directory.pk` and not the `DirectoryIndex` object?**  
Cache invalidation in `cache_watcher` uses integer comparisons on PK values to find
entries to evict. Using the full ORM object would require identity-based comparisons,
which are fragile across different query paths that load the same row.

**Pagination algorithm:**

```
dirs_count = COUNT(subdirectories)
files_count = COUNT(distinct file SHAs) OR COUNT(all files) [based on show_duplicates]
total_items = dirs_count + files_count
total_pages = ceil(total_items / GALLERY_ITEMS_PER_PAGE)

calculate_page_bounds(page, GALLERY_ITEMS_PER_PAGE, dirs_count):
  → dirs_slice: (start, end) into the directory queryset
  → files_slice: (start, end) into the file list/queryset

Fetch:
  - directory SHAs via queryset LIMIT/OFFSET (database paging)
  - file SHAs via distinct list slice (list paging, no extra DB query) OR queryset LIMIT/OFFSET
```

**`files_needing_thumbnails` is not included in the output.** It is computed
separately by the caller so thumbnail generation does not invalidate the cached layout.

**`page_locale`** — the page number within the parent directory where _this_
directory would appear (used for the "back" link). Computed from sibling order.

**`async_layout_manager`** is a `sync_to_async` wrapper for ASGI views.

---

#### `build_context_info(unique_file_sha256, sort_order_value, show_duplicates)`

Builds the complete context dict for the single-item viewer. Constructs navigation
data (first/last/next/previous SHA, current position, total count).

**Duplicate-aware navigation:**

- `show_duplicates=False` (default): uses `directory.get_distinct_file_shas()`, a
  cached list of unique SHA256 values. Navigation position is an `O(n)` list search
  on the cached list.
- `show_duplicates=True`: uses live queryset with a multi-field `Q` object to count
  items that sort before the current entry — more accurate but heavier.

**`async_build_context_info`** — async wrapper that extracts `?sort=` from the
request before delegating to the sync function.

---

#### `calculate_page_bounds(page_number, chunk_size, dirs_count)`

Pure function (no I/O). Given a page number and the total directory count, returns
slice boundaries for directories and files:

- Pages that straddle the dirs/files boundary have both a `dirs_slice` and a
  `files_slice`.
- Pure-directory pages have only `dirs_slice`.
- Pure-file pages have only `files_slice` (with offset adjusted by `dirs_count`).

Returns `None` for a slice when that type has no items on the current page.

---

#### `_get_files_needing_thumbnails(directory, sort_ordering)`

Thin delegation to `ThumbnailFiles.get_files_needing_thumbnail_shas()`. Separated from
`layout_manager` to keep thumbnail state out of the cached layout dict.

---

### 3.4 `serve_up.py` — File Delivery

#### `send_file_response(filename, content_to_send, mtype, attachment, expiration, request)`

Primary file delivery function used throughout the codebase (including
`filetypes.models.send_thumbnail` and `FileIndex`).

- Without `request`: returns a plain `FileResponse`.
- With `request`: returns a `RangedFileResponse` (byte-range support for video seek).
- Always sets `Cache-Control: public, max-age={expiration}`.
- Always strips `ETag` header to avoid `ConditionalGetMiddleware` overhead on large
  files (computing ETags requires reading the full content).
- Filename is sanitized via `sanitize_filename_for_http()` before being placed in
  `Content-Disposition`.

**Note on file handle lifecycle:** callers must _not_ use context managers for file
handles passed to this function — Django's `FileResponse` closes the handle after
streaming.

---

#### `build_async_ranged_response(request, path, file_size, content_type, filename, expiration)`

Used by `FileIndex.async_inline_sendfile()` for ASGI video streaming. Returns a
`StreamingHttpResponse` backed by `_async_file_range_iterator` (an `aiofiles` async
generator that yields 64 KB chunks).

Supports both full-file (`200 OK`) and byte-range (`206 Partial Content`) requests.
The Range header is parsed by `_parse_range_header()` which handles suffix form
(`bytes=-N`) but rejects multipart ranges (browsers never send them for video).

---

#### `SizedFileWrapper`

Wraps an open file handle and pre-populates `.size` from `os.fstat`. Without this,
`RangedFileResponse` / `RangedFileReader` falls back to `len(f.read())` — reading the
entire file into memory to measure its size.

---

#### `static_or_resources(request, pathstr)` / `async_static_or_resources`

Serves files from `settings.STATIC_ROOT` first, then `settings.RESOURCES_PATH`.
The async version reads the full file with `aiofiles` and wraps it in `BytesIO`
before constructing the `FileResponse`.

---

#### `sanitize_filename_for_http(filename)`

Strips control characters (0x00–0x1F, 0x7F), angle brackets, and replaces semicolons
with underscores to prevent HTTP header injection in `Content-Disposition`. Uses a
pre-computed `str.maketrans` table (faster than regex). Returns `"download.bin"` if
the result is empty.

---

### 3.5 `file_listings.py` — Directory Scanner

#### `return_disk_listing(fqpn)` / `return_disk_listing_sync(fqpn)`

Scans a filesystem directory and returns `(success: bool, data: dict)` where `data`
maps title-cased filename → `os.DirEntry`.

**Filtering rules (from settings):**

| Setting | Effect |
|---|---|
| `EXTENSIONS_TO_IGNORE` | Skip files with these extensions |
| `FILES_TO_IGNORE` | Skip files with these exact names (lowercase) |
| `IGNORE_DOT_FILES` | Skip any file/dir starting with `.` |
| `filetypes.filetype_exists_by_ext` | Skip files with unrecognised extensions |

Directories are assigned the synthetic extension `.dir`.

**Async version** calls `asyncio.to_thread(return_disk_listing_sync, fqpn)` — runs
the blocking `Path.iterdir()` in a thread pool. `return_disk_listing_async` is an
alias for backward compatibility.

---

### 3.6 `utilities.py` — Path Helpers

#### `convert_to_webpath(full_path, directory=None)`

Strips `ALBUMS_PATH` (plus optional `directory` suffix) from a filesystem path to
produce a web-relative path. Raises `ValueError` if the prefix is not found.

Cached in `webpaths_cache` (a `MonitoredLRUCache` from `quickbbs.MonitoredCache`,
size from `settings.WEBPATHS_CACHE_SIZE`).

#### `return_breadcrumbs(uri_path)`

Splits a URI path on `/` and builds a list of `{"name": part, "url": cumulative_path}`
dicts. URL-encodes each path component via `urllib.parse.quote`. Cached in
`breadcrumbs_cache` (size from `settings.BREADCRUMBS_CACHE_SIZE`).

#### `ensures_endswith(string, value)`

Adds `value` as a suffix if it is not already present. Used to normalize directory
paths to ensure trailing slashes.

---

### 3.7 `constants.py`

Defines a single regex substitution map (`replacements` + `regex`) for cleaning up
strings. Used to sanitize path components with characters invalid in filenames
(`?`, `/`, `:`, `#`).

---

### 3.8 `report_views.py` — Administrative Reports

#### `duplicate_files_report(request)`

Async view that renders `reports/duplicate_files.jinja` with a summary of highly
duplicated files (SHA256 appearing more than 5 times in `FileIndex`).

Uses two queries: one aggregate to find SHA values and counts, one join to fetch
file locations. Groups are ordered by count descending and include the directory
path for each copy of the file.

---

## 4. ASGI / WSGI Strategy

All views are `async def`. Synchronous operations (DB queries, filesystem access) are
wrapped with `sync_to_async()` at the call site. The pattern throughout:

```python
result = await sync_to_async(some_sync_function)(args)
```

For file I/O in async views, `aiofiles` is used directly.

**`async_render`** is a local wrapper that applies `sync_to_async` to Django's `render()`
— defined separately in both `views.py` and `report_views.py` since they can't share
a module-level import without circular dependency risk.

---

## 5. Caching Architecture

| Cache | Location | Key | Backed by | Invalidated by |
|---|---|---|---|---|
| `layout_manager_cache` | `quickbbs.cache_registry` | `(page, dir.pk, sort, show_dupes)` | `MonitoredLRUCache` | `cache_watcher` on filesystem change |
| `webpaths_cache` | `utilities.py` module level | `(full_path, directory)` | `MonitoredLRUCache` | Never (paths are stable) |
| `breadcrumbs_cache` | `utilities.py` module level | `uri_path` | `MonitoredLRUCache` | Never (paths are stable) |
| `_user_pref_cache` | `views.py` module level | `user.pk` | `TTLCache` | `toggle_show_duplicates()` + TTL expiry |
| `distinct_files_cache` | `quickbbs.directoryindex` | `(directory, sort)` | `MonitoredLRUCache` | `cache_watcher` on filesystem change |

`layout_manager` results do **not** include thumbnail state so that thumbnail
generation does not force a cache eviction.

---

## 6. Template Selection

`_determine_template(request, template_type)` returns:

- **Partial template** (`*_partial.jinja`): when `request.htmx.boosted` is `True`
  and `request.htmx.current_url` is set and `?newwin=` is not set. Used for
  HTMX in-page navigation (replaces only the content div).
- **Complete template** (`*_complete.jinja`): for full-page loads, new tabs, and
  direct URL access.

| `template_type` | Partial | Complete |
|---|---|---|
| `gallery` | `frontend/gallery/gallery_listing_partial.jinja` | `frontend/gallery/gallery_listing_complete.jinja` |
| `search` | `frontend/search/search_listings_partial.jinja` | `frontend/search/search_listings_complete.jinja` |
| `item` | `frontend/item/gallery_htmx_partial.jinja` | `frontend/item/gallery_htmx_complete.jinja` |

---

## 7. Directory Discovery Flow

When a request arrives for a URL that doesn't yet exist in `DirectoryIndex`:

```
_find_directory(paths)
    ├── search_for_directory_by_sha(sha)  →  not found
    ├── add_directory(dirpath)
    │   ├── physical path validation
    │   ├── parent directory creation (recursive)
    │   └── DB record creation
    ├── Cache_Storage.remove_from_cache_indexdirs(parent)  ← invalidate parent listing
    ├── search_for_directory_by_sha(sha)  ← reload with prefetches
    └── update_database_from_disk(directory)  ← populate file entries
```

If the physical directory is missing at the race-condition check (was in DB but deleted
from disk), the parent and directory caches are both invalidated, `update_database_from_disk`
is called to clean up, and `DirectoryNotFoundError` is raised.

---

## 8. Module Structure Summary

```
frontend/
├── __init__.py             # Version metadata only
├── apps.py                 # FrontendConfig: configure_pil() on ready()
├── views.py                # All HTTP views (async ASGI)
├── managers.py             # layout_manager(), build_context_info() + async wrappers
├── serve_up.py             # File delivery: sync FileResponse, async ranged streaming
├── file_listings.py        # Directory scanner: return_disk_listing()
├── utilities.py            # convert_to_webpath(), return_breadcrumbs(), ensures_endswith()
├── constants.py            # Filename sanitization regex
├── report_views.py         # Admin reports: duplicate_files_report()
├── organize_by_person_name.py  # Standalone utility script (not imported by app)
├── file_mover_colors3.py   # Standalone utility: copy/move color-tagged files; --mirror removes target orphans
├── tests/
│   └── test_utilities.py
└── prototypes/             # Experimental code (not imported by app)
    ├── pdf_utilities.py
    ├── nnhash.py
    └── subquery_test.py
```
