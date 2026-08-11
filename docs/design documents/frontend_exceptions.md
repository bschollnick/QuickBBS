# frontend — Exception Taxonomy

**Companion to:** [`frontend_design.md`](frontend_design.md)
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

---

## What this is

`frontend` owns two custom exception classes, both defined, raised, and caught
entirely within a single file. This document also covers the standard/Django
exceptions that are part of `frontend`'s actual error-handling design — not every
`try`/`except` in the codebase, only the ones that shape how a request ends up as a
particular response. Verified directly against `frontend/views.py`,
`frontend/serve_up.py`, `frontend/file_listings.py`, and `frontend/utilities.py`.

---

## Custom exceptions

| Class | Defined | Subclasses | Raised when |
|---|---|---|---|
| `DirectoryNotFoundError` | `frontend/views.py:88` | `Exception` | The directory exists in the database but not on disk, or a newly created record's on-disk sync failed |
| `DirectoryInvalidError` | `frontend/views.py:92` | `Exception` | The requested path lies outside the albums root, or an unexpected error occurred while resolving it |

## Raise and catch sites

Both exceptions are raised exclusively inside
[`_find_directory(paths)`](frontend_design.md#471-helper-functions-in-viewspy)
(`views.py:598–684`), the private helper behind
[`view_gallery`](frontend_design.md#view_galleryrequest):

- **`DirectoryInvalidError`** — raised at `views.py:626` when
  `DirectoryIndex.is_in_albums_tree(dirpath)` is `False` (the path-traversal/escape
  guard); raised again at `views.py:684` when any other exception is caught inside
  `_find_directory`'s broad `except Exception as e` — wrapped as
  `DirectoryInvalidError(...) from e`, so `_find_directory`'s effective public contract
  is "only these two exceptions ever leave this function."
- **`DirectoryNotFoundError`** — raised three times: `views.py:645` when
  `DirectoryIndex.add_directory()` reports the physical directory doesn't exist;
  `views.py:663` when the post-creation `update_database_from_disk()` sync fails;
  `views.py:674` when a directory that existed in the database at lookup time is found
  to have been deleted from disk by the time of a race-condition re-check.

Inside `_find_directory` itself, an `except (DirectoryNotFoundError,
DirectoryInvalidError): raise` (`views.py:679`) re-raises both unchanged before the
broader `except Exception` wraps anything else. The terminal handling happens in
`view_gallery` (`views.py:751–754`):

```python
except DirectoryNotFoundError:
    return HttpResponseNotFound("<h1>gallery not found</h1>")
except DirectoryInvalidError:
    return HttpResponseBadRequest("<h1>Invalid path specified</h1>")
```

Neither exception is imported or caught by any other app — they are entirely private
to `frontend/views.py`.

## Standard/Django exceptions used meaningfully

**`Http404`** — raised directly (not via a caught-and-converted exception) at three
sites: [`download_file`](frontend_design.md#download_filerequest) when no `usha`
identifier is supplied (`views.py:928`) or no matching file is found (`views.py:938`);
and twice in
[`static_or_resources`](frontend_design.md#static_or_resourcesrequest-pathstr)
(`serve_up.py:328, 338`) when a static/resource file path can't be located. All three
are terminal view functions wired directly in `quickbbs/urls.py` — the exception
propagates straight to Django's URL-dispatch machinery uncaught by app code.

**`asyncio.CancelledError`** — caught in `download_file` (`views.py:939`) for the sole
purpose of re-raising it unchanged (bare `raise`) without logging. A client
disconnecting mid-download is expected, not a failure, so this exists to keep it out
of error logs while still letting Django's async machinery run its normal cancellation
cleanup.

**`(DatabaseError, OperationalError)`** — the log-and-fallback pattern for
preference/DB lookups: `_get_show_duplicates_preference` catches `(DatabaseError,
OperationalError, AttributeError)` around a `UserPreferences` lookup and falls back to
`False` (`views.py:190`); `_safe_regex_search` catches `(DatabaseError,
OperationalError)` around a `__iregex` filter and falls back to a plain `__icontains`
query (`views.py:259`) — this is the mechanism behind the `_safe_regex_search()`
fallback documented in
[`frontend_design.md`](frontend_design.md#471-helper-functions-in-viewspy).

**`ValueError` / `TypeError` as parsing guards, not propagated:**
- `get_page_param` catches `(ValueError, TypeError)` around `int(raw_value)` and
  defaults to page 1 (`views.py:118`).
- `create_search_regex_pattern` catches `(TypeError, ValueError)` around
  `re.escape()` and returns an empty pattern (`views.py:214`).
- `view_gallery` catches `(ValueError, UnicodeDecodeError)` around URL-decoding
  `request.path` and falls back to a simpler lowercase-only normalization
  (`views.py:738`).
- [`get_sort_param`](frontend_design.md#get_sort_paramrequest) (in `utilities.py:41`)
  catches `(ValueError, TypeError)` around parsing the `?sort=` query parameter and
  defaults to `settings.DEFAULT_SORT_ORDER` (`utilities.py:60`).

**`ValueError` raised deliberately, as a contract guard — never caught by callers:**
- `managers.py:239` (`layout_manager`) — `"Directory parameter is required"`.
- `managers.py:308, 310` (`get_search_results`) — `"prefetch_dirs parameter is
  required"` / `"prefetch_files parameter is required"`.
- [`convert_to_webpath`](frontend_design.md#convert_to_webpathfull_path-directorynone)
  (`utilities.py:100, 107`) — raised when `directory` is an empty string, or when
  `full_path` doesn't start with the expected albums prefix.

**`OSError` / `PermissionError` / `FileNotFoundError` / `NotADirectoryError`** — in
[`file_listings.py`](frontend_design.md#return_disk_listing_syncfqpn):
`_filter_and_process_item` catches `(OSError, PermissionError)` per directory entry
and returns `None` to skip just that entry (`file_listings.py:53`);
`return_disk_listing_sync` catches `(FileNotFoundError, NotADirectoryError, OSError)`
around the whole scan and returns `(False, {})` (`file_listings.py:101`) — a
transient scan failure is never mistaken for "the directory is empty."

## Out of scope

`frontend/file_mover_colors3.py` and `frontend/organize_by_person_name.py` are
standalone offline CLI utilities with no Django request/response involvement and no
database access — they use generic `OSError`/`shutil.Error` catches for file-move
robustness, but they sit entirely outside the request-handling exception flow this
document otherwise covers.
