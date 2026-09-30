# thumbnails — Design Document

**Version:** 4.6  
**Author:** Benjamin Schollnick

**Date Created:** 2026-08-10  
**Last Updated:** 2026-09-24  
**Last Reviewed:** 2026-09-19

**See also:** [`thumbnails_erd.md`](thumbnails_erd.md) for the entity-relationship
diagram; [`thumbnails_exceptions.md`](thumbnails_exceptions.md) for the exception
taxonomy.

---

## 1. Guiding Principles

### 1.1 The database is easier to keep correct than a file cache would be

Carried down from [quickbbs Section 1.1](quickbbs_app_design.md#11-the-filesystem-is-the-source-of-truth-the-database-is-a-cache).
A thumbnail cache on disk would need its own lifecycle management — one or more files
per size, per source file, that have to be created, invalidated, and cleaned up in step
with the record describing them — mirroring bookkeeping the database already does for
everything else it tracks. That duplication is where the real cost is, not raw disk I/O.

- **The rule.** Every generated thumbnail size lives as bytes in a database column, on
  the same row the rest of the app already treats as authoritative for that file. There
  is no separate on-disk thumbnail directory to keep in sync.
- **Consequence: fewer things that can each independently go stale.** A rename, a
  duplicate, or a deleted source file changes exactly one thing to reconcile — the
  database row — instead of a database row plus a matching (or now-orphaned) set of
  files on disk.
- **Consequence: one write path, transactionally.** When a view generates a
  thumbnail, `get_or_create_thumbnail_record()` stores the bytes on the same row, in
  the same transaction, as the rest of its bookkeeping (Section 4.10). The batch path,
  `quickbbs.tasks.generate_missing_thumbnails()`, passes `suppress_save=True` and
  writes every generated row afterwards in one `bulk_update()`. Either way there is no
  second write (a file create) that can succeed while the row update fails, or the
  reverse, and nothing to fsync separately or clean up after a crash mid-write. A
  disk-cache design would need to make that pair of writes atomic itself.
- **Consequence: no separate existence check to add.** Every thumbnail request already
  looks up the `FileIndex` row, to resolve the generic-icon and link short-circuits
  (Section 1.5, Section 4.11) before any bytes are served. The bytes then come from one
  single-column `SELECT` on `ThumbnailFiles`; a disk cache would add a file
  `open()`/`read()` after the same row lookup, not replace it.
- **Consequence: a read fetches only the size it serves.** Every read path selects
  only the blob column it needs: the serving fast path loads just the requested size,
  and `get_or_create_thumbnail_record()` defers all three blob columns. A small
  thumbnail request never transfers the medium or large bytes.

### 1.2 GPU acceleration is an accelerator, never a requirement

Carried down from [frontend Section 1.3](frontend_design.md#13-self-hosted-format-agnostic-cross-platform).
Every macOS-native backend (Core Image, PDFKit, AVFoundation) has a cross-platform
counterpart (PIL, PyMuPDF, ffmpeg) that produces the same result through ordinary
software rendering.

- **The rule.** Thumbnail generation must produce a correct result on a machine with
  none of the macOS frameworks present. Nothing in the pipeline may assume a GPU backend
  is available.
- **Consequence: every macOS backend is optional at import time and at selection time.**
  Backend availability is probed once, not assumed from the platform name, and whether
  automatic selection is allowed to pick a macOS backend at all is itself a separate
  setting — so the accelerated path can be turned off independent of what's actually
  installed. Requesting `"coreimage"` by name is the only way to demand a macOS backend
  outright: it raises `ImportError` when Core Image is missing. Every other selector,
  including an explicit `"pdfkit"`, falls back to its cross-platform backend
  (Section 4.3).

### 1.3 A cache must never claim something doesn't exist

Carried down from [quickbbs Section 1.2](quickbbs_app_design.md#12-a-cache-must-never-claim-something-doesnt-exist).
This app doesn't keep a cache of its own for thumbnail lookups; it depends on
`FileIndex.get_by_sha256()` in `quickbbs/fileindex.py`, whose cache never stores an
absence — a lookup that finds nothing simply isn't cached, so a thumbnail generated
moments later by a concurrent request is found on the very next lookup rather than
staying invisible until an entry ages out. `thumbnail_file`'s fast path (Section 4.11) reads
through this cache on every request.

### 1.4 Identical files share one thumbnail

Carried down from [quickbbs Section 1.3](quickbbs_app_design.md#13-identical-files-are-the-same-file).
`ThumbnailFiles` is keyed by the source file's content SHA256, not by any particular
copy's path — every `FileIndex` row with identical bytes, wherever it lives in the
gallery, points at the same thumbnail row through `new_ftnail`. A thumbnail is generated
once per distinct piece of content, however many times that content appears.

### 1.5 Every file has a visual representation

A gallery page shows an image for every entry on it. For an image, PDF, or video, that
image is a real rendered thumbnail of the file's own content (Section 4.4–Section 4.9). For a
directory, it's a cover image selected from one of the files inside it —
`thumbnail_dir()` (Section 4.11) prefers a file already chosen as the cover, then a file
whose name starts with an entry in `settings.DIRECTORY_COVER_NAMES` (`cover`, `title`)
followed by a dot, then any image, video or PDF in the directory — so browsing a
gallery of directories shows an actual preview of what's inside each one, not a
folder icon.

- **The rule.** Every file resolves to *some* displayable image.
  - Most files: a rendered thumbnail of their own content.
  - Directories: a cover image proxied from a file inside them.
  - The remaining cases fall back to the filetype's own generic icon, stored on its
    `filetypes` row — either because the
    filetype was never meant to have a rendered preview (text, archives, and similar),
    or because generation was attempted for this specific file and failed.
- **Consequence: a failure to generate is not a failure to display.** Thumbnail
  generation can fail — a corrupt image, an unsupported codec, a damaged PDF — without
  that failure reaching the person browsing the gallery as a broken image or an error.
  The page still shows something recognizable for that file.

---

## 2. Purpose

`thumbnails` generates, stores, and serves image thumbnails for every file type
QuickBBS supports — images, PDFs, videos, and directories (via a selected cover image).
It answers three questions:

- **Does a thumbnail exist?** — `ThumbnailFiles`, keyed by content SHA256 (Section 1.4)
- **How do I generate one?** — a pluggable backend system dispatched by
  `FastImageProcessor`
- **How do I serve one?** — `ThumbnailFiles.send_thumbnail()` and the two HTTP views

Thumbnails are stored as raw JPEG bytes across three columns (`small_thumb`,
`medium_thumb`, `large_thumb`) on one row per distinct file content (Section 1.1); there is no
on-disk thumbnail cache.

---

## 3. High-Level Architecture

```
HTTP request
    └── thumbnail_file(sha256)  /  thumbnail_dir(dir_sha256)
              │
              ├── requested size already stored → send_thumbnail()   (no lock)
              │
              ▼
    ThumbnailFiles.get_or_create_thumbnail_record(sha256)
              │  pg_advisory_xact_lock (per-SHA)
              │  prevents duplicate generation under concurrency
              │
              ├── small_thumb populated by another worker → return the record
              │
              └── small_thumb absent
                        │
                        ▼
              create_thumbnails_from_path(file_path, sizes, backend=selector)
                        │
                        │  backend selection (once per selector, cached)
                        │
                        ├── CoreImageBackend   (macOS GPU, images — Section 1.2)
                        ├── PDFKitBackend      (macOS GPU, PDFs)
                        ├── AVFoundationVideoBackend  (macOS, video)
                        ├── ImageBackend (PIL)  (cross-platform, images)
                        ├── PDFBackend (PyMuPDF) (cross-platform, PDFs)
                        └── VideoBackend (ffmpeg) (cross-platform, video)
                        │
                        ▼
              ThumbnailFiles (model)
              small_thumb / medium_thumb / large_thumb  ← bytes stored in the database
              FileIndex.new_ftnail  ← foreign key linked
```

---

## 4. Component Reference

### 4.1 `exceptions.py`

**What does this do?** Gives every part of the app a shared, specific vocabulary for
what went wrong when a thumbnail couldn't be made or served, instead of everything
looking like a generic error.

**What is its purpose?** Gives callers a single import location for every
thumbnail-specific exception, so they can catch them without importing the backend or
model modules that raise them.

The declarations are split along the extraction boundary. The five
framework-independent exceptions live in `engine/exceptions.py`; the two that carry a
`ThumbnailFiles` instance in their constructor stay in `thumbnails/exceptions.py`,
which re-exports the engine's five so a single import still reaches all seven.

| Exception | Inherits | Purpose |
|---|---|---|
| `ThumbnailGenerationError` | `Exception` | Generation returned no small thumbnail, or `send_thumbnail()` found the requested blob empty; carries `filename` |
| `MediaProcessingError` | `Exception` | A backend failed to load or decode a file; carries `file_path` |
| `PDFProcessingError` | `MediaProcessingError` | `PDFKitBackend` or `PDFBackend` (PyMuPDF) could not load or render a PDF |
| `VideoProcessingError` | `MediaProcessingError` | Either video backend could not probe a video or extract a frame |
| `UnsupportedFormatError` | `ValueError` | An unrecognized output format or backend selector was requested; carries `fmt` |
| `OrphanedThumbnail` | `Exception` | *(app-level)* A `ThumbnailFiles` row has no matching `FileIndex` record; carries `.thumbnail` and `.sha256` |
| `OrphanedFileIndex` | `Exception` | *(app-level)* A `FileIndex` record's `home_directory` is `None` (its directory was deleted); carries `.thumbnail`, `.file_index_id`, `.sha256` |

The first five are declared in `engine/exceptions.py`; the two marked *(app-level)* are
declared in `thumbnails/exceptions.py` because they reference the ORM model.

**`OrphanedThumbnail` and `OrphanedFileIndex`** tell the caller to delete the stale
`ThumbnailFiles` record. Every caller catches them and calls `exc.thumbnail.delete()`:
`thumbnail_dir` then serves the directory's generic icon, `thumbnail_file` returns
HTTP 400 ("File no longer exists in gallery."), and
`quickbbs.tasks.generate_missing_thumbnails()` skips the file.

---

### 4.2 `engine/base.py`

**What does this do?** Guarantees that no matter which underlying tool actually draws a
thumbnail, every one of them can be asked to do the job in exactly the same way.

**What is its purpose?** Defines `AbstractBackend`, the abstract base every backend
implements, with a uniform three-method contract:

```python
class AbstractBackend(ABC):
    def process_from_file(self, file_path, sizes, output_format, quality) -> ThumbnailResult: ...
    def process_from_memory(self, source_bytes, sizes, output_format, quality) -> ThumbnailResult: ...
    def process_data(self, pil_image, sizes, output_format, quality) -> ThumbnailResult: ...
```

Every backend returns a `ThumbnailResult` (defined beside `AbstractBackend`):
`images` maps each size name (`"small"`, `"medium"`, `"large"`) to the encoded bytes,
`format` names their encoding, and `duration` is the source video's length in seconds,
or `None` for a still image or PDF. This shared return value is what lets
`FastImageProcessor` (Section 4.3) call any backend identically regardless of input source.

---

### 4.3 `engine/engine.py`

**What does this do?** Decides which tool should actually generate a given thumbnail,
favoring a GPU-accelerated option when it's available, and otherwise falling back
automatically to the cross-platform thumbnail system.

**What is its purpose?** Defines `FastImageProcessor`, the central dispatcher: selects
the right backend for a file and caches backend instances so each selector's backend is
constructed once.

**Backend selectors** (`BackendType`): `"image"`, `"coreimage"`, `"auto"` (still
images); `"video"`, `"corevideo"` (video); `"pdf"`, `"pymupdf"`, `"pdfkit"` (PDF). The
three auto-selecting variants each check `macintosh_optimizations_enabled()` (reads
`engine.config.config.macintosh_optimizations`, which `thumbnails/apps.py` populates
from `settings.MACINTOSH_OPTIMIZATIONS` at startup) and whether the relevant macOS
framework import succeeded, falling back to the cross-platform backend if either check
fails (Section 1.2).
`"auto"` and `"pdf"` add a third condition on top of those two: the process must be
running on Apple Silicon specifically, not just any Mac — an Intel Mac with
`MACINTOSH_OPTIMIZATIONS` enabled and Core Image or PDFKit importable still falls back
to `ImageBackend`/`PDFBackend`. `"corevideo"` carries no such Apple Silicon check, so it
selects `AVFoundationVideoBackend` on any Mac where AVFoundation imports and the
setting is on. `"pdfkit"` ignores the setting and the processor type: it selects
`PDFKitBackend` whenever PDFKit imports, and `PDFBackend` otherwise. `"coreimage"` ignores
both too, and raises `ImportError` when Core Image is unavailable.

These rules live in the `_BACKEND_RULES` table, one entry per selector, each returning
the backend name to construct. If constructing the chosen backend raises `ImportError`,
`RuntimeError` or `OSError` (for example, no Metal device), `"auto"` constructs
`ImageBackend` instead; every other selector lets the error propagate.

**`_backend_cache`** — a module-level dictionary keyed by backend selector and
protected by `_backend_lock`, so each selector's backend is constructed once per
process and reused by every request that names that selector. Two selectors that
resolve to the same class (for example `"auto"` and `"image"` on a machine without
Core Image) each hold their own instance.

**Fork safety.** `os.register_at_fork` wires the backend and processor caches to clear
themselves in a forked child, discarding any `CoreImageBackend` whose Metal command
queue references the parent's now-dead Mach ports — using such a backend after a fork
can silently produce blank renders instead of raising, so the caches must not survive
the fork.

**Public entry points:**

| Function | Description |
|---|---|
| `create_thumbnails_from_path(file_path, sizes, output, quality, backend)` | Main entry: resolves the backend, calls `process_from_file()` |
| `create_thumbnails_from_pil(pil_image, sizes, ...)` | For an already-decoded PIL image (avoids a second decode) |
| `create_thumbnails_from_bytes(image_bytes, sizes, ...)` | For in-memory bytes |
| `resolve_backend_name(backend, sizes)` | Returns the class name the selector resolves to, e.g. `"CoreImageBackend"`; `quickbbs.tasks` logs it |
| `get_video_info(path)` | Video metadata (`duration`, `width`, `height`, `fps`, `codec`, `format`). Uses the AVFoundation probe on macOS whenever pyobjc imports, regardless of `macintosh_optimizations`, and retries with the ffmpeg probe when AVFoundation raises `MediaProcessingError` |
| `is_all_white_thumbnail(small_thumb)` | True when a blob decodes to an entirely white RGB or greyscale image |
| `clear_backend_caches(force_gc)` | Clears both caches; with `force_gc=True` (the default) also runs a full garbage collection — releases accumulated Core Image GPU resources |
| `get_cache_stats()` | Reports current cache sizes, for deciding when to call `clear_backend_caches()` |

The three `create_thumbnails_*` functions return the backend's `ThumbnailResult`; read a
thumbnail as `result.images["small"]`. `clear_backend_caches(force_gc=True)` reports
memory freed as 0 MB on Windows, where the `resource` module does not exist.

The engine has no default sizes: every entry point takes `sizes`, and QuickBBS passes
`settings.IMAGE_SIZE`.

---

### 4.4 `engine/pil_thumbnails.py`

**What does this do?** Makes sure ordinary images always get a thumbnail, on any
machine, even one with no Apple-specific acceleration installed at all.

**What is its purpose?** Defines `ImageBackend`, the cross-platform PIL/Pillow
backend — the fallback everywhere (Section 1.2), and on non-macOS systems the only backend
used for images.

**`convert_image_for_format(img, output_format)`** — module-level function, reused by
every other backend that needs JPEG-safe output: RGBA/P/LA images are composited onto a
white background for JPEG (which has no alpha channel), other exotic modes convert to
RGB, and everything else passes through unchanged.

**`render_sizes()`** auto-orients via EXIF, then generates sizes largest-first,
resizing each from the *previous* thumbnail rather than from a fresh copy of the
original — the source for the medium thumbnail is the already-downsampled large one, and
so on. Resizing a smaller image is faster, and the quality lost by resizing an
already-downsampled image is small next to the JPEG encoding each thumbnail receives.
Each size is encoded once from its in-memory image, so no JPEG is decoded and
re-encoded along the chain.
Resizing uses `BICUBIC`, chosen over `LANCZOS` for its lower per-call cost at thumbnail
sizes.

---

### 4.5 `engine/pdf_thumbnails.py`

**What does this do?** Lets a PDF show a preview of its first page in the gallery, on
any machine, without needing Apple's own PDF renderer.

**What is its purpose?** Defines `PDFBackend`, the cross-platform PDF backend using
PyMuPDF (imported as `pymupdf`) — used on non-macOS platforms, or whenever `PDFKitBackend` is
unavailable or not selected.

Renders page 0 once at a zoom factor sized for the largest requested thumbnail (10%
over the minimum needed to fit, for a small quality buffer), converts the pixmap
straight to a PIL `Image` with no intermediate file encoding, then delegates to
`ImageBackend.render_sizes()` for the actual resizing. `_calculate_optimal_zoom`
is cached with `cachetools` (`_zoom_cache`), since PDF pages sharing the same dimensions (common within one
document) don't need the division repeated. A missing file raises `FileNotFoundError`;
a failure opening or rendering the PDF (PyMuPDF's errors, or PIL's `OSError`/`ValueError`)
is re-raised as `PDFProcessingError`.

`process_data()` raises `NotImplementedError`: it receives an already-decoded PIL
image, which cannot hold a PDF page to render.

---

### 4.6 `engine/pdfkit_thumbnails.py`

**What does this do?** Produces PDF page previews faster on a Mac, by handing the work
off to Apple's own PDF and graphics frameworks instead of a general-purpose library.

**What is its purpose?** Defines `PDFKitBackend`, the macOS-native PDF backend using
Apple's PDFKit, GPU-accelerated by delegating the resize step to `CoreImageBackend`
(Section 4.7). Import-guarded by `PDFKIT_AVAILABLE`; `__init__` raises `ImportError` if the
framework isn't present.

Renders the page to an `NSImage` via PDFKit's own thumbnail method, converts it to TIFF
bytes (the only bridge between `NSImage` and Core Image's `CIImage`, and lossless so no
quality is lost in the conversion), then hands the resulting `CIImage` to
`CoreImageBackend.render_sizes()` for GPU-accelerated resizing and encoding.

**AppKit suppression.** Both this backend and `AVFoundationVideoBackend` call
`hide_dock_icon()` (`core_image_thumbnails.py`) on init, which sets
`NSApplicationActivationPolicyProhibited` when AppKit is installed — without it, PDFKit or AVFoundation
can trigger AppKit's GUI layer and pop a dock icon for what is meant to be a headless
Django worker process.

---

### 4.7 `engine/core_image_thumbnails.py`

**What does this do?** Does the actual GPU-accelerated pixel-crunching that the other
Mac-native backends rely on, so resizing and encoding work is written once rather than
three times.

**What is its purpose?** Defines `CoreImageBackend`, the GPU-accelerated image backend
using Apple's Core Image, and the sub-processor both `PDFKitBackend` and
`AVFoundationVideoBackend` delegate their resizing to.

**Fork-safe Metal device.** The Metal GPU device is created once and cached per
process, keyed by the creating PID. After `os.fork()`, a child inherits the parent's
device pointer but the underlying Mach ports are already dead; the cache detects the PID
mismatch and recreates the device rather than trying to use the stale one.

**`kCIContextCacheIntermediates: False`.** Core Image's `CIContext` normally caches
intermediate filter results, on the assumption the same image will be processed
repeatedly. Every thumbnail here is a different image, so that cache would only ever
grow, accumulating GPU memory with no hit ever landing — disabling it is what keeps
batch thumbnail runs from exhausting GPU memory.

**Direct bitmap rendering.** `_render_to_bytes` uses
`render_toBitmap_rowBytes_bounds_format_colorSpace_` rather than
`createCGImage:fromRect:`, because the latter allocates an IOSurface (GPU shared
memory) that leaks in a long-running worker; rendering straight into a CPU-side
`bytearray` keeps everything ordinarily garbage-collected instead. Extent dimensions are
floored (not ceiled) before allocating that buffer, since Lanczos scaling produces
fractional extents and a mismatched buffer width shears every row of the render — floor
crops the sub-pixel fringe rather than padding with undefined content.

**`autorelease_pool()`.** Every entry point wraps its Objective-C object creation in
this context manager; without it, autoreleased objects (`CIImage`, `CGImage`, `NSData`)
accumulate in the thread's pool and are never drained in a long-running worker. Sizes
are processed in a nested inner pool so each one drains as soon as it's done, rather
than holding everything until the whole batch completes.

---

### 4.8 `engine/video_thumbnails.py`

**What does this do?** Lets a video show a representative freeze-frame in the gallery,
on any machine, without needing Apple's own video framework.

**What is its purpose?** Defines `VideoBackend`, the cross-platform video backend using
`ffmpeg-python` via subprocess — the fallback when AVFoundation is unavailable or not
selected.

Captures a single frame at `duration / 2` (the midpoint) with `ffmpeg`'s `scale` and
`pad` filters doing aspect-preserving letterbox/pillarbox in the same subprocess call,
then delegates resizing to `ImageBackend`. `read_video_info()` (via `ffmpeg.probe()`)
supplies `duration`, `width`, `height`, `fps`, `codec`, and `format`; an empty-stdout
result from `ffmpeg` (corrupt stream, seek past the last decodable frame) raises
`VideoProcessingError` with ffmpeg's own stderr rather than letting PIL fail later on
empty bytes with an unhelpful decode error.

---

### 4.9 `engine/avfoundation_video_thumbnails.py`

**What does this do?** Produces video freeze-frame previews faster on a Mac, by reading
the video directly rather than handing it off to a separate helper program.

**What is its purpose?** Defines `AVFoundationVideoBackend`, the macOS-native video
backend using AVFoundation — chosen by the `"corevideo"` selector over `VideoBackend`
because frame extraction happens in-process via Objective-C, with no subprocess spawn.
Only decodes formats macOS itself has codecs for (MP4/MOV/M4V and similar); WMV, FLV,
and MPEG-1 raise `VideoProcessingError` ("No video tracks found in file").

`setAppliesPreferredTrackTransform_(True)` is set on the image generator specifically
to correct rotation metadata — without it, a portrait video shot on a phone would
extract sideways. The extracted frame becomes a `CIImage` and is handed to
`CoreImageBackend.render_sizes()` for the same GPU-accelerated resize path PDFKit
uses.

---

### 4.10 `models.py`

**What does this do?** Holds the actual thumbnail pictures in the database itself,
one set per distinct piece of file content, so the gallery never has to regenerate the
same picture twice.

**What is its purpose?** Defines `ThumbnailFiles`, the single ORM model, one row per
distinct file content (Section 1.4), looked up by `sha256_hash`. The primary key is the
auto-increment `id`.

| Field | Type | Notes |
|---|---|---|
| `sha256_hash` | `CharField`, unique, indexed, nullable | Content SHA256 of the source file |
| `small_thumb` / `medium_thumb` / `large_thumb` | `BinaryField(null=True)` | JPEG bytes; `NULL` is the only "no data" state — a `CheckConstraint` (`thumbnails_no_empty_blobs`) forbids empty-bytes rows so nothing can silently escape the missing-thumbnail index below |

**Partial indexes:**

| Index | Condition | Purpose |
|---|---|---|
| `thumbnails_has_small_idx` | `small_thumb IS NOT NULL` (excluding `b""`) | Fast existence check — only `small_thumb` drives generation decisions; medium/large existence is never queried standalone |
| `thumbnails_small_missing_idx` | `small_thumb IS NULL` | Lets missing-thumbnail lookups read the small set of not-yet-generated rows directly, instead of probing this table once per file in a directory |

This app keeps no lookup cache of its own for `ThumbnailFiles` rows — see Section 1.3 for the
cache it depends on instead.

---

#### `get_or_create_thumbnail_record(file_sha256, suppress_save, prefetch_related_thumbnail, select_related_fileindex)`

**What does this do?** Answers "does this file have a thumbnail yet, and if not, make
one" — the one place generation actually happens, however a request got there.

**What is its purpose?** `ThumbnailFiles` static method: the central creation/retrieval
path, called by both HTTP views' slow path (Section 4.11) once the fast path has established
that a thumbnail is missing.

1. Acquire a per-SHA `pg_advisory_xact_lock` (derived from the first 8 bytes of the
   SHA256) inside a `transaction.atomic()` block — this serializes concurrent requests
   for the same file's thumbnail across every worker process, not just threads within
   one.
2. `get_or_create()` the `ThumbnailFiles` row, deferring the blob columns — existence is
   answered separately below, so the row lookup never pulls thumbnail bytes across the
   wire just to check whether they're populated.
3. Link every unlinked `FileIndex` sharing this SHA to the row (`FileIndex.link_to_thumbnail`).
4. Re-check for an already-populated `small_thumb` — another worker may have generated
   it while this one waited for the lock — and return immediately if so.
5. Resolve a `FileIndex` record to generate from, repairing an orphaned link where
   possible and raising `OrphanedThumbnail`/`OrphanedFileIndex` where it can't be
   (Section 4.1). It raises `ValueError` when matching `FileIndex` records exist but
   cannot be linked.
6. If that file is already marked generic, return without generating unless its
   directory's `cache_invalidated` is set; a rescanned directory gets one retry, and a
   successful retry clears the generic mark on every copy of the content.
7. Dispatch by filetype, with the selector `"auto"` for an image, `"corevideo"` for a
   video and `"pdf"` for a PDF; check the small thumbnail isn't empty, and store the
   three blobs. A file whose type never gets a rendered thumbnail (text, archives, and
   similar) is marked generic here and no generation is attempted at all (Section 1.5).
   A link file (`.link`, `.alias`) is skipped entirely — no blobs, no generic mark; the
   view layer resolves it to the linked directory's cover thumbnail instead
   (Section 4.11).

**GPU-corruption safeguard.** Core Image can produce an all-white thumbnail instead of
raising, most often in a forked child still using a Metal command queue whose Mach
ports died with the parent (Section 4.3). The safeguard only runs when
`settings.MAC_OPTIMIZATION_WHITECHECK` is turned on (`False` by default) — otherwise a
freshly generated thumbnail is stored as-is with no white check at all. When it is on
and a freshly generated `small_thumb` is both suspiciously small
(`< settings.SMALL_THUMBNAIL_SAFEGUARD_SIZE`) and entirely white, it is regenerated
exactly once with the matching cross-platform backend, and that result is kept
unconditionally — a genuinely blank source (e.g. an actually-blank PDF page) is legitimate
content, not corruption, so there is no retry loop past the one.

**Failure handling** distinguishes three cases: a moved/deleted file
(`FileNotFoundError`) marks that one `FileIndex` `delete_pending` rather than touching
other copies of the same content; a decode failure the backend itself raises
(`MediaProcessingError`) marks every `FileIndex` sharing the SHA generic and logs at
`WARNING`, which includes every `PDFBackend` failure (Section 4.5); any other exception
does the same and logs at `ERROR` with a traceback. That last case includes an empty
result (`ThumbnailGenerationError`). In every one of these cases the
method returns the (unpopulated) `thumbnail` record rather than raising — the caller's
fallback to the filetype's generic icon (Section 1.5) is what actually surfaces the failure to
the person browsing.

---

#### `send_thumbnail(filename_override, fext_override, size, index_data_item)`

**What does this do?** Turns a stored thumbnail into the actual HTTP response the
browser displays — or, transparently, the generic icon instead, if that's what this
file resolves to.

**What is its purpose?** Instance method on `ThumbnailFiles`: returns a `FileResponse`
for one requested size (`small`, `medium`, or `large`).

If the resolved `FileIndex` is marked generic (either `is_generic_icon` or
`filetype.generic`), delegates straight to the filetype's own fallback icon instead of
this file's thumbnail — it never reads `small_thumb`/`medium_thumb`/`large_thumb` in
that case. Otherwise it builds a fresh `io.BytesIO` from the requested blob on every
call — Django closes the stream after sending, so a cached stream would already be
exhausted on the second request — and raises `ThumbnailGenerationError` if the blob is
empty rather than serving nothing silently.

---

### 4.11 `views.py`

**What does this do?** Answers the actual web requests a browser makes when it needs
to show a thumbnail image, for either a single file or a whole directory.

**What is its purpose?** Defines the HTTP views — `thumbnail_file` and
`thumbnail_dir` — that resolve a request to a stored thumbnail (generating one first
if needed) and return it as an image response.

#### `thumbnail_file(request, sha256)`

**What does this do?** Serves the thumbnail image for one specific file — the `<img>`
`src` every gallery thumbnail actually points at — generating it first if nobody has
asked for it before.

**What is its purpose?** View function: resolves `sha256` to a stored thumbnail blob of
the requested size and returns it as a `FileResponse`, generating the thumbnail on
demand if it doesn't exist yet.

Splits into a read-only fast path and a generation-locked slow path:

- `_serve_existing_thumbnail()` resolves the `FileIndex` from the cached lookup (Section 1.3),
  honors the generic-icon and link short-circuits, and serves the requested blob size
  with a single-column `SELECT` — no advisory lock, no transaction. This is the
  steady-state path once a thumbnail already exists.
- Only when the record or the requested size is missing does the request fall through
  to `get_or_create_thumbnail_record()` (Section 4.10), which takes the transaction and
  advisory lock actually needed to serialize generation. Splitting the two paths means
  the common case (thumbnail already generated) never pays the locking cost that only
  matters for the uncommon case (thumbnail doesn't exist yet).

A link file (`.link`, `.alias`) with a `virtual_directory` is never given a thumbnail of
its own — the view calls `thumbnail_dir()` for the directory it points at and returns
that response, on both the fast and slow paths.

---

#### `thumbnail_dir(request, dir_sha256)`

**What does this do?** Serves a directory's cover thumbnail — the image a folder shows
in the gallery before you open it.

**What is its purpose?** View function: resolves `dir_sha256` to a `DirectoryIndex`,
picks a cover image if one isn't already assigned, and returns that image's thumbnail
as a `FileResponse`.

1. If the directory already has a cached, valid thumbnail reference, try to serve it
   directly.
2. Otherwise, select a cover image via `DirectoryIndex.get_cover_image()`, in the
   order given in Section 1.5. If nothing is found, sync the directory from disk and
   try once more; if there is still nothing, serve the directory's generic icon.
3. Inside `transaction.atomic()`, assign the cover image to the directory and flag the
   file as its cover. Then, if the file has no `ThumbnailFiles` record, call
   `get_or_create_thumbnail_record()` (Section 4.10) — so a directory's first visit can
   still pay the generation cost, not just a file's first visit — and link the result
   in a second `transaction.atomic()`. An orphaned record (Section 4.1) is deleted and
   the generic icon is served.
4. Serve the resulting thumbnail; if serving raises `OSError`, `ValueError`,
   `AttributeError` or `ThumbnailGenerationError`, mark the directory generic and serve
   the filetype's generic icon instead of an error.

---

### 4.12 `admin.py`

**What does this do?** Gives a staff member a way to look at and export thumbnail data
in the Django administration site, without dumping raw unreadable binary data on
screen.

**What is its purpose?** Defines `AdminThumbnail_Files`, the standard `ModelAdmin` for
`ThumbnailFiles`. `small_thumb`/`medium_thumb`/`large_thumb` are replaced in the
list and detail views by computed `sthumb`/`mthumb`/`lthumb` columns showing the first
25 bytes as a preview string — the raw blobs are unreadable and unnecessarily heavy to
render on an administration page. A `download_thumbnails` action bundles every size for the
selected rows into an in-memory ZIP, named `<sha256>_<size>.jpg`.

---

## 5. Concurrency and Safety

### PostgreSQL advisory lock

`pg_advisory_xact_lock`, keyed by (the first 8 bytes of) the content SHA256, is the
concurrency guard for thumbnail generation — per-SHA, transaction-scoped, and exclusive.
Two workers (even across separate processes, unlike a Python-level lock) generating the
same file's thumbnail serialize here; the second, after acquiring the lock, re-checks the
database and returns the already-generated result instead of re-running the backend —
check-lock-recheck, not check-then-act.

### Threading and fork safety

Backend instances are created once per selector under the module-level
`_backend_lock` in `engine/engine.py`, and keep no per-request state, so one instance
serves every thread. `CoreImageBackend` holds one long-lived `CIContext` shared by all
calls. `os.register_at_fork` (Section 4.3) clears both the processor and backend caches
in a forked child, since a `CoreImageBackend`'s Metal command queue does not survive a
fork.

### autorelease_pool

Every PyObjC entry point that creates Objective-C objects is wrapped in
`autorelease_pool()` (Section 4.7) — without it, those objects accumulate in the calling
thread's pool and are never drained in a long-running Django worker.

---

## 6. Module Structure Summary

The app is split in two: `engine/` is the framework-independent work layer, and
everything beside it is the Django integration. `engine/__init__.py` states that the
engine imports no Django, but `pdf_thumbnails.py` and `pdfkit_thumbnails.py` read
`django.conf.settings` and import `quickbbs.MonitoredCache` when they load; every other
engine module is Django-free.

```
thumbnails/
├── __init__.py
├── engine/                           # Django-free work layer
│   ├── __init__.py                   # Public API surface (__all__)
│   ├── config.py                     # EngineConfig — settings supplied by the application
│   ├── engine.py                     # FastImageProcessor: backend factory + dispatch,
│   │                                 #   get_video_info, is_all_white_thumbnail
│   ├── base.py                       # AbstractBackend ABC
│   ├── exceptions.py                 # Framework-independent exceptions
│   ├── pil_thumbnails.py             # ImageBackend: cross-platform PIL backend
│   ├── pdf_thumbnails.py             # PDFBackend: PyMuPDF cross-platform PDF backend
│   ├── pdfkit_thumbnails.py          # PDFKitBackend: macOS GPU PDF backend
│   ├── core_image_thumbnails.py      # CoreImageBackend: macOS GPU image backend
│   ├── video_thumbnails.py           # VideoBackend: ffmpeg cross-platform video backend
│   ├── avfoundation_video_thumbnails.py  # AVFoundationVideoBackend: macOS native video
│   ├── benchmarks/
│   │   ├── thumbnail_benchmarks.py   # Standalone performance benchmarks — not imported by the app
│   │   └── README.md                 # Plus saved result files and sample output images
│   └── tests/
│       └── test_engine.py            # Plain pytest, no database; its PyMuPDF test loads Django settings (see above)
├── exceptions.py                     # ORM-coupled exceptions + re-exports of engine's
├── apps.py                           # ThumbnailsConfig.ready() → pushes settings into engine/config.py
├── models.py                         # ThumbnailFiles model + get_or_create_thumbnail_record
├── views.py                          # thumbnail_file, thumbnail_dir HTTP views
├── admin.py                          # AdminThumbnail_Files + download_thumbnails action
├── migrations/                       # 7 migrations (0001-0007)
└── tests/
    ├── test_thumbnail_engine.py      # Django-dependent tests only
    └── test_views.py
```
