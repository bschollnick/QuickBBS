# thumbnails — Exception Taxonomy

**Companion to:** [`thumbnails_design.md`](thumbnails_design.md)
**Author:** Benjamin Schollnick
**Last Updated:** 2026-08-07

---

## What this is

`thumbnails` owns the richest custom exception hierarchy in the codebase, centered on
[`thumbnails/exceptions.py`](thumbnails_design.md#41-exceptionspy--exception-hierarchy).
This document covers every class in that hierarchy, where each is raised across the
backend modules, where each is caught, and the two exceptions consumed cross-app by
[`quickbbs`](quickbbs_exceptions.md) — see
[`high_level_exception_flow.md`](high_level_exception_flow.md) for that full picture.
Verified directly against `thumbnails/exceptions.py`, `thumbnails/models.py`,
`thumbnails/views.py`, `thumbnails/thumbnail_engine.py`, and every backend module
(`core_image_thumbnails.py`, `pdfkit_thumbnails.py`, `pdf_thumbnails.py`,
`avfoundation_video_thumbnails.py`, `video_thumbnails.py`).

---

## Custom exception classes

| Class | Subclasses | Constructor attrs | Raised when |
|---|---|---|---|
| `ThumbnailGenerationError` | `Exception` | `filename` | The generation pipeline ran but produced an invalid result: empty output, or a blob that's empty at serve time |
| `MediaProcessingError` | `Exception` | `file_path` | A media backend (PDFKit, Core Image, AVFoundation) failed to load or decode the source file — a data problem, not a code problem |
| `PDFProcessingError` | `MediaProcessingError` | (inherits) | PDFKit-specific load/render/conversion failures |
| `VideoProcessingError` | `MediaProcessingError` | (inherits) | AVFoundation/ffmpeg-specific load/extraction failures |
| `OrphanedThumbnail` | `Exception` | `thumbnail`, `sha256` | A `ThumbnailFiles` row exists for a SHA256 with zero matching `FileIndex` rows |
| `OrphanedFileIndex` | `Exception` | `thumbnail`, `file_index_id`, `sha256` | The `FileIndex` row resolved for a SHA256 has `home_directory = None` (its parent directory was deleted) |
| `UnsupportedFormatError` | `ValueError` | `fmt` | An unrecognized output format or backend-type selector is requested — a programming-time contract violation, deliberately typed rather than a bare `ValueError` |

## Raise sites, by class

**`ThumbnailGenerationError`** — raised in `thumbnails/models.py` only:
`_generate_and_store_blobs` raises it three times (`:497, :514, :531`) when the image,
video, or PDF backend respectively returns an empty result; `send_thumbnail`
(`:760`) raises it when the thumbnail blob is empty at serve time.

**`MediaProcessingError`** (base class, raised directly — not via a subclass) — only
in `thumbnails/core_image_thumbnails.py`: can't load an image from a path (`:208`),
can't create a `CIImage` from bytes (`:242`), the `CIImage` has an unusable/zero
extent (`:321`), or the extent is too small to render (`:380`).

**`PDFProcessingError`** — all in `thumbnails/pdfkit_thumbnails.py`: can't get the
requested page (`:121`), render failed (`:140`), TIFF representation failed
(`:146`), CIImage-from-TIFF failed (`:152`), can't load a PDF from a file path
(`:192`), the PDF has no pages (`:198`, `:261`), or can't load a PDF from bytes
(`:257`).

**`VideoProcessingError`** — split across two backends:
- `thumbnails/avfoundation_video_thumbnails.py`: can't load the video asset (`:215,
  :286`), frame extraction failed (`:235, :241`), no video tracks found (`:297`), and
  two wrap-and-reraise sites (`:254, :330`) — both preceded by `except
  VideoProcessingError: raise` (`:251, :327`) so an already-typed error passes through
  unchanged, while anything else gets wrapped into a fresh `VideoProcessingError` with
  `from e`.
- `thumbnails/video_thumbnails.py` (the ffmpeg fallback backend): probe failures
  (`:177, :187`), a wrapped `ffmpeg.Error` (`:198`), no video stream found (`:276`),
  and a wrapped generic error from `get_video_info` (`:292`).

**`UnsupportedFormatError`** — three independent sites, one per module: an
unsupported output format in
[`core_image_thumbnails.py`](thumbnails_design.md#47-core_image_thumbnailspy--coreimagebackend)
(`:416`); an unrecognized backend-type selector in
[`FastImageProcessor._create_backend`](thumbnails_design.md#43-thumbnail_enginepy--fastimageprocessor)
(`thumbnail_engine.py:239`); an unsupported image format in the ffmpeg backend
(`video_thumbnails.py:323`).

**`OrphanedThumbnail`** — `thumbnails/models.py:393`, inside
`ThumbnailFiles._resolve_index_item_for_sha`, when a `ThumbnailFiles` row's SHA256 has
zero matching `FileIndex` rows.

**`OrphanedFileIndex`** — `thumbnails/models.py:420`, same method, when the resolved
`FileIndex.home_directory` is `None`.

## Catch sites and terminal handling

**The three-tier except chain in `_generate_and_store_blobs`**
(`models.py:588–619`), the core generation path:

```python
except FileNotFoundError as e:
    # File moved/deleted. Marks only THIS FileIndex row delete_pending=True —
    # other FileIndex rows sharing the same SHA256 may still exist at valid
    # paths, so they are left untouched.
except MediaProcessingError as e:
    # Catches PDFProcessingError/VideoProcessingError too (base class).
    # Unreadable/corrupt media — marks the whole SHA256 generic.
    # Logged at WARNING, not ERROR: "a data issue, not a code issue."
except Exception as e:  # TODO: narrow once thumbnail backend exception
                         # types are catalogued across PIL/PyMuPDF/ffmpeg
    # Anything else — also marks the whole SHA256 generic, logged via
    # logger.exception (full traceback).
```

**`send_thumbnail`** (`models.py:740`) catches `(AttributeError, ObjectDoesNotExist)`
around a reverse `FileIndex` relation lookup — logs at DEBUG and continues with
`index_data_item=None` rather than failing the whole thumbnail request over a missing
optional lookup.

**Internal re-raise-or-wrap pattern** — `avfoundation_video_thumbnails.py` catches its
own `VideoProcessingError` twice (`:251, :327`) purely to re-raise it unchanged before
a broader `except Exception` wraps anything else into a fresh `VideoProcessingError`
(with `from e` to preserve the chain).

**View-layer terminal handling**, in
[`thumbnails/views.py`](thumbnails_design.md#411-viewspy--http-views):

- [`thumbnail2_dir`](thumbnails_design.md#thumbnail2_dirrequest-dir_sha256) catches
  `(OSError, ValueError, AttributeError, ThumbnailGenerationError)` at two points
  (`:59, :126`) around calls to `send_thumbnail()`. The first (`:59`) falls through to
  the cover-image regeneration logic below it rather than returning immediately; the
  second (`:126`), after a cover image has already been selected and a
  `ThumbnailFiles` record ensured, marks the directory `is_generic_icon=True` and
  returns the filetype's generic icon.
- `thumbnail2_dir` also catches `FileIndex.DoesNotExist` (`:63`) when the directory's
  cached thumbnail FK points to a deleted `FileIndex` row — clears the stale reference
  via `directory.invalidate_thumb()` and falls through to cover-image regeneration.
- `_serve_existing_thumbnail` catches the same four-exception tuple (`:180`) around
  its fast-path serve attempt.
- [`thumbnail2_file`](thumbnails_design.md#thumbnail2_filerequest-sha256) catches the
  same tuple (`:260`) around its own `send_thumbnail()` call, marking **every**
  `FileIndex` row sharing that SHA256 as generic (via
  `FileIndex.set_generic_icon_for_sha`) before returning the generic icon — a broader
  blast radius than `thumbnail2_dir`'s single-directory flag, because a file's
  generic-icon state is tracked per content hash, not per directory placement.
- `thumbnail2_file` also catches `(AttributeError, IndexError)` (`:240`) around a
  `.first()`-then-fallback `FileIndex` lookup, converting to
  `HttpResponseBadRequest("Error accessing file data.")`.

**`OrphanedThumbnail` / `OrphanedFileIndex`**, caught independently in both
`thumbnail2_dir` (`:110`) and `thumbnail2_file` (`:223`) around calls to
[`get_or_create_thumbnail_record`](thumbnails_design.md#get_or_create_thumbnail_recordfile_sha256-suppress_save-prefetch_related_thumbnail-select_related_fileindex):
both delete `exc.thumbnail`, but the fallback response differs —
`thumbnail2_dir` falls back to `directory.filetype.send_thumbnail()`;
`thumbnail2_file` returns `HttpResponseBadRequest("File no longer exists in
gallery.")`. The same two exceptions are also caught, independently, by
[`quickbbs`](quickbbs_exceptions.md)'s background task — see
[`high_level_exception_flow.md`](high_level_exception_flow.md) for the comparison.

**Backend-availability probing** — `FastImageProcessor._create_backend`
(`thumbnail_engine.py:233`) catches `(ImportError, RuntimeError, OSError)` around
importing `CoreImageBackend` for the `"auto"` backend-type selector on Apple Silicon;
on failure it silently falls through to the cross-platform PIL backend rather than
raising. This is an availability probe, not error recovery from a real failure.

## Standard/Django exceptions used meaningfully

- **`Http404`** — raised directly in `thumbnail2_dir` (`:52`) when the directory SHA
  doesn't resolve to a record at all (before any thumbnail logic runs).
- **`HttpResponseBadRequest`** — returned (not raised) at the `OrphanedThumbnail`/
  `OrphanedFileIndex` catch in `thumbnail2_file` and at its `(AttributeError,
  IndexError)` catch, as described above.
- **`ImportError`** — used throughout the backend-detection code purely as an
  availability probe (e.g. `thumbnail_engine.py`'s "Core Image backend not
  available," and the numerous `except ImportError` guards around optional
  native-framework imports in `core_image_thumbnails.py`, `pdfkit_thumbnails.py`,
  `avfoundation_video_thumbnails.py`, `video_thumbnails.py`, `pil_thumbnails.py`) — this
  gates platform-specific backend selection, not error recovery from a failure that
  already happened.
- **`NotImplementedError`** — raised in both
  [`pdfkit_thumbnails.py`](thumbnails_design.md#46-pdfkit_thumbnailspy--pdfkitbackend)
  (`:298`) and [`pdf_thumbnails.py`](thumbnails_design.md#45-pdf_thumbnailspy--pdfbackend)
  (`:223`) for the unimplemented "PDF thumbnail from a PIL Image" code path — both
  backends define the method but always raise rather than support it.

## `pdf_thumbnails.py`'s untyped raises

`thumbnails/pdf_thumbnails.py` raises a bare, untyped `Exception` in two places:
`process(...)` (`:156`, `f"Error processing PDF: {e}"`) and `process_from_memory(...)`
(`:201`, `f"Error processing PDF bytes: {e}"`), both wrapping whatever `fitz`/PIL error
occurred while opening or rendering the PDF.
