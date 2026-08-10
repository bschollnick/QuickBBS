# filetypes — Exception Taxonomy

**Companion to:** [`filetypes_design.md`](filetypes_design.md)
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-10

---

## What this is

`filetypes` defines no custom exception classes. Its one deliberate exception-handling
contract centers on
[`load_filetypes()`](filetypes_design.md#load_filetypesforcefalse): every exception
raised while reloading the cache — Django framework exceptions and `DatabaseError`
alike — is left to propagate unhandled, on purpose. Verified directly against
`filetypes/models.py`, `filetypes/middleware.py`, and
`filetypes/management/commands/refresh_filetypes.py`.

---

## Every reload failure propagates: nothing is swallowed

`load_filetypes()` (`filetypes/models.py`) does not wrap its call to
`get_ftype_dict()` in a `try`/`except` at all:

```python
if not _filetypes_dict or force:
    _filetypes_dict = None
    print("Loading FileType data from database...")
    return get_ftype_dict()  # any exception here propagates unhandled
return _filetypes_dict
```

**Reversed decision (2026-08-10):** an earlier version of this function caught
`DatabaseError` (and a broad `Exception` tier below it), printed operator instructions
("Please use manage.py --refresh-filetypes"), and returned the existing — possibly
stale or empty — cache rather than raising, on the theory that a failed load at worker
startup shouldn't crash the worker. Code review caught that the fallback was
implemented incorrectly (it returned `None`, not the actual previous dict), and the
user's response was to reject the swallow-and-continue strategy entirely, not just fix
the bug in it: **a failed reload must not be recoverable in place.** In this codebase,
a failed filetypes reload is not an expected, tolerable incident — it is a sign of
complete system failure. There is no supported API or programmatic path where the
filetypes table is expected to be unreloadable, so `load_filetypes()` is not designed
to limp forward when it is. Running the scan path (`fileindex.py`) or directory
aggregate path (`directoryindex.py`) against stale or invalid filetype data is worse
than failing loudly: the worker process (WSGI), the request (ASGI middleware, via
`sync_to_async`), or the `post_save`/`post_delete` signal handler that triggered the
reload should die or fail rather than continue on data it can no longer trust.

`SynchronousOnlyOperation` (`django.core.exceptions`) gets the same treatment as any
other exception now — it always propagated in the prior version too, so this is not a
behavior change for it specifically. It remains a documented contract, not a handled
error path: an async caller is required to wrap `load_filetypes()` in `sync_to_async()`
to avoid triggering it at all. The one caller that matters here,
[`FiletypeLoaderMiddleware.__acall__`](filetypes_design.md#44-middlewarepy-filetypeloadermiddleware)
(`middleware.py:63`), does exactly that (`await sync_to_async(load_filetypes)()`); its
sync counterpart, `__call__` (`middleware.py:47`), calls `load_filetypes()` directly,
which is safe precisely because it's the sync code path.

## `DatabaseError`: now a hard stop everywhere, not just the CLI

- **Request-time (worker startup / signal handler):** `load_filetypes()` no longer
  catches `DatabaseError`. A failed reload propagates out of
  `FiletypeLoaderMiddleware.__call__`/`__acall__` into the WSGI/ASGI request cycle, or
  out of the `post_save`/`post_delete` signal handler in `apps.py` into whatever
  save/delete triggered it (e.g. an admin edit to a `filetypes` row). This intentionally
  crashes the worker or fails the request rather than continuing on stale data — see
  "Reversed decision" above.
- **CLI (management command):** `refresh_filetypes.Command.handle()`
  (`management/commands/refresh_filetypes.py:246–259`) already treated `(DatabaseError,
  OperationalError)` as fatal: writes to `self.stderr` via Django's command styling
  and calls `sys.exit(1)`. This is unchanged — the CLI and request-time paths are now
  consistent with each other, where before the CLI was the only hard stop.

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
