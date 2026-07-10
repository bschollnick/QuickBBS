# filetypes — Design Document

**Version:** 3.99  
**Author:** Benjamin Schollnick  
**Last Updated:** 2026-04-11

---

## 1. Purpose

`filetypes` is a Django application that provides a small, database-backed registry of
every file extension the gallery understands. It answers two questions for every other
part of QuickBBS:

1. **Is this extension supported?** (`filetype_exists_by_ext`)
2. **What are its properties?** (MIME type, display icon, boolean category flags,
   thumbnail bytes, hex colour)

The table is small and read-only at runtime, so it is loaded once per worker process
into a module-level dict and never queried again during normal operation. Every lookup
is an O(1) dict access with zero database round-trips.

---

## 2. High-Level Architecture

```
settings (quickbbs_settings.py)
  Lists of known extensions grouped by category
  FTYPES dict mapping category names → numeric IDs
        │
        │ seeded by
        ▼
manage.py refresh_filetypes          ← run once after adding new extensions
  update_or_create() each extension row
        │
        │ rows stored in
        ▼
┌─────────────────────────────────┐
│  filetypes table (DB)           │
│  PK: fileext  (e.g. ".jpg")     │
│  Boolean flags, MIME, thumbnail  │
└────────────┬────────────────────┘
             │ loaded once at startup
             ▼
┌─────────────────────────────────┐
│  _filetypes_dict  (module-level)│
│  dict[str, filetypes]           │  ← all callers read from here
└─────────────────────────────────┘
             ▲
             │ invalidated + reloaded on
  post_save / post_delete signals (admin edits)
```

---

## 3. Component Reference

### 3.1 `models.py` — `filetypes` model

The single ORM model. Its primary key is `fileext` (a lowercase string including the
leading dot, e.g. `".jpg"`).

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `fileext` | `CharField(PK, max_length=10)` | Lowercase, dot-prefixed. e.g. `".jpg"`, `".dir"`, `".none"` |
| `generic` | `BooleanField` | `True` = use a static icon; `False` = generate/serve a real thumbnail |
| `icon_filename` | `CharField` | Bare filename of the fallback icon (joined with `settings.IMAGES_PATH` at call time) |
| `color` | `CharField(max_length=7)` | Hex RGB colour (no `#`) used by the UI |
| `filetype` | `IntegerField` | Numeric category ID from `settings.FTYPES` |
| `mimetype` | `CharField` | Standard MIME type string |
| `is_image` | `BooleanField` | True for raster image formats |
| `is_archive` | `BooleanField` | True for ZIP/RAR/CBZ/CBR |
| `is_pdf` | `BooleanField` | True for `.pdf` |
| `is_movie` | `BooleanField` | True for video formats |
| `is_audio` | `BooleanField` | True for audio formats |
| `is_dir` | `BooleanField` | True for the synthetic `.dir` extension |
| `is_text` | `BooleanField` | True for plain-text formats |
| `is_html` | `BooleanField` | True for `.html`/`.htm` |
| `is_markdown` | `BooleanField` | True for `.md`/`.markdown` |
| `is_link` | `BooleanField` | True for `.link`/`.alias` shortcut files |
| `thumbnail` | `BinaryField` | Raw bytes of the fallback icon image, stored in DB |

**Why boolean flags instead of a single integer category?**  
A single `filetype` integer works for exact-category queries, but "fetch everything
that can show a thumbnail" previously required SQL `WHERE filetype IN (2, 4, 5)`
(PDF, image, movie). As categories grew, that became unmaintainable. The boolean flags
(`is_image`, `is_pdf`, `is_movie`) make intent explicit in application code and are
covered by composite database indexes.

**Database indexes (Meta):**

| Index name | Fields | Query pattern covered |
|---|---|---|
| `filetypes_thumbnailable_idx` | `is_image, is_movie, is_pdf` | "Fetch all thumbnailable types" |
| `filetypes_dir_link_idx` | `is_dir, is_link` | Directory and shortcut filtering |
| `filetypes_text_idx` | `is_text, is_html, is_markdown` | Text content queries |

Individual per-column `db_index` values were removed in migration 0004 once the table
was confirmed to be fully cached in memory at startup, making DB-level single-column
indexes redundant.

**Reverse FK annotations (type-checking only):**

```python
dirs_filetype_data: RelatedManager[DirectoryIndex]  # DirectoryIndex.filetype FK
file_filetype_data: RelatedManager[FileIndex]        # FileIndex.filetype FK
```

These are declared as `TYPE_CHECKING`-only annotations for IDE support; they are not
used at runtime.

---

### 3.2 `models.py` — static lookup methods

All three methods normalize the extension first (see `_normalize_extension`) and then
read from the module-level dict — no DB query.

| Method | Signature | Returns |
|---|---|---|
| `_normalize_extension(fileext)` | `str → str` | Lowercase, dot-prefixed; maps `""` / `None` / `"unknown"` to `".none"` |
| `filetype_exists_by_ext(fileext)` | `str → bool` | `True` if extension is in the dict and not `".none"` |
| `return_filetype(fileext)` | `str → filetypes` | The `filetypes` ORM object for the extension |
| `return_any_icon_filename(fileext)` | `str → str \| None` | Full path to icon, or `None` if no icon set |

**`send_thumbnail()`** creates a fresh `BytesIO` from `self.thumbnail` bytes and
returns a `FileResponse` via `send_file_response`. A new `BytesIO` is created on every
call because Django closes the stream after sending the response.

---

### 3.3 `models.py` — module-level cache functions

**`get_ftype_dict() → dict`**

Lazy-loads the full `filetypes` table into `_filetypes_dict` using `in_bulk()` (keyed
by primary key = `fileext`) on first call. Returns the same dict object on all
subsequent calls. This is the canonical read path.

**`load_filetypes(force=False) → dict`**

Populates the older `FILETYPE_DATA` global (kept for backward compatibility with
`thumbnails/image_utils.py`) by calling `get_ftype_dict()`. When `force=True`, sets
`_filetypes_dict = None` first to clear the lazy cache, forcing a DB reload on the
next `get_ftype_dict()` call. Handles `DatabaseError` gracefully and prints a hint to
run `refresh_filetypes`.

**Two globals, one source:**

| Global | Type | Consumer |
|---|---|---|
| `_filetypes_dict` | `dict \| None` | `get_ftype_dict()` and all static methods |
| `FILETYPE_DATA` | `dict` | `thumbnails/image_utils.py` (legacy reference) |

Both point at the same underlying dict object after loading.

---

### 3.4 `apps.py` — `FiletypesConfig`

Django `AppConfig` that wires two behaviors at startup:

1. **Eager load (WSGI):** If no asyncio event loop is running when `ready()` is called,
   calls `load_filetypes()` synchronously. Safe for `runserver` and gunicorn.

2. **Deferred load (ASGI):** If an event loop is detected (`asyncio.get_running_loop()`
   does not raise), loading is skipped. `FiletypeLoaderMiddleware` will load on the
   first request instead. This avoids `SynchronousOnlyOperation` errors in Uvicorn /
   Hypercorn workers.

3. **Auto-reload signals:** Connects `post_save` and `post_delete` to
   `load_filetypes(force=True)` for the `filetypes` model. Any admin save or delete
   immediately refreshes the in-memory dict in that worker process.

---

### 3.5 `middleware.py` — `FiletypeLoaderMiddleware`

Ensures filetypes are loaded exactly once per worker process in ASGI mode.

**`__init__`** detects async mode via `iscoroutinefunction(get_response)` and sets
`self._loaded = False`. Loading is deliberately **not** done in `__init__` because
`__init__` can execute in an async context even under WSGI during testing, which would
break DB access.

**`__call__`** (WSGI sync path): Calls `load_filetypes()` on the first request, then
sets `_loaded = True`. No overhead on subsequent requests.

**`__acall__`** (ASGI async path): Wraps `load_filetypes` with `sync_to_async` for
the first request.

After the first request the middleware is effectively a no-op pass-through.

---

### 3.6 `admin.py` — `AdminFiletypes`

Standard `ModelAdmin` exposing all fields for manual inspection and editing. Includes
list filters on every boolean flag for quick category browsing.

`thumbnail` is intentionally excluded from both `fields` and `list_display` — the
binary blob would be unreadable and too large to render safely in the admin interface.

Changes saved through admin trigger the `post_save` signal, which calls
`load_filetypes(force=True)` automatically.

---

### 3.7 `management/commands/refresh_filetypes.py`

Management command: `python manage.py refresh_filetypes --refresh-filetypes`

Reads all `*_FILE_TYPES` lists and `FTYPES` from `settings`, builds a list of dicts,
and calls `filetypes.objects.update_or_create(fileext=..., defaults=...)` for each
entry. MIME types are resolved with `mimetypes.guess_type`. Icon thumbnails are read
from `settings.ICONS_PATH` as raw bytes and stored in the `thumbnail` field.

**When to run:**

- Initial project setup (empty database)
- After adding a new extension to any `*_FILE_TYPES` list in `quickbbs_settings.py`
- After changing an icon file on disk

**Idempotent:** Safe to re-run at any time; existing rows are updated in place.

**Special entries added unconditionally:**

| Extension | Purpose |
|---|---|
| `.link` | macOS-style URL shortcut |
| `.pdf` | PDF documents |
| `.epub` | E-book format |
| `.dir` | Synthetic type representing a gallery subdirectory |
| `.none` | Fallback for unknown/missing extensions |

---

## 4. Extension Registry — Settings Contract

`quickbbs_settings.py` is the single source of truth for which extensions are
supported. `refresh_filetypes` reads these at command time; the database is the runtime
source.

**Numeric category IDs (`FTYPES`):**

| Key | ID | Notes |
|---|---|---|
| `unknown` | 0 | Fallback |
| `dir` | 1 | Synthetic directory entries |
| `pdf` | 2 | |
| `archive` | 3 | ZIP, RAR, CBZ, CBR |
| `image` | 4 | Also used for text/markdown (`filetype` field) |
| `movie` | 5 | |
| `text` | 6 | |
| `html` | 7 | |
| `epub` | 8 | |
| `flash` | 9 | Legacy; no extensions mapped |
| `audio` | 10 | |
| `markdown` | 11 | |
| `link` | 12 | |

Note: text and markdown rows carry `filetype=4` (image) in the database — an artifact
of an earlier design where they shared the image rendering path. Their boolean flags
(`is_text`, `is_markdown`) are the authoritative type discriminators at runtime.

**To add a new extension:**

1. Add the extension string to the appropriate `*_FILE_TYPES` list in
   `quickbbs_settings.py`.
2. Run `python manage.py refresh_filetypes --refresh-filetypes`.
3. The row is inserted (or updated) in the `filetypes` table and the in-memory dict
   reloaded.

---

## 5. Data Flow — Extension Lookup at Runtime

```
FileIndex / DirectoryIndex creation (scan)
    └── filetypes.filetype_exists_by_ext(ext)      # is this extension known?
           └── get_ftype_dict()[ext]                # O(1) dict lookup
    └── filetypes.return_filetype(ext)              # get full row object
           └── get_ftype_dict()[ext]                # O(1) dict lookup

Thumbnail serving
    └── filetypes.send_thumbnail()                  # for generic-icon types
           └── io.BytesIO(self.thumbnail)           # bytes already in memory
           └── send_file_response(...)

Directory listing (file_listings.py)
    └── filetype_models.filetypes.filetype_exists_by_ext(fext)
           # skips files with unrecognised extensions
```

---

## 6. ASGI / WSGI Compatibility

The table is always loaded via a synchronous ORM query (`filetypes.objects.all().in_bulk()`).
This is safe in WSGI. In ASGI (Uvicorn/Hypercorn) the Django `ready()` hook may run
inside the event loop, making synchronous ORM calls illegal.

The dual-path design handles this:

| Server mode | Load triggered by | Mechanism |
|---|---|---|
| WSGI (runserver, gunicorn) | `AppConfig.ready()` | Direct `load_filetypes()` call |
| ASGI (uvicorn, hypercorn) | First HTTP request | `FiletypeLoaderMiddleware.__acall__` via `sync_to_async` |

Once loaded, all subsequent reads use the module-level dict and require no
sync/async bridging.

---

## 7. Module Structure Summary

```
filetypes/
├── __init__.py                         # Version metadata only
├── models.py                           # filetypes model, get_ftype_dict(), load_filetypes()
├── apps.py                             # FiletypesConfig: startup load + auto-reload signals
├── middleware.py                       # FiletypeLoaderMiddleware: ASGI-safe deferred load
├── admin.py                            # AdminFiletypes: full field display + boolean filters
├── management/
│   └── commands/
│       └── refresh_filetypes.py        # Seed/update the filetypes table from settings
├── migrations/
│   ├── 0001_initial.py                 # Initial table + per-column indexes
│   ├── 0002_filetypes_thumbnail.py     # Added BinaryField thumbnail column
│   ├── 0003_…_thumbnailable_idx.py     # Added composite Meta indexes
│   └── 0004_alter_filetypes_…py        # Removed per-column db_index (table is memory-cached)
├── tests/
│   ├── test_models.py
│   ├── test_middleware.py
│   └── test_management_commands.py
└── old/
    └── #constants.py                   # Archived pre-DB constants (not imported)
```
