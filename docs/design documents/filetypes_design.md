# filetypes — Design Document

**Version:** 4.3
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

**See also:** [`filetypes_erd.md`](filetypes_erd.md) for the entity-relationship
diagram; [`filetypes_exceptions.md`](filetypes_exceptions.md) for the exception
taxonomy.

---

## 1. Guiding Principles

### 1.1 Capability checks read as what they are, not as a category number

A single numeric category is enough to answer "what kind of file is this," but the
gallery constantly needs to answer narrower questions instead — can this be
thumbnailed, does this belong in a text viewer, is this a directory-like entry. Answering
those from one integer means every caller has to know which numbers mean what and
combine them correctly.

- **The rule.** Every capability a file extension has is its own named boolean
  (`is_image`, `is_pdf`, `is_movie`, `is_text`, …) rather than something reconstructed
  from the numeric category.
- **Consequence: clarity and scalability go together here.** `is_image` reads as exactly
  what it checks; a query or condition built from these flags says what it means without
  a second lookup table to decode it. As more distinctions were needed — text versus
  markdown, directory versus link — adding another named boolean stayed simple, where
  extending a single shared number would not have.

### 1.2 The registry is read constantly and changes almost never

Every file and directory encountered during a scan asks this registry whether its
extension is known and what it can do — the busiest lookup path in the app, by a wide
margin, against a table with a handful of rows that a human edits by hand.

- **The rule.** The table is loaded into memory once per worker process; every lookup
  after that is a dict access, never a query.
- **Consequence: the cost of a lookup is paid once, not once per file.** At scan volume,
  a database round trip on every single extension check would be a real, recurring cost
  for a question whose answer essentially never changes between requests. Keeping the
  whole table in memory turns that into O(1) with no database involvement at all after
  the first load.
- **Consequence: a write forces its own reload.** Nothing re-checks the database on its
  own between requests, but that's a non-issue in practice — a save or delete on the
  table fires a signal that forces the in-memory cache to reload immediately, so an
  admin edit is picked up without a restart. The design leans on this rather than
  polling because edits to this table are a genuine rarity: a handful of rows, changed
  by hand, essentially never.

---

## 2. Purpose

`filetypes` is a small, database-backed registry of every file extension the gallery
recognizes. It answers two questions for every other app:

- **Is this extension supported?** — `filetype_exists_by_ext()`
- **What can be done with it?** — MIME type, display icon, per-capability boolean
  flags, fallback thumbnail bytes, and a display color, via `return_filetype()`

`filetypes` sits underneath `quickbbs`: `DirectoryIndex` and `FileIndex` both carry a
foreign key into this table, and every scan path consults it once per file or directory
encountered.

---

## 3. High-Level Architecture

```
quickbbs_settings.py                                  *_FILE_TYPES lists, FTYPES ids
        │
        │ read by
        ▼
manage.py refresh_filetypes            Command.refresh_filetypes()   ← run by hand
        │                     update_or_create() one row per extension
        ▼
┌────────────────────────────────┐
│  filetypes table (DB)          │
│  PK: fileext  (e.g. ".jpg")    │
│  capability booleans, MIME,     │
│  icon filename, thumbnail bytes │
└────────────┬────────────────────┘
             │ loaded once per worker, via
             │   apps.py (WSGI) or middleware.py (ASGI)
             ▼
┌────────────────────────────────┐
│  _filetypes_dict (module-level)│  ← get_ftype_dict() / return_filetype() / etc.
│  dict[fileext, filetypes]       │     read from here, never the DB
└────────────┬────────────────────┘
             ▲
             │ forced reload on
   post_save / post_delete signals (any row write: admin.py, refresh_filetypes, scripts)
```

---

## 4. Component Reference

### 4.1 `models.py`

**What does this do?** Defines the one place the gallery keeps its list of known file
extensions and what each one is allowed to do — whether it's a picture, a movie, a
folder, and so on.

**What is its purpose?** Defines the `filetypes` model, keyed by `fileext` (primary
key — a lowercase, dot-prefixed string, e.g. `".jpg"`, `".dir"`, `".none"`), with a
per-capability boolean field for every type distinction the rest of the app checks.

The single ORM model, keyed by `fileext`.

| Field | Type | Notes |
|---|---|---|
| `fileext` | `CharField(PK, max_length=10)` | Lowercase, dot-prefixed |
| `generic` | `BooleanField` | `True` = serve a stock icon; `False` = generate/serve a real thumbnail |
| `icon_filename` | `CharField` | Bare filename of the fallback icon, joined with `settings.IMAGES_PATH` at call time |
| `color` | `CharField(max_length=7)` | Hex RGB (no `#`), used by the UI |
| `filetype` | `IntegerField` | Numeric category from `settings.FTYPES` — legacy display grouping, not the runtime capability check (§1.1) |
| `mimetype` | `CharField` | Standard MIME type string |
| `is_image` / `is_archive` / `is_pdf` / `is_movie` / `is_audio` / `is_dir` / `is_text` / `is_html` / `is_markdown` / `is_link` | `BooleanField` | Per-capability flags — the authoritative type discriminators at runtime (§1.1) |
| `thumbnail` | `BinaryField` | Raw bytes of the fallback icon image, stored in the row |

**Composite indexes (`Meta`):**

| Index | Fields | Query pattern |
|---|---|---|
| `filetypes_thumbnailable_idx` | `is_image, is_movie, is_pdf` | "Every thumbnailable type" |
| `filetypes_dir_link_idx` | `is_dir, is_link` | Directory and shortcut filtering |
| `filetypes_text_idx` | `is_text, is_html, is_markdown` | Text-content queries |

Per-column indexes on the individual booleans were dropped once the table was confirmed
to be fully memory-resident at startup (§1.2) — a single-column database index serves a
query that never actually reaches the database.

Every static lookup method below reads `get_ftype_dict()`, never the database directly.

#### `_normalize_extension(fileext)`

**What does this do?** Makes sure a file extension is spelled the one way the registry
recognizes, no matter how it arrived — with or without a leading dot, mixed case, or
missing entirely.

**What is its purpose?** Normalizes an extension string to lowercase, dot-prefixed form;
`""`, `None`, and `"unknown"` all normalize to `".none"`.

---

#### `filetype_exists_by_ext(fileext)`

**What does this do?** Lets a caller check whether a file extension is one the gallery
knows how to handle, before doing anything else with it.

**What is its purpose?** Returns `True` if the normalized extension is registered and is
not the `".none"` fallback, `False` otherwise.

---

#### `return_filetype(fileext)`

**What does this do?** Hands back everything the gallery knows about a file extension —
its MIME type, icon, capability flags — in one call.

**What is its purpose?** Returns the `filetypes` row for the normalized extension;
raises `KeyError` if the extension is not registered.

---

#### `return_any_icon_filename(fileext)`

**What does this do?** Finds the fallback icon image to show for a file extension, if
one has been set.

**What is its purpose?** Returns the full path to the extension's icon file under
`settings.IMAGES_PATH`, or `None` if the extension is unknown or has no icon set.

---

#### `send_thumbnail()`

**What does this do?** Serves the stock icon for a file type — the picture shown for
every file of that type that doesn't get its own generated thumbnail.

**What is its purpose?** Wraps `self.thumbnail` in a fresh `BytesIO` and hands it to
`frontend.serve_up.send_file_response`. The `BytesIO` is rebuilt on every call rather
than cached, because Django closes the stream after sending the response — a cached,
already-closed stream would fail on the second request.

---

### 4.2 `models.py`

**What does this do?** Keeps a ready-to-use copy of the whole file-type registry
sitting in memory, so nothing has to go ask the database the same question over and
over while the gallery is running.

**What is its purpose?** Defines the module-level in-memory cache of the `filetypes`
table — `get_ftype_dict()`, `load_filetypes()`, and the two global dicts they
populate — that every capability lookup reads from instead of querying the database.

#### `get_ftype_dict()`

**What does this do?** Holds the whole file-type registry in memory so nothing in the
gallery ever waits on a database round trip just to ask what a file extension means.

**What is its purpose?** Loads the entire table with `filetypes.objects.all().in_bulk()`
(keyed by the primary key, `fileext`) on first call, and returns the same dict on every
call after that.

This is the canonical read path — every lookup method in the model funnels through it,
and it never queries the database a second time on its own.

---

#### `load_filetypes(force=False)`

**What does this do?** Keeps an older, separately named copy of the same registry data
in sync for the one caller that still expects it under its original name, and is the one
entry point that can force a reload after the table changes on disk.

**What is its purpose?** Populates `FILETYPE_DATA`, an older global kept for
`thumbnails/image_utils.py`, by calling `get_ftype_dict()`. With `force=True`, first
clears `_filetypes_dict` so the next `get_ftype_dict()` call reloads from the database —
this is the only way the in-memory copy is ever refreshed (§1.2).

A `SynchronousOnlyOperation` raised inside is deliberately re-raised rather than
swallowed: returning an empty cache here would make every lookup fail silently, looking
exactly like an empty table rather than a call from the wrong context. A plain
`DatabaseError` is caught and printed with a hint to run `refresh_filetypes`, since that
error means the table itself needs attention, not the caller.

`FILETYPE_DATA` and `_filetypes_dict` end up pointing at the same dict object once
loaded — two names for one piece of state, kept only because `image_utils.py` still
reads the older one.

---

### 4.3 `apps.py`

**What does this do?** Makes sure the running gallery notices when someone edits the
list of known file extensions, without slowing down or breaking how the app starts up.

**What is its purpose?** Defines `FiletypesConfig`, the Django app config whose
`ready()` method wires the `filetypes` model's save/delete signals to a forced cache
reload, and otherwise performs no work at startup.

#### `FiletypesConfig.ready()`

**What does this do?** Gets the app's cache-refresh wiring in place at startup without
risking the startup-time database errors and ASGI restrictions that a real query there
would invite.

**What is its purpose?** Connects `post_save` and `post_delete` on the `filetypes` model
to `load_filetypes(force=True)`, and otherwise touches nothing at Django startup.

- **No load in `ready()`.** Querying the database during app initialization triggers a
  Django warning and, in ASGI workers, can run inside an event loop where synchronous
  ORM calls are illegal. Loading is left entirely to `FiletypeLoaderMiddleware` (first
  request) or `get_ftype_dict()`'s own self-loading on first use (non-request contexts,
  such as management commands or the task runner).
- **Auto-reload signals.** Any save or delete of a `filetypes` row — whether made
  through the admin, a script, or `refresh_filetypes` — runs `load_filetypes(force=True)`
  in whichever process performed the write, refreshing that process's in-memory dict
  immediately (§1.2's cache-invalidation consequence). The signal fires per write, in the
  process that made it; it does not reach into other already-running worker processes,
  which keep serving their own in-memory copy until they reload it themselves or restart.

---

### 4.4 `middleware.py`

**What does this do?** Makes sure the file-type registry is ready in memory before the
first page is served, without adding a database check to every request after that.

**What is its purpose?** Loads the table exactly once per worker process, on that
worker's first request, rather than in `__init__` — `__init__` can run in an async
context even under WSGI during testing, and calling the synchronous loader there would
break.

| Path | Mode | Behavior |
|---|---|---|
| `__call__` | WSGI (sync) | Calls `load_filetypes()` on the first request, then sets `_loaded = True` |
| `__acall__` | ASGI (async) | Same, wrapped in `sync_to_async` |

After the first request in either mode, the middleware is a pure pass-through.

---

### 4.5 `admin.py`

**What does this do?** Gives whoever maintains the registry a normal admin screen for
editing extensions and their capability flags, without exposing the raw icon image
bytes as an unreadable blob in the UI.

**What is its purpose?** Standard `ModelAdmin` exposing every field except `thumbnail`
for inspection and editing. `list_filter` includes every capability boolean, for
browsing the registry by category.

Saves and deletes made here go through the same `Model.save()` / `Model.delete()` path
as any other write, so they trigger the `post_save`/`post_delete` reload signals wired
in `apps.py` (§4.3) in the worker process handling the admin request.

---

### 4.6 `management/commands/refresh_filetypes.py`

**What does this do?** Lets whoever adds a new extension to the settings lists get it
into the running registry with a single command, instead of hand-writing database rows.

**What is its purpose?** `python manage.py refresh_filetypes` — seeds or updates the
table from the extension lists in `quickbbs_settings.py`.

For each list (movie, audio, archive, HTML, graphic, text, markdown, link) it builds one
`update_or_create()` entry per extension, resolving the MIME type with
`mimetypes.guess_type` and reading the fallback icon's bytes from `settings.ICONS_PATH`
into the `thumbnail` field. A handful of extensions are added as individually written
entries rather than from a list — `.link`, `.pdf`, `.epub`, `.dir` (the synthetic type
representing a gallery subdirectory), and `.none` (the fallback for unknown or missing
extensions).

`update_or_create` means the command is safe to re-run at any time; existing rows are
updated in place rather than duplicated. Each row it writes calls `Model.save()` (or
`Model.objects.create()`) under the hood, which fires the same `post_save` signal an
admin edit would (§4.3) — so the process running the command reloads its own in-memory
copy as it goes. What the command does not do is reach the in-memory copy held by an
already-running server worker process; those workers only pick up the change through
their own next write-triggered reload or a restart.

**Run this after:** adding a new extension to any `*_FILE_TYPES` list, or changing an
icon file's bytes on disk. Neither takes effect until this command runs.

> `.markdown` appears in both `TEXT_FILE_TYPES` and `MARKDOWN_FILE_TYPES`; the markdown
> loop runs after the text loop, so `update_or_create` leaves that extension with
> `is_markdown=True`, `is_text=False` — the markdown entry wins.

---

## 5. Extension Registry — Settings Contract

`quickbbs_settings.py` is the single source of truth for which extensions exist;
`refresh_filetypes` is what carries that list into the database.

**Numeric category IDs (`FTYPES`)** — used only for the legacy `filetype` display
grouping (§4.1), not for runtime capability checks:

| Key | ID | Notes |
|---|---|---|
| `unknown` | 0 | Fallback (`.none`) |
| `dir` | 1 | Synthetic directory entries |
| `pdf` | 2 | |
| `archive` | 3 | ZIP, RAR, CBZ, CBR |
| `image` | 4 | Also assigned to text and markdown entries |
| `movie` | 5 | |
| `text` | 6 | Unused by any current entry — text rows carry `image` (4) instead |
| `html` | 7 | |
| `epub` | 8 | |
| `flash` | 9 | Legacy; no extensions mapped |
| `audio` | 10 | |
| `markdown` | 11 | Unused by any current entry — markdown rows carry `image` (4) instead |
| `link` | 12 | Assigned to the `.link`/`.alias` entries |

**To add a new extension:**

1. Add the extension string to the appropriate `*_FILE_TYPES` list in
   `quickbbs_settings.py`.
2. Run `python manage.py refresh_filetypes`.
3. The row is inserted or updated, and the process running the command reloads its own
   in-memory copy as it writes (§4.6); other already-running server workers see the
   change only on their own next write-triggered reload or a full restart.

---

## 6. ASGI / WSGI Compatibility

The table always loads through a synchronous ORM call
(`filetypes.objects.all().in_bulk()`), which is safe under WSGI but illegal inside an
ASGI event loop. Two paths reach it depending on server mode:

| Server mode | Load triggered by | Mechanism |
|---|---|---|
| WSGI (runserver, gunicorn) | First request | `FiletypeLoaderMiddleware.__call__` calls `load_filetypes()` directly |
| ASGI (uvicorn, hypercorn) | First request | `FiletypeLoaderMiddleware.__acall__` wraps it in `sync_to_async` |

`apps.py`'s `ready()` deliberately does neither (§4.3) — both paths converge on the same
middleware-driven first-request load, so there is exactly one load path per worker
regardless of server mode. Once loaded, every subsequent read is a plain dict access
with no sync/async bridging involved.

---

## 7. Module Structure Summary

```
filetypes/
├── __init__.py                         # Version metadata only
├── models.py                           # filetypes model, get_ftype_dict(), load_filetypes()
├── apps.py                             # FiletypesConfig: reload signals, no startup DB access
├── middleware.py                       # FiletypeLoaderMiddleware: first-request load, WSGI+ASGI
├── admin.py                            # AdminFiletypes: full field display + capability filters
├── management/
│   └── commands/
│       └── refresh_filetypes.py        # Seed/update the table from settings extension lists
├── migrations/                         # 4 migrations (0001-0004)
├── tests/                              # Package scaffold only — no test modules currently present
└── old/
    └── #constants.py                   # Archived pre-database constants — not imported
```
