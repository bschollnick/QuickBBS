# filetypes — Exception Taxonomy

**Companion to:** [`filetypes_design.md`](filetypes_design.md)
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

---

## What this is

`filetypes` defines no custom exception classes. Its one deliberate exception-handling
contract centers on
[`load_filetypes()`](filetypes_design.md#load_filetypesforcefalse) and a Django
framework exception it lets escape on purpose. Verified directly against
`filetypes/models.py`, `filetypes/middleware.py`, and
`filetypes/management/commands/refresh_filetypes.py`.

---

## `SynchronousOnlyOperation`: deliberately re-raised, never swallowed

`load_filetypes()` (`filetypes/models.py:241–283`) is a three-tier except chain around
the call that populates the module-level filetype dict from the database:

```python
try:
    FILETYPE_DATA = get_ftype_dict()
except SynchronousOnlyOperation:
    raise
except DatabaseError as e:
    ...  # print instructions, swallow
except Exception as e:  # TODO: narrow once startup failure modes are known
    ...  # print instructions, swallow
```

`SynchronousOnlyOperation` (`django.core.exceptions`) is caught only to be re-raised
unchanged — the opposite of the `DatabaseError`/`Exception` tiers below it, which both
print operator instructions and swallow the error, returning the possibly-stale or
empty existing cache. The function's own docstring states why: silently returning an
empty cache here would make every filetype lookup fail while looking like an
unpopulated table, which is a worse failure mode than letting the real error surface.

**This exception is never actually caught anywhere else in the codebase.** It is a
documented contract, not a handled error path: an async caller is required to wrap
`load_filetypes()` in `sync_to_async()` to avoid triggering it at all. The one caller
that matters here,
[`FiletypeLoaderMiddleware.__acall__`](filetypes_design.md#44-middlewarepy-filetypeloadermiddleware)
(`middleware.py:63`), does exactly that (`await sync_to_async(load_filetypes)()`); its
sync counterpart, `__call__` (`middleware.py:47`), calls `load_filetypes()` directly,
which is safe precisely because it's the sync code path. If a future async caller
forgot the `sync_to_async()` wrapper, `SynchronousOnlyOperation` would propagate
uncaught up through Django/ASGI — that is the intended behavior, not a gap.

## `DatabaseError`: two different responses depending on context

- **Request-time (worker startup):** `load_filetypes()`'s `except DatabaseError`
  tier (`models.py:271`) prints operator instructions ("Please use manage.py
  --refresh-filetypes") and swallows the error, returning the existing (possibly
  empty) `FILETYPE_DATA` cache rather than raising — a failed load at worker startup
  doesn't crash the worker.
- **CLI (management command):** `refresh_filetypes.Command.handle()`
  (`management/commands/refresh_filetypes.py:246–259`) treats `(DatabaseError,
  OperationalError)` as fatal: writes to `self.stderr` via Django's command styling
  and calls `sys.exit(1)`. This is the one place in `filetypes` where a database
  failure is treated as a hard stop rather than a log-and-continue — appropriate for a
  CLI invocation, where there's no running worker to keep alive.

## `KeyError`: documented, but practically unreachable

[`return_filetype(fileext)`](filetypes_design.md#return_filetypefileext)'s docstring
states it raises `KeyError` if the extension isn't registered — its implementation is
a bare dict lookup, `get_ftype_dict()[fileext]`. In practice this path is defensive
rather than a real error path a caller needs to handle: both call sites that matter —
`DirectoryIndex.add_directory()`
([`quickbbs_app_design.md` §4.2](quickbbs_app_design.md#42-directoryindexpy--directoryindex))
passing the literal, always-registered `.dir` extension, and
`FileIndex.from_filesystem()`
([§4.3](quickbbs_app_design.md#43-fileindexpy--fileindex)) passing a filesystem-derived
extension — either use a hardcoded, known-good value or are guarded beforehand by
[`filetype_exists_by_ext(fileext)`](filetypes_design.md#filetype_exists_by_extfileext)
(`fileindex.py:579`, checked immediately before `return_filetype()` is called at
`fileindex.py:591`). Neither call site catches the `KeyError` this could otherwise
raise.
