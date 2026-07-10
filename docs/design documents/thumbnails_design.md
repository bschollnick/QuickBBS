# thumbnails — Design Document

**Version:** 3.99  
**Author:** Benjamin Schollnick  
**Last Updated:** 2026-04-11

---

## 1. Purpose

`thumbnails` is a Django application responsible for generating, storing, and serving
image thumbnails for every file type that QuickBBS supports. It answers three questions:

1. **Does a thumbnail exist?** (`ThumbnailFiles` model, keyed by SHA256)
2. **How do I generate one?** (pluggable backend system via `FastImageProcessor`)
3. **How do I serve one?** (`ThumbnailFiles.send_thumbnail()`, HTTP views)

Thumbnails are stored as raw JPEG bytes in three database columns (`small_thumb`,
`medium_thumb`, `large_thumb`). The database is the single source of truth; there is
no on-disk thumbnail cache directory.

---

## 2. High-Level Architecture

```
HTTP request
    └── thumbnail2_file(sha256)  /  thumbnail2_dir(dir_sha256)
              │
              ▼
    ThumbnailFiles.get_or_create_thumbnail_record(sha256)
              │  pg_advisory_xact_lock (per-SHA)
              │  prevents duplicate generation under concurrency
              │
              ├── record exists + all sizes populated → send_thumbnail()
              │
              └── record missing / sizes absent
                        │
                        ▼
              FastImageProcessor.create_thumbnails_from_path(file_path, sizes)
                        │
                        │  backend selection (once per SHA, cached)
                        │
                        ├── CoreImageBackend   (Apple Silicon GPU, preferred on macOS)
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
              fs_Cache_Tracking  ← thumbnail invalidated on change
```

---

## 3. Component Reference

### 3.1 `exceptions.py` — Exception Hierarchy

All thumbnail-specific exceptions are declared here so callers can catch them without
importing implementation modules.

| Exception | Inherits | Purpose |
|---|---|---|
| `ThumbnailGenerationError` | `Exception` | Base class for all thumbnail failures |
| `MediaProcessingError` | `ThumbnailGenerationError` | General media (image) processing failure; carries `file_path` |
| `PDFProcessingError` | `ThumbnailGenerationError` | PDF-specific failure; carries `file_path` |
| `VideoProcessingError` | `ThumbnailGenerationError` | Video-specific failure; carries `file_path` |
| `UnsupportedFormatError` | `ThumbnailGenerationError` | Unknown output format requested (e.g., `"BMP"`) |
| `OrphanedThumbnail` | `Exception` | Thumbnail row exists but its `FileIndex` FK is missing; carries `.thumbnail` and `.sha256` for cleanup |
| `OrphanedFileIndex` | `Exception` | FileIndex exists but its `ThumbnailFiles` FK points to a deleted record; carries `.thumbnail`, `.file_index_id`, `.sha256` |

**`OrphanedThumbnail` and `OrphanedFileIndex`** are not error conditions in the
traditional sense — they are signals to the caller to delete the stale record and
fall back to the generic icon. Views catch them explicitly and call `exc.thumbnail.delete()`.

---

### 3.2 `Abstractbase_thumbnails.py` — `AbstractBackend`

Abstract base class that every thumbnail backend must implement.

```python
class AbstractBackend(ABC):
    @abstractmethod
    def process_from_file(self, file_path, sizes, output_format, quality) -> dict[str, bytes]: ...
    @abstractmethod
    def process_from_memory(self, image_bytes, sizes, output_format, quality) -> dict[str, bytes]: ...
    @abstractmethod
    def process_data(self, pil_image, sizes, output_format, quality) -> dict[str, bytes]: ...
```

**Return contract:** All three methods return a `dict` where:
- Keys are size names (`"small"`, `"medium"`, `"large"`)
- Values are raw image bytes in the requested `output_format`
- Video backends additionally include `"duration"` (float seconds) and `"format"` (str) keys

This uniform interface allows `FastImageProcessor` to call any backend identically,
regardless of whether the input is a file path, bytes, or PIL object.

---

### 3.3 `thumbnail_engine.py` — `FastImageProcessor`

The central dispatcher. Selects the best backend for a given file extension and
manages per-backend instance caching.

**`BackendType` literal:** `"auto" | "core_image" | "pil" | "pdf" | "pdfkit" | "video" | "avfoundation"`

**Backend selection (`_get_cached_processor`):**

```
file_path
    → extension → filetype lookup (filetypes module)
    → is_pdf?    → "auto":  PDFKitBackend (macOS) / PDFBackend (PyMuPDF, cross-platform)
    → is_movie?  → "auto":  AVFoundationVideoBackend (macOS) / VideoBackend (ffmpeg, cross-platform)
    → is_image?  → "auto":  CoreImageBackend (Apple Silicon) / ImageBackend (PIL, cross-platform)
```

`"auto"` is the default backend type. It probes platform and framework availability at
runtime, preferring GPU-accelerated macOS backends when available.

**`_backend_cache`** — class-level `dict[str, AbstractBackend]`, protected by a
`threading.Lock`. Backend instances are created once per backend type and reused across
all requests. The `Lock` prevents duplicate construction under concurrent first requests.

**Public API:**

| Function | Description |
|---|---|
| `create_thumbnails_from_path(file_path, sizes, backend_type, output_format, quality)` | Main entry: load file → select backend → call `process_from_file()` |
| `create_thumbnails_from_pil(pil_image, file_path, sizes, ...)` | For already-loaded PIL images (avoids double decode) |
| `create_thumbnails_from_bytes(image_bytes, file_path, sizes, ...)` | For in-memory bytes |
| `clear_backend_caches()` | Clears `_backend_cache` (used in tests) |
| `get_cache_stats()` | Returns dict of backend type → cache hit info |

Default sizes: `{"small": (200, 200), "medium": (740, 740), "large": (1024, 1024)}`.

---

### 3.4 `pil_thumbnails.py` — `ImageBackend`

Cross-platform PIL/Pillow backend for raster images. This is the fallback on all
platforms and the primary backend on non-macOS systems.

**`convert_image_for_format(img, output_format)`** — standalone function:
- For JPEG output: converts RGBA/P/LA → RGB using a white matte background
- For other formats: passes through or converts to RGB as needed
- Exported for reuse by `VideoBackend` and other backends

**`_process_pil_image(img, sizes, output_format, quality)`** — core method:

```
1. Auto-orient via ImageOps.exif_transpose(img)
2. Sort sizes by area (largest first)
3. For each size (largest → smallest):
   a. img.copy()  ← important: thumbnail() mutates the image in place
   b. working_img.thumbnail(size, BICUBIC)
   c. Save to BytesIO with progressive=True (JPEG) / optimize=True
   d. Store bytes in results dict
4. Return {size_name: bytes, ...}
```

**Progressive downsampling:** Sorting largest→smallest and operating on a copy of the
original image (not the previous size) means each thumbnail is downsampled from the
full-resolution source, not from the previous thumbnail. This avoids accumulated
quality loss across sizes.

**JPEG output special case:** RGBA images are composited onto a white background before
saving. JPEG has no alpha channel; without this step, Pillow raises `OSError: cannot
write mode RGBA as JPEG`.

---

### 3.5 `pdf_thumbnails.py` — `PDFBackend`

Cross-platform PDF backend using PyMuPDF (`fitz`). Used on non-macOS platforms or when
`PDFKitBackend` is unavailable.

**Zoom caching:** `_calculate_optimal_zoom(page_width, page_height, target_width, target_height)`
is a `@staticmethod` with `@lru_cache(maxsize=500)`. PDF pages with identical dimensions
(common within a series) reuse the zoom calculation without repeating the division.

**Processing flow:**
1. Open PDF with `fitz.open(file_path)`
2. Load page 0 (or 0 if requested page exceeds document length)
3. Calculate zoom factor (10% quality buffer over minimum-fit)
4. `page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))` → raw pixel data
5. `Image.frombytes(mode, (width, height), pix.samples)` — zero-copy PIL conversion
6. `ImageOps.exif_transpose(img)` for EXIF orientation
7. Delegate to `self._image_backend._process_pil_image(...)` for resizing/encoding

`PDFBackend` holds a cached `ImageBackend` instance (`self._image_backend`) to avoid
re-constructing it per call.

`process_data()` raises `NotImplementedError` — rendering from an already-loaded PIL
image defeats the purpose of this backend (PDFs cannot be represented as PIL images
before rendering).

---

### 3.6 `pdfkit_thumbnails.py` — `PDFKitBackend`

macOS-native PDF backend using Apple's PDFKit framework (via pyobjc-framework-Quartz).
Significantly faster than `PDFBackend` because PDFKit's rendering is GPU-accelerated.

**Platform guard:** `PDFKIT_AVAILABLE` flag set at import time; `__init__` raises
`ImportError` if False.

**AppKit suppression:** `NSApplicationActivationPolicyProhibited` prevents a dock icon
from appearing when PDFKit triggers AppKit. This is a macOS quirk where headless
frameworks can unexpectedly activate the GUI layer.

**Processing flow:**
1. Open PDF with `PDFDocument.alloc().initWithURL_(url)` (or `initWithData_` for bytes)
2. `_calculate_optimal_scale()` — cached; same 10% quality buffer pattern as PDFBackend
3. `page.thumbnailOfSize_forBox_((w, h), kPDFDisplayBoxMediaBox)` → `NSImage`
4. `ns_image.TIFFRepresentation()` → TIFF bytes
5. `CIImage.imageWithData_(tiff_data)` → CIImage
6. Delegate to `self._image_backend._process_ci_image(...)` for GPU-accelerated resizing

The TIFF intermediate step is required because PDFKit returns `NSImage` and Core Image
accepts `CIImage`. TIFF preserves full quality without lossy compression.

**Memory management:** The entire operation is wrapped in `autorelease_pool()` from
`core_image_thumbnails`. The inner `_render_pdf_page_to_ciimage()` deliberately has no
inner pool because an inner pool would drain the `tiff_data` that the returned CIImage
may still reference.

---

### 3.7 `core_image_thumbnails.py` — `CoreImageBackend`

GPU-accelerated image backend using Apple's Core Image framework. Preferred over PIL
on Apple Silicon due to GPU offload. Used directly for images and as a sub-processor
for `PDFKitBackend` and `AVFoundationVideoBackend`.

**Metal device management:**

```python
_metal_device_cache: dict[str, object] = {"device": None, "pid": None}
```

The Metal GPU device is created once and cached per-process. After `os.fork()`, the
child inherits the parent's Metal device pointer, but the underlying Mach ports are
dead. The cache stores the creating process's PID and re-creates the device whenever
the current PID does not match — a **fork-safe Metal pattern**.

Metal is accessed via `ctypes.cdll.LoadLibrary` because `pyobjc-framework-Metal` is
not installed; only `MTLCreateSystemDefaultDevice` is needed.

**CIContext:**

```python
CIContext.contextWithMTLCommandQueue_options_(
    self._command_queue,
    {kCIContextCacheIntermediates: False, ...}
)
```

`kCIContextCacheIntermediates: False` is critical for batch thumbnail processing. Core
Image caches intermediate filter results on the assumption that the same image will be
processed multiple times. For thumbnailing (every image is different), this cache
accumulates GPU memory without ever producing a hit. Disabling it prevents GPU OOM
under gallery scans.

**Rendering to bitmap (no IOSurface):**

```python
self.context.render_toBitmap_rowBytes_bounds_format_colorSpace_(
    ci_image, bitmap_data, bytes_per_row, extent, kCIFormatRGBA8, color_space
)
```

This uses direct bitmap rendering instead of `createCGImage:fromRect:`. The
`createCGImage` path allocates an IOSurface (GPU shared memory), which causes GPU
memory leaks in long-running workers. Rendering directly into a `bytearray` keeps all
memory CPU-side and GC-managed.

**`autorelease_pool()` context manager:**

Wraps operations that create Objective-C autoreleased objects (CIImage, CGImage,
NSData). Without explicit pools, autoreleased objects accumulate in the current thread's
pool and are never drained in a long-running Django worker, causing memory leaks.
Nested pools are used (outer per call, inner per thumbnail size) for earlier drainage.

**`_process_ci_image(ci_image, sizes, ...)`:**

1. Sort sizes by area (largest first)
2. For each size (in a nested `autorelease_pool`):
   a. Calculate `scale = min(target_w / orig_w, target_h / orig_h)`
   b. Apply `CILanczosScaleTransform` filter for GPU-accelerated Lanczos scaling
   c. `_render_to_bytes()` → RGBA bitmap → PIL → JPEG/PNG/WEBP bytes

---

### 3.8 `video_thumbnails.py` — `VideoBackend`

Cross-platform video backend using `ffmpeg-python`. Fallback on non-macOS or when
AVFoundation is unavailable.

**Frame extraction via ffmpeg subprocess:**

```python
ffmpeg.input(video_path, ss=time_offset)
    .filter("scale", w, h, force_original_aspect_ratio="decrease")
    .filter("pad", w, h, -1, -1, "black")  # letterbox/pillarbox
    .output("pipe:", vframes=1, format="image2", vcodec="mjpeg", qscale=2)
    .run_async(pipe_stdout=True, ...)
```

Frame is captured at `duration / 2` (mid-point). The `pad` filter adds black borders
to fill the requested pixel box while preserving aspect ratio.

**Metadata:** `_get_video_info()` uses `ffmpeg.probe()` to extract `duration`, `width`,
`height`, `fps`, `codec`, and `format`. These are returned in the output dict alongside
the thumbnail bytes (callers can use `duration` for display).

**Image processing:** After frame extraction, the frame is converted to PIL and
delegated to `self._image_backend._process_pil_image()`.

---

### 3.9 `avfoundation_video_thumbnails.py` — `AVFoundationVideoBackend`

macOS-native video backend using Apple's AVFoundation framework. Preferred over
`VideoBackend` on macOS because no subprocess is spawned — frame extraction is in-process
via Objective-C.

**AppKit suppression:** Same `NSApplicationActivationPolicyProhibited` pattern as
`PDFKitBackend`.

**Frame extraction (`_extract_frame_as_ciimage`):**

```python
asset = AVAsset.assetWithURL_(file_url)
generator = AVAssetImageGenerator.assetImageGeneratorWithAsset_(asset)
generator.setAppliesPreferredTrackTransform_(True)  # Handle video rotation
requested_time = CMTimeMake(int(offset * 600), 600)  # 600 timescale = 1/600 sec precision
cg_image = generator.copyCGImageAtTime_actualTime_error_(requested_time, None, None)[0]
ci_image = CIImage.imageWithCGImage_(cg_image)
```

`setAppliesPreferredTrackTransform_(True)` is critical — it applies the track's
preferred transformation, which corrects rotation metadata (portrait videos shot on
iPhone would otherwise appear sideways).

**No inner autorelease pool in `_extract_frame_as_ciimage`:** The returned CIImage is
still referenced by the caller (`process_from_file`), which has an outer pool. An inner
pool here would drain the CIImage's backing store before the caller can use it.

**Image processing:** Delegates to `self._image_backend._process_ci_image()` — the
returned CIImage goes directly into Core Image's GPU pipeline without a CPU round-trip.

---

### 3.10 `models.py` — `ThumbnailFiles`

The single ORM model. Primary key is `sha256_hash` — the content SHA256 of the original
file.

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `sha256_hash` | `CharField(PK, max_length=64)` | Content SHA256 of the source file |
| `small_thumb` | `BinaryField(null=True)` | JPEG bytes, 200×200 |
| `medium_thumb` | `BinaryField(null=True)` | JPEG bytes, 740×740 |
| `large_thumb` | `BinaryField(null=True)` | JPEG bytes, 1024×1024 |

**Partial indexes:**

| Index | Condition | Purpose |
|---|---|---|
| `thumbnailfiles_small_exists_idx` | `small_thumb IS NOT NULL` | "Does small thumbnail exist?" |
| `thumbnailfiles_medium_exists_idx` | `medium_thumb IS NOT NULL` | "Does medium thumbnail exist?" |
| `thumbnailfiles_large_exists_idx` | `large_thumb IS NOT NULL` | "Does large thumbnail exist?" |

Partial indexes are used instead of full indexes because thumbnails can be legitimately
null while the row exists (e.g., during incremental population).

**Module-level cache:**

```python
thumbnailfiles_cache: LRUCache[str, ThumbnailFiles] = create_cache(maxsize=1500)
```

SHA256 → ThumbnailFiles object. Populated by `get_or_create_thumbnail_record()` and
`get_by_sha256_for_download()`. Never caches None values (absence of a record is
ephemeral; caching it would suppress later creation).

---

### 3.11 `models.py` — `get_or_create_thumbnail_record()`

The central thumbnail creation/retrieval method. Called by both `thumbnail2_file` and
`thumbnail2_dir`.

**Signature:**
```python
@classmethod
def get_or_create_thumbnail_record(
    cls,
    sha256: str,
    suppress_save: bool = False,
    prefetch_related_thumbnail=None,
    select_related_fileindex=None,
) -> ThumbnailFiles
```

**Processing flow:**

```
1. Check thumbnailfiles_cache[sha256] → return if hit

2. SELECT FROM thumbnailfiles WHERE sha256_hash = sha256 (with prefetch/select)
   → if found AND all three sizes populated → cache and return

3. SELECT pg_advisory_xact_lock(hash(sha256))
   — per-SHA exclusive advisory lock prevents duplicate generation
   — two concurrent requests for the same file will serialize here

4. Re-check DB after acquiring lock (another worker may have generated it)
   → return if now complete

5. Fetch FileIndex by sha256 (validated, raises OrphanedThumbnail if none)

6. Filetype routing:
   → filetype.generic         → call set_generic_icon_for_sha() → return
   → filetype.is_pdf          → FastImageProcessor (PDF backend)
   → filetype.is_movie        → FastImageProcessor (video backend)
   → filetype.is_image        → FastImageProcessor (image backend)
   → else                     → set_generic_icon_for_sha()

7. Store bytes: update_or_create() with small/medium/large from result dict
   Link FileIndex.new_ftnail = thumbnail record

8. Handle OrphanedFileIndex: if FileIndex FK is stale, raise for caller to clean up

9. Cache and return
```

**`suppress_save=True`** is used in batch processing contexts where the caller will
commit many thumbnails in a single transaction.

**`batch_create_async(sha256_list)`** — class method that generates thumbnails for a
list of SHAs concurrently. Used by the `generate_missing_thumbnails` background task.
Wraps `get_or_create_thumbnail_record()` calls with `sync_to_async`.

**`get_files_needing_thumbnail_shas(limit)`** — returns a list of SHA256 strings for
FileIndex records that have no corresponding ThumbnailFiles row. Keyed on content SHA
(not unique SHA) to avoid re-generating for duplicates.

---

### 3.12 `models.py` — `send_thumbnail()`

Instance method on `ThumbnailFiles`. Returns a `FileResponse` for the requested size.

```python
def send_thumbnail(
    self,
    filename_override=None,
    fext_override=".jpg",
    size="small",
    index_data_item=None,
) -> FileResponse
```

**Size selection:** Maps `size` string (`"small"`, `"medium"`, `"large"`) to the
corresponding `BinaryField`. If the requested size is absent (null), falls through to
the next smaller size. If all sizes are null, falls back to `index_data_item.filetype.send_thumbnail()`
(the generic icon from `filetypes`).

**Stream creation:** Creates a fresh `io.BytesIO` from the stored bytes on every call.
Django closes the stream after sending; a cached stream would be exhausted on the second
request.

---

### 3.13 `views.py` — HTTP Views

Two public views, both synchronous Django views (no async). They are thin orchestrators
that call model methods and handle exceptions.

**`thumbnail2_file(request, sha256)`:**

```
1. get_or_create_thumbnail_record(sha256)
   → OrphanedThumbnail / OrphanedFileIndex → delete + HttpResponseBadRequest

2. Fetch associated FileIndex (prefetch_related "FileIndex" reverse FK)

3. filetype.generic or is_generic_icon → filetype.send_thumbnail()

4. filetype.is_link + virtual_directory → delegate to thumbnail2_dir()

5. thumbnail.send_thumbnail(size=request.GET.get("size", "small"))
   → OSError/ValueError/AttributeError → set_generic_icon_for_sha(sha256) + filetype icon
```

**`thumbnail2_dir(request, dir_sha256)`:**

```
1. DirectoryIndex.search_for_directory_by_sha(dir_sha256)
   → not found → Http404

2. directory.thumbnail and is_cached → try send_thumbnail() → return on success

3. directory.invalidate_thumb() if not is_cached

4. directory.get_cover_image()
   → None → update_database_from_disk() → retry
   → still None → directory.filetype.send_thumbnail() (default icon)

5. transaction.atomic():
   directory.thumbnail = cover_image
   directory.save(update_fields=["thumbnail", "is_generic_icon"])

6. Ensure thumbnail.new_ftnail exists:
   ThumbnailFiles.get_or_create_thumbnail_record(cover_image.file_sha256)
   → OrphanedThumbnail/OrphanedFileIndex → delete + filetype icon

7. directory.thumbnail.new_ftnail.send_thumbnail(size="small")
   → OSError → mark is_generic_icon=True + filetype icon
```

**Cover image selection** (`DirectoryIndex.get_cover_image()`): Prefers files named
`cover` or `title` before falling back to the first file in the directory.
`thumbnail2_dir` wraps the cover-image assignment in `transaction.atomic()` to prevent
race conditions when multiple requests arrive for an uncached directory simultaneously.

---

### 3.14 `admin.py` — `AdminThumbnail_Files`

Standard `ModelAdmin` for `ThumbnailFiles`.

- `small_thumb`, `medium_thumb`, `large_thumb` are excluded from `fields` (binary blobs
  are unreadable in the admin). They are replaced by computed `sthumb`, `mthumb`,
  `lthumb` columns that display the first 25 bytes as a string preview.
- **`download_thumbnails` admin action:** Creates an in-memory ZIP file containing all
  three thumbnail sizes for selected records, named `<sha256>_small.jpg`,
  `<sha256>_medium.jpg`, `<sha256>_large.jpg`. Returns as a streaming attachment.

---

### 3.15 `image_utils.py` — Legacy Utilities

Standalone utility functions that predate the backend system. Still used by some parts
of the codebase that have not yet been migrated to `FastImageProcessor`.

| Function | Description |
|---|---|
| `pdf_to_pil(fspath)` | Opens a PDF with PyMuPDF, renders page 0, returns PIL Image |
| `movie_to_pil(fspath)` | Opens a video with `av` (PyAV), seeks to midpoint, returns frame as PIL Image; falls back to broken-video PNG on error |
| `movie_duration(fspath)` | Returns video duration in seconds via PyAV stream metadata |
| `image_to_pil(fspath, mem=False)` | Opens a raster image (or bytes if `mem=True`) with PIL |
| `return_image_obj(fs_path, memory=False)` | High-level dispatcher: routes to `pdf_to_pil`, `movie_to_pil`, or `image_to_pil` based on `FILETYPE_DATA` extension lookup |
| `resize_pil_image(source_image, size, fext)` | Resizes a PIL image to `size` using LANCZOS; saves as PNG (or JPEG if OSError) |

**Legacy consumer:** `FILETYPE_DATA` (the `filetypes.models` module-level dict) is
accessed directly in `return_image_obj` rather than through `get_ftype_dict()`. This is
a backward-compatible reference kept for callers that were written before
`get_ftype_dict()` existed.

**Migration path:** New code should use `FastImageProcessor` and the backend system
directly. `image_utils.py` functions will remain until all callers are migrated.

---

## 4. Backend Selection Matrix

| Platform | File Type | Preferred Backend | Fallback Backend |
|---|---|---|---|
| macOS (Apple Silicon) | Image | `CoreImageBackend` (GPU) | `ImageBackend` (PIL) |
| macOS | PDF | `PDFKitBackend` (GPU) | `PDFBackend` (PyMuPDF) |
| macOS | Video | `AVFoundationVideoBackend` | `VideoBackend` (ffmpeg) |
| Non-macOS | Image | `ImageBackend` (PIL) | — |
| Non-macOS | PDF | `PDFBackend` (PyMuPDF) | — |
| Non-macOS | Video | `VideoBackend` (ffmpeg) | — |
| Any | Generic filetype | No generation — use `filetypes.send_thumbnail()` | — |

Backend availability is probed at import time via try/except on framework imports.
The `"auto"` backend type in `FastImageProcessor` inspects `CORE_IMAGE_AVAILABLE`,
`PDFKIT_AVAILABLE`, and `AVFOUNDATION_AVAILABLE` flags at selection time.

---

## 5. Concurrency and Safety

### PostgreSQL Advisory Lock

`pg_advisory_xact_lock` is the concurrency guard for thumbnail creation:

```sql
SELECT pg_advisory_xact_lock(hashtext(sha256))
```

The lock is per-SHA, transaction-scoped, and exclusive. Two workers attempting to
generate a thumbnail for the same file will serialize at this point. The second worker,
after acquiring the lock, re-checks the database (step 4 in the flow above) and returns
the already-generated thumbnail without re-running the backend. This is a
check-lock-recheck pattern, not a simple check-then-act.

### Threading Safety

Backend instances in `FastImageProcessor._backend_cache` are created under
`threading.Lock`. Once created, backends are stateless across calls (state, if any, is
in `__init__`-allocated resources like the Metal command queue) and can be used from
multiple threads concurrently.

### Fork Safety

`CoreImageBackend` uses a PID-keyed cache for the Metal device. Any post-fork child
detects the PID mismatch and re-creates the device rather than using the inherited
(invalid) pointer.

### autorelease_pool

All PyObjC operations that create Objective-C objects must be wrapped in `autorelease_pool()`.
This is enforced by convention: every `process_from_file` and `process_from_memory`
entry point in macOS backends opens an outer pool, and loops over multiple sizes open
inner pools for more frequent drainage.

---

## 6. Data Flow: File Thumbnail Request

```
1. Browser: GET /thumbnail/file/<sha256>/

2. thumbnail2_file(request, sha256):
   - ThumbnailFiles.get_or_create_thumbnail_record(sha256)
   - If new: FastImageProcessor.create_thumbnails_from_path(file_path, sizes)
             → backend processes → returns {"small": bytes, "medium": bytes, "large": bytes}
   - ThumbnailFiles.update_or_create(sha256_hash=sha256, defaults={...})
   - FileIndex.new_ftnail = thumbnail (linked)

3. thumbnail.send_thumbnail(size="small"):
   - BytesIO(self.small_thumb) → FileResponse(Content-Type: image/jpeg)
```

---

## 7. Data Flow: Directory Thumbnail Request

```
1. Browser: GET /thumbnail/dir/<dir_sha256>/

2. thumbnail2_dir(request, dir_sha256):
   - DirectoryIndex.search_for_directory_by_sha(dir_sha256)
   - If cached and thumbnail set: return existing thumbnail

3. Not cached → invalidate_thumb() → get_cover_image()
   - Searches for "cover", "title" files first, then first file
   - If none: update_database_from_disk() → retry
   - If still none: return directory filetype's generic icon

4. transaction.atomic():
   - directory.thumbnail = cover_image
   - directory.save()

5. ThumbnailFiles.get_or_create_thumbnail_record(cover_image.file_sha256)
   - May trigger full thumbnail generation for the cover file

6. directory.thumbnail.new_ftnail.send_thumbnail(size="small")
```

---

## 8. Background Task Integration

**`quickbbs.tasks.generate_missing_thumbnails`** (django-dbtasks `@task`):

```python
@task(priority=50)  # web-priority; 0 for background bulk runs
async def generate_missing_thumbnails():
    sha_list = ThumbnailFiles.get_files_needing_thumbnail_shas(limit=100)
    await ThumbnailFiles.batch_create_async(sha_list)
```

- `get_files_needing_thumbnail_shas()` finds FileIndex records with no ThumbnailFiles row
- Groups by `file_sha256` (content SHA) so duplicates are not processed twice
- `batch_create_async()` wraps `get_or_create_thumbnail_record()` with `sync_to_async`
- Called periodically by the `taskrunner` process

---

## 9. Known Design Decisions and Limitations

### Why store thumbnails in the database?

Thumbnails-in-DB avoids a separate thumbnail filesystem, eliminates file path management
(no stale files after rename/delete), and makes backup atomic (one PostgreSQL dump
covers everything). The tradeoff is database size, which grows proportionally to the
gallery. PostgreSQL handles binary BLOBs efficiently for read-heavy workloads.

### Why three separate size columns instead of one BLOB per size row?

A single `ThumbnailFiles` row per file allows a single `get_or_create` call per file,
and all three sizes can be verified (or populated) in one query. Three separate rows
would require three queries or a group-by.

### Why no async views?

`thumbnail2_file` and `thumbnail2_dir` are synchronous Django views. Thumbnail generation
is CPU-bound (image processing) or subprocess-bound (ffmpeg). Async views would not
improve throughput here because the bottleneck is CPU/GPU, not I/O wait. The advisory
lock and ORM operations are synchronous PostgreSQL calls that would require explicit
`sync_to_async` wrapping in async views, adding complexity without benefit.

### `process_data()` is not implemented for PDF backends

PDF files cannot be represented as a PIL Image before rendering — there is no conversion
path from PDF bytes to a PIL object without first rendering a page. Both `PDFBackend`
and `PDFKitBackend` raise `NotImplementedError` for `process_data()`.

### macOS backends suppress AppKit activation

`PDFKitBackend` and `AVFoundationVideoBackend` suppress the dock icon via
`NSApplicationActivationPolicyProhibited`. Without this, PDFKit and AVFoundation can
trigger AppKit's GUI initialization, causing a dock icon to appear for the Django server
process — unexpected and potentially disruptive in headless/server environments.

---

## 10. Module Structure Summary

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
├── migrations/
│   └── 0001_initial.py
├── tests/
│   └── (test files)
└── SCRIPT_test_*.py                  # Standalone memory/performance test scripts
```
