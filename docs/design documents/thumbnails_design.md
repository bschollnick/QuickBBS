# thumbnails — Design Document

**Version:** 4.5
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

**See also:** [`thumbnails_erd.md`](thumbnails_erd.md) for the entity-relationship
diagram; [`thumbnails_exceptions.md`](thumbnails_exceptions.md) for the exception
taxonomy.

---

## 1. Guiding Principles

### 1.1 The database is easier to keep correct than a file cache would be

Carried down from [quickbbs §1.1](quickbbs_app_design.md#11-the-filesystem-is-the-source-of-truth-the-database-is-a-cache).
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
- **Consequence: one write path, transactionally.** Generation stores the thumbnail
  bytes on the same row, in the same transaction, as the rest of the bookkeeping
  `get_or_create_thumbnail_record()` already does (§4.10) — there is no second write
  (a file create) that can succeed while the first (the row update) fails, or vice
  versa, and nothing to fsync separately or clean up after a crash mid-write. A
  disk-cache design would need to make that pair of writes atomic itself.
- **Consequence: no separate existence check to add.** Every thumbnail request already
  needs the `ThumbnailFiles`/`FileIndex` row anyway, to resolve the generic-icon and
  link short-circuits (§1.5, §4.11) before any bytes are served. Storing the bytes on
  that same row means serving one doesn't cost a second I/O subsystem on top of the
  query that was already required — a disk cache would add a file `open()`/`read()`
  after the same row lookup, not replace it.
- **Consequence: read cost stays proportional to size.** Small thumbnails
  are generally stored inline and retrieved with the row itself — the cheapest case.
  Medium and large thumbnails are not inline and are fetched separately from the row,
  so they don't get that same discount. The case for the database here isn't that
  every read is the fastest possible one. It's that generation collapses into one
  transactional write. Invalidation also becomes an easier process since the database
  already manages this by design.

### 1.2 GPU acceleration is an accelerator, never a requirement

Carried down from [frontend §1.3](frontend_design.md#13-self-hosted-format-agnostic-cross-platform).
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
  installed. Explicitly requesting a macOS backend by name is the only way to demand it
  outright; automatic selection always has a working fallback.

### 1.3 A cache must never claim something doesn't exist

Carried down from [quickbbs §1.2](quickbbs_app_design.md#12-a-cache-must-never-claim-something-doesnt-exist).
This app doesn't keep a cache of its own for thumbnail lookups; it depends on
`FileIndex.get_by_sha256()` in `quickbbs/fileindex.py`, whose cache never stores an
absence — a lookup that finds nothing simply isn't cached, so a thumbnail generated
moments later by a concurrent request is found on the very next lookup rather than
staying invisible until an entry ages out. `thumbnail2_file`'s fast path (§4.11) reads
through this cache on every request.

### 1.4 Identical files share one thumbnail

Carried down from [quickbbs §1.3](quickbbs_app_design.md#13-identical-files-are-the-same-file).
`ThumbnailFiles` is keyed by the source file's content SHA256, not by any particular
copy's path — every `FileIndex` row with identical bytes, wherever it lives in the
gallery, points at the same thumbnail row through `new_ftnail`. A thumbnail is generated
once per distinct piece of content, however many times that content appears.

### 1.5 Every file has a visual representation

A gallery page shows an image for every entry on it. For an image, PDF, or video, that
image is a real rendered thumbnail of the file's own content (§4.4–§4.9). For a
directory, it's a cover image selected from one of the files inside it —
`thumbnail2_dir()` (§4.11) prefers a file named `cover` or `title`, then falls back to
any thumbnailable file in the directory — so browsing a gallery of directories shows an
actual preview of what's inside each one, not a folder icon.

- **The rule.** Every file resolves to *some* displayable image.
  - Most files: a rendered thumbnail of their own content.
  - Directories: a cover image proxied from a file inside them.
  - The remaining cases fall back to the filetype's own generic icon (e.g. the Acrobat
    icon for a PDF, a generic image icon for an image file) — either because the
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

- **Does a thumbnail exist?** — `ThumbnailFiles`, keyed by content SHA256 (§1.4)
- **How do I generate one?** — a pluggable backend system dispatched by
  `FastImageProcessor`
- **How do I serve one?** — `ThumbnailFiles.send_thumbnail()` and the two HTTP views

Thumbnails are stored as raw JPEG bytes across three columns (`small_thumb`,
`medium_thumb`, `large_thumb`) on one row per distinct file content (§1.1); there is no
on-disk thumbnail cache.

---

## 3. High-Level Architecture

```
HTTP request
    └── thumbnail2_file(sha256)  /  thumbnail2_dir(dir_sha256)
              │
              ▼
    ThumbnailFiles.get_or_create_thumbnail_record(sha256)
              │  pg_advisory_xact_lock (per-SHA)
              │  prevents duplicate generation under concurrency
              │
              ├── record exists + small_thumb populated → send_thumbnail()
              │
              └── record missing / small_thumb absent
                        │
                        ▼
              create_thumbnails_from_path(file_path, sizes, backend)
                        │
                        │  backend selection (once per backend type, cached)
                        │
                        ├── CoreImageBackend   (macOS GPU, images — §1.2)
                        ├── PDFKitBackend      (macOS GPU, PDFs)
                        ├── AVFoundationVideoBackend  (macOS, video)
                        ├── ImageBackend (PIL)  (cross-platform, images)
                        ├── PDFBackend (PyMuPDF) (cross-platform, PDFs)
                        └── VideoBackend (ffmpeg) (cross-platform, video)
                        │
                        ▼
              ThumbnailFiles (model)
              small_thumb / medium_thumb / large_thumb  ← bytes stored in DB
              FileIndex.new_ftnail  ← FK linked
```

---

## 4. Component Reference

### 4.1 `exceptions.py`

**What does this do?** Gives every part of the app a shared, specific vocabulary for
what went wrong when a thumbnail couldn't be made or served, instead of everything
looking like a generic error.

**What is its purpose?** Declares every thumbnail-specific exception class in one
module, so callers can catch them without importing the backend or model modules that
raise them.

All thumbnail-specific exceptions are declared here so callers can catch them without
importing implementation modules.

| Exception | Inherits | Purpose |
|---|---|---|
| `ThumbnailGenerationError` | `Exception` | The generation pipeline ran but produced an invalid result — empty output, GPU-corrupted (all-white) image, or unsupported input |
| `MediaProcessingError` | `Exception` | A backend failed to load or decode a file; carries `file_path` |
| `PDFProcessingError` | `MediaProcessingError` | PDF-specific decode/render failure |
| `VideoProcessingError` | `MediaProcessingError` | Video-specific decode/extraction failure |
| `UnsupportedFormatError` | `ValueError` | An unrecognized output format was requested; carries `fmt` |
| `OrphanedThumbnail` | `Exception` | A `ThumbnailFiles` row has no matching `FileIndex` record; carries `.thumbnail` and `.sha256` |
| `OrphanedFileIndex` | `Exception` | A `FileIndex` record's `home_directory` is `None` (its directory was deleted); carries `.thumbnail`, `.file_index_id`, `.sha256` |

**`OrphanedThumbnail` and `OrphanedFileIndex`** are not error conditions in the
traditional sense — they are signals telling the caller to delete the stale record and
fall back to the generic icon. Both views catch them explicitly and call
`exc.thumbnail.delete()`.

---

### 4.2 `Abstractbase_thumbnails.py`

**What does this do?** Guarantees that no matter which underlying tool actually draws a
thumbnail, every one of them can be asked to do the job in exactly the same way.

**What is its purpose?** Defines `AbstractBackend`, the abstract base every backend
implements, with a uniform three-method contract:

```python
class AbstractBackend(ABC):
    def process_from_file(self, file_path, sizes, output_format, quality) -> dict[str, bytes]: ...
    def process_from_memory(self, image_bytes, sizes, output_format, quality) -> dict[str, bytes]: ...
    def process_data(self, pil_image, sizes, output_format, quality) -> dict[str, bytes]: ...
```

Return values are a `dict` keyed by size name (`"small"`, `"medium"`, `"large"`) mapping
to raw image bytes in the requested format; video and PDF backends add `"duration"`
and/or `"format"` keys. This shared shape is what lets `FastImageProcessor` (§4.3) call
any backend identically regardless of input source.

---

### 4.3 `thumbnail_engine.py`

**What does this do?** Decides which tool should actually generate a given thumbnail,
favoring a GPU-accelerated option when it's available, and otherwise falling back
automatically to the cross-platform thumbnail system.

**What is its purpose?** Defines `FastImageProcessor`, the central dispatcher: selects
the right backend for a file and caches backend instances so each is constructed once.

**Backend selectors** (`BackendType`): `"image"`, `"coreimage"`, `"auto"` (still
images); `"video"`, `"corevideo"` (video); `"pdf"`, `"pymupdf"`, `"pdfkit"` (PDF). The
three auto-selecting variants each check `macintosh_optimizations_enabled()` (reads
`settings.MACINTOSH_OPTIMIZATIONS`) and whether the relevant macOS framework import
succeeded, falling back to the cross-platform backend if either check fails (§1.2).
`"auto"` and `"pdf"` add a third condition on top of those two: the process must be
running on Apple Silicon specifically, not just any Mac — an Intel Mac with
`MACINTOSH_OPTIMIZATIONS` enabled and Core Image or PDFKit importable still falls back
to `ImageBackend`/`PDFBackend`. `"corevideo"` carries no such Apple Silicon check, so it
selects `AVFoundationVideoBackend` on any Mac where AVFoundation imports and the
setting is on. Explicit requests (`"coreimage"`, `"pdfkit"`) are never gated by any of
this — asking for a macOS backend by name either returns it or raises `ImportError` if
it's genuinely unavailable.

**`_backend_cache`** — a class-level `dict[str, AbstractBackend]` protected by a
`threading.Lock`, so each backend type is constructed once per process and reused
across every request that resolves to it.

**Fork safety.** `os.register_at_fork` wires the backend and processor caches to clear
themselves in a forked child, discarding any `CoreImageBackend` whose Metal command
queue references the parent's now-dead Mach ports — using such a backend after a fork
can silently produce blank renders instead of raising, so the caches must not survive
the fork.

**Public entry points:**

| Function | Description |
|---|---|
| `create_thumbnails_from_path(file_path, sizes, backend, output, quality)` | Main entry: resolves the backend, calls `process_from_file()` |
| `create_thumbnails_from_pil(pil_image, sizes, ...)` | For an already-decoded PIL image (avoids a second decode) |
| `create_thumbnails_from_bytes(image_bytes, sizes, ...)` | For in-memory bytes |
| `clear_backend_caches(force_gc)` | Clears both caches; optionally forces a GC pass — releases accumulated Core Image GPU resources |
| `get_cache_stats()` | Reports current cache sizes, for deciding when to call `clear_backend_caches()` |

Default sizes come from `settings.IMAGE_SIZE`.

---

### 4.4 `pil_thumbnails.py`

**What does this do?** Makes sure ordinary images always get a thumbnail, on any
machine, even one with no Apple-specific acceleration installed at all.

**What is its purpose?** Defines `ImageBackend`, the cross-platform PIL/Pillow
backend — the fallback everywhere (§1.2), and on non-macOS systems the only backend
used for images.

**`convert_image_for_format(img, output_format)`** — module-level function, reused by
every other backend that needs JPEG-safe output: RGBA/P/LA images are composited onto a
white background for JPEG (which has no alpha channel), other exotic modes convert to
RGB, and everything else passes through unchanged.

**`_process_pil_image()`** auto-orients via EXIF, then generates sizes largest-first,
resizing each from the *previous* thumbnail rather than from a fresh copy of the
original — the source for the medium thumbnail is the already-downsampled large one, and
so on. This is a deliberate speed trade (resizing a smaller image is faster) accepted
because sequential downsampling from largest to smallest loses negligible quality
compared to the increment already introduced by lossy JPEG re-encoding at each step.
Resizing uses `BICUBIC`, chosen over `LANCZOS` for its lower per-call cost at thumbnail
sizes.

---

### 4.5 `pdf_thumbnails.py`

**What does this do?** Lets a PDF show a preview of its first page in the gallery, on
any machine, without needing Apple's own PDF renderer.

**What is its purpose?** Defines `PDFBackend`, the cross-platform PDF backend using
PyMuPDF (`fitz`) — used on non-macOS platforms, or whenever `PDFKitBackend` is
unavailable or not selected.

Renders page 0 once at a zoom factor sized for the largest requested thumbnail (10%
over the minimum needed to fit, for a small quality buffer), converts the pixmap
straight to a PIL `Image` with no intermediate file encoding, then delegates to
`ImageBackend._process_pil_image()` for the actual resizing. `_calculate_optimal_zoom`
is `@lru_cache`d, since PDF pages sharing the same dimensions (common within one
document) don't need the division repeated.

`process_data()` raises `NotImplementedError` — there is no PDF-bytes-to-PIL-Image
conversion path that doesn't already require rendering a page, which defeats the point
of accepting a pre-decoded PIL image.

---

### 4.6 `pdfkit_thumbnails.py`

**What does this do?** Produces PDF page previews faster on a Mac, by handing the work
off to Apple's own PDF and graphics frameworks instead of a general-purpose library.

**What is its purpose?** Defines `PDFKitBackend`, the macOS-native PDF backend using
Apple's PDFKit, GPU-accelerated by delegating the resize step to `CoreImageBackend`
(§4.7). Import-guarded by `PDFKIT_AVAILABLE`; `__init__` raises `ImportError` if the
framework isn't present.

Renders the page to an `NSImage` via PDFKit's own thumbnail method, converts it to TIFF
bytes (the only bridge between `NSImage` and Core Image's `CIImage`, and lossless so no
quality is lost in the conversion), then hands the resulting `CIImage` to
`CoreImageBackend._process_ci_image()` for GPU-accelerated resizing and encoding.

**AppKit suppression.** Both this backend and `AVFoundationVideoBackend` set
`NSApplicationActivationPolicyProhibited` on init — without it, PDFKit or AVFoundation
can trigger AppKit's GUI layer and pop a dock icon for what is meant to be a headless
Django worker process.

---

### 4.7 `core_image_thumbnails.py`

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

### 4.8 `video_thumbnails.py`

**What does this do?** Lets a video show a representative freeze-frame in the gallery,
on any machine, without needing Apple's own video framework.

**What is its purpose?** Defines `VideoBackend`, the cross-platform video backend using
`ffmpeg-python` via subprocess — the fallback when AVFoundation is unavailable or not
selected.

Captures a single frame at `duration / 2` (the midpoint) with `ffmpeg`'s `scale` and
`pad` filters doing aspect-preserving letterbox/pillarbox in the same subprocess call,
then delegates resizing to `ImageBackend`. `_get_video_info()` (via `ffmpeg.probe()`)
supplies `duration`, `width`, `height`, `fps`, `codec`, and `format`; an empty-stdout
result from `ffmpeg` (corrupt stream, seek past the last decodable frame) raises
`VideoProcessingError` with ffmpeg's own stderr rather than letting PIL fail later on
empty bytes with an unhelpful decode error.

---

### 4.9 `avfoundation_video_thumbnails.py`

**What does this do?** Produces video freeze-frame previews faster on a Mac, by reading
the video directly rather than handing it off to a separate helper program.

**What is its purpose?** Defines `AVFoundationVideoBackend`, the macOS-native video
backend using AVFoundation — preferred over `VideoBackend` on macOS because frame
extraction happens in-process via Objective-C, with no subprocess spawn.
Only decodes formats macOS itself has codecs for (MP4/MOV/M4V and similar); WMV, FLV,
and MPEG-1 raise `VideoProcessingError` ("No video tracks found").

`setAppliesPreferredTrackTransform_(True)` is set on the image generator specifically
to correct rotation metadata — without it, a portrait video shot on a phone would
extract sideways. The extracted frame becomes a `CIImage` and is handed to
`CoreImageBackend._process_ci_image()` for the same GPU-accelerated resize path PDFKit
uses.

---

### 4.10 `models.py`

**What does this do?** Holds the actual thumbnail pictures in the database itself,
one set per distinct piece of file content, so the gallery never has to regenerate the
same picture twice.

**What is its purpose?** Defines `ThumbnailFiles`, the single ORM model, one row per
distinct file content (§1.4), keyed by `sha256_hash`.

| Field | Type | Notes |
|---|---|---|
| `sha256_hash` | `CharField`, unique, indexed | Content SHA256 of the source file |
| `small_thumb` / `medium_thumb` / `large_thumb` | `BinaryField(null=True)` | JPEG bytes; `NULL` is the only "no data" state — a `CheckConstraint` (`thumbnails_no_empty_blobs`) forbids empty-bytes rows so nothing can silently escape the missing-thumbnail index below |

**Partial indexes:**

| Index | Condition | Purpose |
|---|---|---|
| `thumbnails_has_small_idx` | `small_thumb IS NOT NULL` (excluding `b""`) | Fast existence check — only `small_thumb` drives generation decisions; medium/large existence is never queried standalone |
| `thumbnails_small_missing_idx` | `small_thumb IS NULL` | Lets missing-thumbnail lookups read the small set of not-yet-generated rows directly, instead of probing this table once per file in a directory |

This app keeps no lookup cache of its own for `ThumbnailFiles` rows — see §1.3 for the
cache it depends on instead.

---

#### `get_or_create_thumbnail_record(file_sha256, suppress_save, prefetch_related_thumbnail, select_related_fileindex)`

**What does this do?** Answers "does this file have a thumbnail yet, and if not, make
one" — the one place generation actually happens, however a request got there.

**What is its purpose?** `ThumbnailFiles` static method: the central creation/retrieval
path, called by both HTTP views' slow path (§4.11) once the fast path has established
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
   possible and raising `OrphanedThumbnail`/`OrphanedFileIndex` where it can't be (§4.1).
6. Dispatch by filetype — image, movie, PDF, or otherwise generic — generate, validate
   the result isn't empty, and store the three blobs. A file whose type never gets a
   rendered thumbnail (text, archives, and similar) is marked generic here and no
   generation is attempted at all (§1.5). A link file (`.link`, `.alias`) is skipped
   entirely — no blobs, no generic mark; the view layer resolves it to the linked
   directory's cover thumbnail instead (§4.11).

**GPU-corruption safeguard.** Early Core Image acceleration, under heavy load, could
occasionally produce a corrupted all-white thumbnail; the underlying cause appears
resolved, but the safeguard remains as a defense-in-depth measure. It only runs when
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
(`MediaProcessingError`) marks every `FileIndex` sharing the SHA generic; any other
exception does the same and logs at `ERROR` rather than `WARNING`, since it's an
unclassified failure rather than a known data problem. In every one of these cases the
method returns the (unpopulated) `thumbnail` record rather than raising — the caller's
fallback to the filetype's generic icon (§1.5) is what actually surfaces the failure to
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

**What is its purpose?** Defines the HTTP views — `thumbnail2_file` and
`thumbnail2_dir` — that resolve a request to a stored thumbnail (generating one first
if needed) and return it as an image response.

#### `thumbnail2_file(request, sha256)`

**What does this do?** Serves the thumbnail image for one specific file — the `<img>`
`src` every gallery thumbnail actually points at — generating it first if nobody has
asked for it before.

**What is its purpose?** View function: resolves `sha256` to a stored thumbnail blob of
the requested size and returns it as a `FileResponse`, generating the thumbnail on
demand if it doesn't exist yet.

Splits into a read-only fast path and a generation-locked slow path:

- `_serve_existing_thumbnail()` resolves the `FileIndex` from the cached lookup (§1.3),
  honors the generic-icon and link short-circuits, and serves the requested blob size
  with a single-column `SELECT` — no advisory lock, no transaction. This is the
  steady-state path once a thumbnail already exists.
- Only when the record or the requested size is missing does the request fall through
  to `get_or_create_thumbnail_record()` (§4.10), which takes the transaction and
  advisory lock actually needed to serialize generation. Splitting the two paths means
  the common case (thumbnail already generated) never pays the locking cost that only
  matters for the uncommon case (thumbnail doesn't exist yet).

A link file (`.link`, `.alias`) with a `virtual_directory` is never given a thumbnail of
its own — the request is redirected to `thumbnail2_dir()` for the directory it points
at, on both the fast and slow paths.

---

#### `thumbnail2_dir(request, dir_sha256)`

**What does this do?** Serves a directory's cover thumbnail — the image a folder shows
in the gallery before you open it.

**What is its purpose?** View function: resolves `dir_sha256` to a `DirectoryIndex`,
picks a cover image if one isn't already assigned, and returns that image's thumbnail
as a `FileResponse`.

1. If the directory already has a cached, valid thumbnail reference, try to serve it
   directly.
2. Otherwise, select a cover image via `DirectoryIndex.get_cover_image()` — preferring
   files named `cover` or `title`, then any thumbnailable file — resyncing from disk
   first if nothing is found.
3. Assign the cover image and ensure its `ThumbnailFiles` record exists (calling
   `get_or_create_thumbnail_record()`, §4.10, if it doesn't — so a directory's first
   visit can still pay the generation cost, not just a file's first visit), wrapped in
   `transaction.atomic()` to avoid a race when multiple requests hit an uncached
   directory simultaneously.
4. Serve the resulting thumbnail; on any serving failure, mark the directory generic and
   fall back to the filetype's default icon rather than erroring out to the browser.

---

### 4.12 `admin.py`

**What does this do?** Gives a staff member a way to look at and export thumbnail data
in the Django admin site, without dumping raw unreadable binary data on screen.

**What is its purpose?** Defines `AdminThumbnail_Files`, the standard `ModelAdmin` for
`ThumbnailFiles`. `small_thumb`/`medium_thumb`/`large_thumb` are replaced in the
list and detail views by computed `sthumb`/`mthumb`/`lthumb` columns showing the first
25 bytes as a preview string — the raw blobs are unreadable and unnecessarily heavy to
render in the admin UI. A `download_thumbnails` admin action bundles every size for the
selected rows into an in-memory ZIP, named `<sha256>_<size>.jpg`.

---

### 4.13 `image_utils.py`

**What does this do?** Keeps older code working that was written before the current
backend system existed, without forcing every caller to be rewritten at once.

**What is its purpose?** A set of standalone legacy utility functions that predate the
backend system (§4.3–§4.9), still used by callers that haven't migrated to
`FastImageProcessor`.

| Function | Description |
|---|---|
| `pdf_to_pil(fspath)` | Renders page 0 with PyMuPDF, returns a PIL Image, or `None` if PIL raises a `UserWarning` while decoding the rendered page |
| `movie_to_pil(fspath)` | Seeks to the midpoint with PyAV, decodes the next frame; falls back to a "broken video" placeholder image on decode error |
| `movie_duration(fspath)` | Duration in whole seconds via PyAV stream metadata, or `None` if the first video stream has no readable duration |
| `image_to_pil(fspath, mem=False)` | Opens a raster image from a path or from bytes, returning `None` if the data can't be decoded |
| `return_image_obj(fs_path, memory=False)` | Dispatches to the three functions above based on a direct read of `filetypes.models.FILETYPE_DATA`; returns `None` for an extension that isn't a PDF, movie, or image type |
| `resize_pil_image(source_image, size, fext)` | Resizes with `LANCZOS`; saves PNG, falling back to JPEG on an encoding error |

`return_image_obj` reads `FILETYPE_DATA` directly rather than through
`filetypes.get_ftype_dict()` — a holdover reference from before that accessor existed,
kept only because this module's callers haven't been migrated yet.

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

Backend instances are created once per type under `FastImageProcessor._backend_lock`
and are otherwise stateless across calls, safe to use from multiple threads
concurrently. `os.register_at_fork` (§4.3) clears both the processor and backend caches
in a forked child, since a `CoreImageBackend`'s Metal command queue does not survive a
fork.

### autorelease_pool

Every PyObjC entry point that creates Objective-C objects is wrapped in
`autorelease_pool()` (§4.7) — without it, those objects accumulate in the calling
thread's pool and are never drained in a long-running Django worker.

---

## 6. Module Structure Summary

```
thumbnails/
├── __init__.py
├── exceptions.py                     # All thumbnail-specific exceptions
├── Abstractbase_thumbnails.py        # AbstractBackend ABC
├── thumbnail_engine.py               # FastImageProcessor: backend factory + dispatch
├── pil_thumbnails.py                 # ImageBackend: cross-platform PIL backend
├── pdf_thumbnails.py                 # PDFBackend: PyMuPDF cross-platform PDF backend
├── pdfkit_thumbnails.py              # PDFKitBackend: macOS GPU PDF backend
├── core_image_thumbnails.py          # CoreImageBackend: macOS GPU image backend
├── video_thumbnails.py               # VideoBackend: ffmpeg cross-platform video backend
├── avfoundation_video_thumbnails.py  # AVFoundationVideoBackend: macOS native video
├── models.py                         # ThumbnailFiles model + get_or_create_thumbnail_record
├── views.py                          # thumbnail2_file, thumbnail2_dir HTTP views
├── admin.py                          # AdminThumbnail_Files + download_thumbnails action
├── image_utils.py                    # Legacy utility functions (pre-backend-system)
├── benchmarks/
│   └── thumbnail_benchmarks.py       # Standalone backend performance benchmarks — not imported by the app
├── migrations/                       # 7 migrations (0001-0007)
├── tests/
│   ├── test_thumbnail_engine.py
│   └── test_views.py
└── SCRIPT_test_avfoundation_memory.py  # Standalone memory-leak probes — not imported by the app
    SCRIPT_test_memory_leak.py
    SCRIPT_test_pdfkit_memory.py
```
