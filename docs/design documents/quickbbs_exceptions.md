# quickbbs — Exception Taxonomy

**Companion to:** [`quickbbs_app_design.md`](quickbbs_app_design.md)
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

---

## What this is

`quickbbs` defines no custom exception classes of its own. This file documents where
it raises and catches standard/Django exceptions as a deliberate part of its
error-handling design, and where it consumes exceptions defined by
[`thumbnails`](thumbnails_exceptions.md). Verified directly against
`quickbbs/quickbbs/{directoryindex,fileindex,tasks,settings,apps,common,asgi}.py` and
`quickbbs/quickbbs/middleware/filter_ips.py`.

---

## Contract guards: `ValueError` and `TypeError` raised, never caught by callers

Several methods on
[`DirectoryIndex`](quickbbs_app_design.md#42-directoryindexpy--directoryindex) and
[`FileIndex`](quickbbs_app_design.md#43-fileindexpy--fileindex) raise `ValueError` when
a required keyword argument is missing — this is a programmer-error guard, not a
runtime-data problem, and nothing in the codebase catches it:

- `DirectoryIndex.get_all_parent_shas`, `.files_in_dir`, `.dirs_in_dir` — raise
  `ValueError("select_related parameter is required")` and/or
  `ValueError("prefetch_related parameter is required")` when the caller omits either
  argument (`directoryindex.py:649, 988, 990, 1075, 1271, 1273`).
- `FileIndex.return_by_sha256_list`, `.get_by_sha256`, `.get_by_sha256_for_download` —
  same pattern, `ValueError("select_related parameter is required")`
  (`fileindex.py:348, 372, 413`).
- `FileIndex.fqpndirectory` (property) — raises `ValueError` when `home_directory` is
  `None`, meaning the record is orphaned (`fileindex.py:254`).
- `FileIndex.check_for_updates` — raises `TypeError` (not `ValueError`) when `fs_stat`
  is a value other than a stat result or `None` (`fileindex.py:1178`).
- `FileIndex.resolve_macos_alias` — raises `ValueError` (`from error`) when macOS
  bookmark data can't be encoded or decoded (`fileindex.py:1421, 1427`).

## `Http404`: converting a filesystem miss into a proper 404

`FileIndex.inline_sendfile` and `FileIndex.async_inline_sendfile` both catch
`FileNotFoundError` around their file-open call and re-raise as `Http404 from exc`
(`fileindex.py:1063, 1085, 1122`) — this is what lets a file that's vanished from disk
between the database record being read and the file being opened surface as a normal
404 response rather than an unhandled 500. Both methods are the terminal file-serving
step behind [`frontend`](frontend_exceptions.md)'s `download_file` view.

## `DatabaseError`: log and return a safe default, never propagate

Every cache-invalidation method on `DirectoryIndex` wraps its write in
`try`/`except DatabaseError` (sometimes combined with `AttributeError`) and returns a
safe default rather than letting the error reach its caller:

- `cache_valid_for_sha` — `except DatabaseError` → logs, returns `False`
  (`directoryindex.py:476`).
- `invalidate_cache` — `except (DatabaseError, AttributeError)` → logs, returns
  `False` (`directoryindex.py:505`).
- `invalidate_cache_by_sha` — same pattern (`directoryindex.py:528`).
- `invalidate_all_caches` — `except DatabaseError` → logs, returns `0`
  (`directoryindex.py:619`).

The same pattern appears outside `DirectoryIndex`: `quickbbs/tasks.py`'s vacuum task
catches `DatabaseError` and logs-and-continues; `quickbbs/asgi.py`'s startup DB-pool
pre-warm does the same at ASGI lifespan startup.

## `PermissionDenied`: currently unreachable in production

`quickbbs/middleware/filter_ips.py`'s `FilterHostMiddleware` raises
`django.core.exceptions.PermissionDenied` when a request's `Host` header isn't a
`.local` name, a configured allowed host, or otherwise trusted (`filter_ips.py:37`) —
Django's exception middleware would convert this to a 403. **This middleware is not
currently registered in `settings.MIDDLEWARE`**, so this raise site exists in the
codebase but is not part of any request's actual code path today.

## Other standard exceptions used meaningfully

- `KeyError` — `MonitoredCache.__getitem__` catches `KeyError` only to increment a
  miss counter, then re-raises it unchanged (bare `raise`) — `dict.__getitem__`'s
  normal contract is preserved for callers.
- `ImportError` — raised in `quickbbs/settings.py` when `secrets.py` is missing,
  wrapping the original with a setup-instruction message (`raise ImportError(...) from
  e`); this fails Django startup outright, by design.
- `CommandError` (django.core.management.base) — raised in
  `management/commands/scan.py` for an invalid `--start` path (outside the albums
  tree, doesn't exist, or isn't a directory) — the standard way a Django management
  command reports a usage error to the CLI.
- Broad, deliberately unnarrowed `except Exception` — a handful of sites carry a
  `TODO` comment acknowledging the catch is wider than ideal: the SSL-certificate
  startup check in `apps.py`, SHA-executor shutdown cleanup in `common.py`, and the
  per-directory scan error handlers in `management/commands/add_directories.py` and
  `add_files.py` (log the one directory's failure, continue to the next).
- `(FileNotFoundError, OSError)` / `(OSError, IOError, ValueError)` — the general
  "a filesystem operation might fail mid-scan" pattern: `common.py`'s `get_file_sha`
  returns `(None, None)` rather than raising; `DirectoryIndex.add_directory` catches
  `(FileNotFoundError, OSError)` around its `stat()` call; `sync_subdirectories` and
  `process_new_files` catch similarly broad tuples and skip the one offending
  entry rather than aborting the whole directory sync.

## Exceptions consumed from `thumbnails`

`quickbbs` imports and handles two of
[`thumbnails`](thumbnails_exceptions.md)'s custom exceptions — see
[`high_level_exception_flow.md`](high_level_exception_flow.md) for the full cross-app
picture:

- **`MediaProcessingError`** — `FileIndex._get_video_info` catches it around a call to
  the AVFoundation backend and retries against the ffmpeg fallback backend
  (`fileindex.py:84`), re-raising only if the ffmpeg backend was already the one in
  use. `FileIndex.check_for_updates` catches it (combined with `OSError, ValueError,
  RuntimeError`) around a movie-duration lookup and logs-and-continues, leaving
  `duration` unset for that file rather than aborting the sync (`fileindex.py:1247`).
- **`OrphanedThumbnail` / `OrphanedFileIndex`** — `quickbbs/tasks.py`'s
  `generate_missing_thumbnails` task catches both around
  `ThumbnailFiles.get_or_create_thumbnail_record(...)`, deletes the orphaned
  `ThumbnailFiles` row (`exc.thumbnail.delete()`), and marks that SHA's result as
  `False` in the task's result dict (`tasks.py:142, 150`). The same two exceptions are
  also caught, independently, inside `thumbnails/views.py` with a different terminal
  handling strategy — see the cross-app flow doc for the comparison.
