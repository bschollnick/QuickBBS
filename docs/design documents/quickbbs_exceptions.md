# quickbbs — Exception Taxonomy

**Date Created:** 2026-08-07  
**Last Updated:** 2026-09-20  
**Last Reviewed:** 2026-09-20

**Companion to:** [`quickbbs_app_design.md`](quickbbs_app_design.md)
**Author:** Benjamin Schollnick

---

## What this is

`quickbbs` defines no custom exception classes of its own. This file documents where
it raises and catches standard/Django exceptions as a deliberate part of its
error-handling design, and where it consumes exceptions defined by
[`thumbnails`](thumbnails_exceptions.md). Verified directly against
`quickbbs/quickbbs/{directoryindex,fileindex,tasks,settings,apps,common,asgi}.py`.

---

## Contract guards: `ValueError` and `TypeError` raised, never caught by callers

Several methods on
[`DirectoryIndex`](quickbbs_app_design.md#42-directoryindexpy--directoryindex) and
[`FileIndex`](quickbbs_app_design.md#43-fileindexpy--fileindex) raise `ValueError` when
a required keyword argument is missing — this is a programmer-error guard, not a
runtime-data problem, and nothing in the codebase catches it:

- `DirectoryIndex.get_all_parent_shas`, `.return_by_sha256_list`, `.files_in_dir`,
  `.dirs_in_dir` — raise `ValueError("select_related parameter is required")`
  when the caller omits that argument (`directoryindex.py:643, 988, 1095, 1328`).
  `return_by_sha256_list` and `dirs_in_dir` also take `prefetch_related` and
  raise `ValueError("prefetch_related parameter is required")` for it
  (`directoryindex.py:990, 1330`); `get_all_parent_shas` and `files_in_dir`
  have no such parameter.
- `FileIndex.return_by_sha256_list`, `.get_by_sha256`, `.get_by_sha256_for_download` —
  same pattern, `ValueError("select_related parameter is required")`
  (`fileindex.py:298, 326, 367`).
- `FileIndex.fqpndirectory` (property) — raises `ValueError` when `home_directory` is
  `None`, meaning the record is orphaned (`fileindex.py:201`).
- `FileIndex.check_for_updates` — raises `TypeError` (not `ValueError`) when `fs_stat`
  is a value other than a stat result or `None` (`fileindex.py:1091`).
- `FileIndex._resolve_alias_uncached` — raises `ValueError` when macOS bookmark data
  can't be encoded or decoded (`fileindex.py:1334, 1340`). `error` is a PyObjC
  out-parameter rather than a caught exception, so neither raise chains with `from`.

## `Http404`: converting a filesystem miss into a proper 404

`FileIndex.inline_sendfile` and `FileIndex.async_inline_sendfile` both catch
`FileNotFoundError` around their file-open call and re-raise as `Http404 from exc`
(`fileindex.py:979, 1001, 1038`) — this is what lets a file that's vanished from disk
between the database record being read and the file being opened surface as a normal
404 response rather than an unhandled 500. Both methods are the terminal file-serving
step behind [`frontend`](frontend_exceptions.md)'s `download_file` view.

## `DatabaseError`: log and return a safe default, never propagate

The single-row cache-invalidation methods on `DirectoryIndex` wrap their write in
`try`/`except DatabaseError` (sometimes combined with `AttributeError`) and return a
safe default rather than letting the error reach the caller.  The batch method
`invalidate_caches` (`directoryindex.py:531`) does not — a failure there propagates:

- `cache_valid_for_sha` — `except DatabaseError` → logs, returns `False`
  (`directoryindex.py:474`).
- `invalidate_cache` — `except (DatabaseError, AttributeError)` → logs, returns
  `False` (`directoryindex.py:503`).
- `invalidate_cache_by_sha` — same pattern (`directoryindex.py:526`).
- `invalidate_all_caches` — `except DatabaseError` → logs, returns `0`
  (`directoryindex.py:617`).

The same pattern appears outside `DirectoryIndex`, catching
`(DatabaseError, OperationalError)` in both places: `quickbbs/tasks.py`'s vacuum task
logs and continues (`tasks.py:335`), and `quickbbs/asgi.py`'s startup DB-pool
pre-warm does the same at ASGI lifespan startup (`asgi.py:82`).

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
- Broad, deliberately unnarrowed `except Exception` — each site carries a
  `# pylint: disable=broad-exception-caught` on the `except` rather than a code tag:
  the SSL-certificate startup check in `apps.py:107` and its sibling at `apps.py:149`,
  SHA-executor shutdown cleanup in `common.py:292`, and the per-directory scan error
  handlers in `management/commands/add_directories.py:93` and `add_files.py:69`
  (log the one directory's failure, continue to the next).
- `(FileNotFoundError, OSError)` and its relatives — the general
  "a filesystem operation might fail mid-scan" pattern: `common.py`'s `get_file_sha`
  returns `(None, None)` rather than raising; `DirectoryIndex.add_directory` catches
  `(FileNotFoundError, OSError)` around its `stat()` call (`directoryindex.py:323`);
  `sync_subdirectories` catches `(OSError, IOError, ValueError, TypeError)`
  (`directoryindex.py:1519`) and `process_new_files` catches `(OSError, IOError)`
  (`directoryindex.py:1590`), each skipping the one offending entry rather than
  aborting the whole directory sync.

## Exceptions consumed from `thumbnails`

`quickbbs` imports and handles two of
[`thumbnails`](thumbnails_exceptions.md)'s custom exceptions — see
[`high_level_exception_flow.md`](high_level_exception_flow.md) for the full cross-app
picture:

- **`MediaProcessingError`** — `thumbnails.engine.get_video_info` catches it around
  the resolved probe and retries against the ffmpeg probe
  (`thumbnails/engine/engine.py:155`), re-raising only if the ffmpeg probe was
  already the resolved one. `FileIndex.check_for_updates` catches it (combined with
  `OSError, ValueError, RuntimeError`) around a movie-duration lookup and
  logs-and-continues, leaving `duration` unset for that file rather than aborting the
  sync (`fileindex.py:1160`). `fileindex.py` reaches that function through
  `from thumbnails.engine import get_video_info as _get_video_info` (`:41`).
- **`OrphanedThumbnail` / `OrphanedFileIndex`** — `quickbbs/tasks.py`'s
  `generate_missing_thumbnails` task catches both around
  `ThumbnailFiles.get_or_create_thumbnail_record(...)`, deletes the orphaned
  `ThumbnailFiles` row (`exc.thumbnail.delete()`), and marks that SHA's result as
  `False` in the task's result dict (`tasks.py:148, 156`). The same two exceptions are
  also caught, independently, inside `thumbnails/views.py` with a different terminal
  handling strategy — see the cross-app flow doc for the comparison.
