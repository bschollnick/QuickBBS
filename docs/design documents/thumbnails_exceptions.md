# thumbnails — Exception Taxonomy

**Date Created:** 2026-08-07  
**Last Updated:** 2026-09-25  
**Last Reviewed:** 2026-09-25

**Companion to:** [`thumbnails_design.md`](thumbnails_design.md)
**Author:** Benjamin Schollnick

---

## What this is

`thumbnails` owns the richest custom exception hierarchy in the codebase. This document
covers every class in it, where each is raised, and where each is caught. Two modules
define the classes, as [`thumbnails_design.md`](thumbnails_design.md#41-exceptionspy)
describes:

- `thumbnails/engine/exceptions.py` defines the engine's exceptions, which carry no
  Django references: `ThumbnailGenerationError`, `MediaProcessingError`,
  `PDFProcessingError`, `VideoProcessingError` and `UnsupportedFormatError`.
- `thumbnails/exceptions.py` defines the two that reference database models,
  `OrphanedThumbnail` and `OrphanedFileIndex`, and re-exports the engine's five, so
  callers import all seven from one place.

Three of these cross into [`quickbbs`](quickbbs_exceptions.md): `MediaProcessingError`,
`OrphanedThumbnail` and `OrphanedFileIndex`. See
[`high_level_exception_flow.md`](high_level_exception_flow.md) for that picture.

Every site below is named by function or method, not line number.

---

## Custom exception classes

| Class | Subclasses | Constructor attributes | Raised when |
|---|---|---|---|
| `ThumbnailGenerationError` | `Exception` | `filename` | Generation ran but returned no small thumbnail, or a blob is empty at serve time |
| `MediaProcessingError` | `Exception` | `file_path` | A media backend (Core Image, PDFKit, PyMuPDF, AVFoundation, ffmpeg) could not load or decode the source file: a data problem, not a code problem |
| `PDFProcessingError` | `MediaProcessingError` | (inherits) | PDFKit or PyMuPDF load, render or conversion failures |
| `VideoProcessingError` | `MediaProcessingError` | (inherits) | AVFoundation or ffmpeg load, probe or frame-extraction failures |
| `OrphanedThumbnail` | `Exception` | `thumbnail`, `sha256` | A `ThumbnailFiles` row exists for a SHA256 with zero matching `FileIndex` rows |
| `OrphanedFileIndex` | `Exception` | `thumbnail`, `file_index_id`, `sha256` | The `FileIndex` row resolved for a SHA256 has `home_directory = None` (its parent directory was deleted) |
| `UnsupportedFormatError` | `ValueError` | `fmt` | An unrecognized output format or backend selector is requested. It is a named subclass of `ValueError`, so a caller can tell it apart from other `ValueError`s |

## Raise sites, by class

**`ThumbnailGenerationError`** — raised in `thumbnails/models.py` only.
`ThumbnailFiles._generate_and_store_blobs` raises it three times, when the image, video
or PDF backend returns a result with no small thumbnail; the same method's own
`except Exception` catches it (see below). `ThumbnailFiles.send_thumbnail` raises it
when the requested blob is empty at serve time.

**`MediaProcessingError`** (raised directly, not through a subclass) — only in
`thumbnails/engine/core_image_thumbnails.py`: `CoreImageBackend.process_from_file`
cannot load an image from the path; `process_from_memory` cannot create a `CIImage`
from the bytes; `render_sizes` finds an unusable (zero or infinite) extent; and
`_render_to_bytes` finds an extent too small to render.

**`PDFProcessingError`** — two backends:
- `thumbnails/engine/pdfkit_thumbnails.py`: `PDFKitBackend._render_pdf_page_to_ciimage`
  cannot get the requested page, rendering fails, the TIFF representation fails, or the
  `CIImage` cannot be created from the TIFF data; `process_from_file` and
  `process_from_memory` cannot load the PDF, or it has no pages.
- `thumbnails/engine/pdf_thumbnails.py`: the module-level context manager
  `_open_page()`, which `PDFBackend.process_from_file` and `process_from_memory` both
  render inside, re-raises any PyMuPDF error (all subclass `RuntimeError`), or PIL's
  `OSError` or `ValueError`, as `PDFProcessingError`, with `from e`.

**`VideoProcessingError`** — two backends:
- `thumbnails/engine/avfoundation_video_thumbnails.py`: `_extract_frame_as_ciimage`
  cannot load the asset or extract a frame (two sites); `read_video_info` cannot load
  the asset or finds no video tracks. Each function ends with `except
  VideoProcessingError: raise`, so an already-typed error passes through unchanged,
  followed by `except Exception`, which wraps anything else in a new
  `VideoProcessingError` with `from e`.
- `thumbnails/engine/video_thumbnails.py` (the ffmpeg backend):
  `_generate_thumbnail_to_pil` raises it when ffmpeg exits non-zero, when ffmpeg exits
  zero with no frame data, and when it wraps an `ffmpeg.Error`; `read_video_info` raises
  it when the file has no video stream and when it wraps an `ffmpeg.Error`.

**`UnsupportedFormatError`** — two sites: an output format other than JPEG, PNG or WEBP
in `CoreImageBackend._render_to_bytes`
([`core_image_thumbnails.py`](thumbnails_design.md#47-enginecore_image_thumbnailspy));
and an unrecognized backend selector in
[`FastImageProcessor._create_backend`](thumbnails_design.md#43-engineenginepy)
(`thumbnails/engine/engine.py`), which looks the selector up in `_BACKEND_RULES`.

**`OrphanedThumbnail`** — `ThumbnailFiles._resolve_index_item_for_sha` in
`thumbnails/models.py`, when no `FileIndex` row exists for the `ThumbnailFiles` row's
SHA256.

**`OrphanedFileIndex`** — the same method, when the resolved `FileIndex.home_directory`
is `None`.

**`FileNotFoundError`** is raised explicitly by every file-based backend when the path
does not exist: `CoreImageBackend`, `PDFBackend`, `PDFKitBackend` and
`AVFoundationVideoBackend` in `process_from_file`, and the ffmpeg backend in
`_generate_thumbnail_to_pil`. `ImageBackend.process_from_file` lets PIL raise it.
Core Image needs the explicit check because `CIImage.imageWithContentsOfURL_` returns
`None` for a missing file, the same as for an undecodable one.

## Catch sites and terminal handling

**The three-tier except chain in `ThumbnailFiles._generate_and_store_blobs`**
(`thumbnails/models.py`), the core generation path:

```python
except FileNotFoundError as e:
    # File moved/deleted. Marks only THIS FileIndex row delete_pending=True —
    # other FileIndex rows sharing the same SHA256 may still exist at valid
    # paths, so they are left untouched. Logged at WARNING.
except MediaProcessingError as e:
    # Catches PDFProcessingError/VideoProcessingError too (base class).
    # Unreadable/corrupt media — marks the whole SHA256 generic.
    # Logged at WARNING: a data issue, not a code issue.
except Exception as e:
    # Anything else, including this method's own ThumbnailGenerationError —
    # also marks the whole SHA256 generic, logged via logger.exception
    # (ERROR with a full traceback).
```

The broad `except Exception` carries a `TODO` to narrow it once the backends' exception
types are catalogued. None of the three re-raises: the method returns the unpopulated
`thumbnail` record.

**`ThumbnailFiles.send_thumbnail`** catches `(AttributeError, ObjectDoesNotExist)`
around its reverse `FileIndex` relation lookup. It logs at DEBUG and continues with
`index_data_item=None` rather than failing the thumbnail request over an optional
lookup.

**`get_video_info`** (`thumbnails/engine/engine.py`) catches `MediaProcessingError` from
the AVFoundation probe and retries with the ffmpeg probe, which reads formats macOS has
no decoder for (WMV, FLV, MPEG-1). When the resolved probe already is the ffmpeg one, it
re-raises.

**View-layer terminal handling**, in
[`thumbnails/views.py`](thumbnails_design.md#411-viewspy):

- [`thumbnail_dir`](thumbnails_design.md#thumbnail_dirrequest-dir_sha256) catches
  `(OSError, ValueError, AttributeError, ThumbnailGenerationError)` around both of its
  `send_thumbnail()` calls, printing the error to standard output rather than logging
  it. The first catch, on the cached-cover fast path, falls through to cover-image
  selection. The second, after a cover image has been selected and a `ThumbnailFiles`
  record ensured, marks the directory `is_generic_icon=True` and returns the filetype's
  generic icon.
- `thumbnail_dir` also catches `FileIndex.DoesNotExist` when the directory's cached
  thumbnail foreign key points to a deleted `FileIndex` row. It clears the stale
  reference with `directory.invalidate_thumb()` and falls through to cover-image
  selection.
- `_serve_existing_thumbnail`, the read-only fast path of `thumbnail_file`, catches the
  same four-exception tuple around its `send_thumbnail()` call. It marks **every**
  `FileIndex` row sharing that SHA256 as generic (via `FileIndex.set_generic_icon_for_sha`)
  and returns the generic icon.
- [`thumbnail_file`](thumbnails_design.md#thumbnail_filerequest-sha256) catches the same
  tuple around its own `send_thumbnail()` call, with the same handling as
  `_serve_existing_thumbnail`. The generic flag is set for the whole SHA256, not one
  row, because a file's generic-icon state is tracked per content hash, while
  `thumbnail_dir`'s flag is per directory.
- `thumbnail_file` also catches `(AttributeError, IndexError)` around its `.first()`
  lookup of the associated `FileIndex` row and the `FileIndex.get_by_sha256` fallback,
  returning `HttpResponseBadRequest("Error accessing file data.")`.

**`OrphanedThumbnail` / `OrphanedFileIndex`** are caught independently in both
`thumbnail_dir` and `thumbnail_file` around their calls to
[`get_or_create_thumbnail_record`](thumbnails_design.md#get_or_create_thumbnail_recordfile_sha256-suppress_save-prefetch_related_thumbnail-select_related_fileindex).
Both log at WARNING and delete `exc.thumbnail`, but the response differs:
`thumbnail_dir` falls back to `directory.filetype.send_thumbnail()`; `thumbnail_file`
returns `HttpResponseBadRequest("File no longer exists in gallery.")`. The same two
exceptions are also caught, independently, by [`quickbbs`](quickbbs_exceptions.md)'s
`generate_missing_thumbnails` background task (`quickbbs/tasks.py`) — see
[`high_level_exception_flow.md`](high_level_exception_flow.md) for the comparison.

**`ValueError` from `get_or_create_thumbnail_record` is not caught by either view.** The
method raises it when a required parameter is missing, and
`_resolve_index_item_for_sha` raises it when `FileIndex` rows exist for the SHA256 but
cannot be linked to the orphaned `ThumbnailFiles` row, or cannot be fetched after
linking. In a view it propagates as a server error. The background task catches it in
its `except Exception`, logs it with a traceback, and records that SHA256 as failed.

**Backend-availability probing** — `FastImageProcessor._create_backend`
(`thumbnails/engine/engine.py`) catches `(ImportError, RuntimeError, OSError)` around
constructing the backend the `"auto"` selector chose (`CoreImageBackend` on an Apple
Silicon Mac), and constructs `ImageBackend` instead. `_FALLBACK_ON_CONSTRUCTION_ERROR`
names `"auto"` as the only selector with a fallback; every other selector lets the error
propagate. This is an availability probe, not error recovery from a real failure.

**`CoreImageBackend.__init__`** raises `ImportError` when Core Image or a Metal device
is unavailable, and wraps any exception from creating the Metal command queue (for
example in a forked child with a stale device) in `ImportError`, so that
`_create_backend`'s fallback above applies. The module-level `_create_metal_device`
catches `(OSError, AttributeError)` from loading Metal through `ctypes` and returns
`None`.

## Standard and Django exceptions used meaningfully

- **`Http404`** — raised in `thumbnail_dir` when no directory SHA256 is supplied, and
  when the SHA256 does not resolve to a `DirectoryIndex` record, before any thumbnail
  logic runs.
- **`HttpResponseBadRequest`** — returned (not raised) by `thumbnail_file` at its
  `OrphanedThumbnail`/`OrphanedFileIndex` catch, at its `(AttributeError, IndexError)`
  catch, and when no `FileIndex` row is found at all ("No associated file data found.").
- **`ImportError`** — used as an availability probe, not error recovery:
  `except ImportError` guards the optional native-framework imports at module level in
  `core_image_thumbnails.py`, `pdfkit_thumbnails.py` and
  `avfoundation_video_thumbnails.py`, and inside `hide_dock_icon`. In `engine.py`,
  `_check_core_image_available`, `_check_avfoundation_available`,
  `_check_pdfkit_available`, `_resolve_video_info_impl` and `_peak_rss_kb` catch it,
  and `_require_core_image` raises it ("Core Image backend not available on this
  system") when `"coreimage"` is requested explicitly. The backend constructors raise it
  when their framework is missing.
- **`OSError`** — `is_apple_silicon` catches it from `platform` and returns `False`.
- **`NotImplementedError`** — raised by `process_data` in both
  [`pdfkit_thumbnails.py`](thumbnails_design.md#46-enginepdfkit_thumbnailspy) and
  [`pdf_thumbnails.py`](thumbnails_design.md#45-enginepdf_thumbnailspy) for the
  unimplemented "PDF thumbnail from a PIL Image" path: both backends define the method
  and always raise.
