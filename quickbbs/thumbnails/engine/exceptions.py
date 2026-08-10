"""Exceptions raised by the thumbnail generation engine.

These are the framework-independent exceptions belonging to the engine's work
layer. They intentionally carry no Django or ORM references so this module can
be extracted into a standalone distribution unchanged.

Application-level exceptions that reference database models live in
``thumbnails.exceptions`` instead.
"""

from __future__ import annotations


class ThumbnailGenerationError(Exception):
    """Raised when thumbnail generation fails for a known, recoverable reason.

    This covers cases where the pipeline ran but produced an invalid result:
    empty output, GPU-corrupted (all-white) images, or unsupported input.
    Callers should catch this to skip the current file, mark it as a generic
    icon, or schedule a retry — rather than treating it as an unexpected crash.

    Attributes:
        filename: Name of the file being processed, if available.
    """

    def __init__(self, message: str, filename: str = "") -> None:
        self.filename = filename
        super().__init__(message)


class MediaProcessingError(Exception):
    """Raised when a media backend fails to load or process a file.

    Base class for backend-specific errors.  Represents failures in the
    underlying OS framework (PDFKit, AVFoundation, etc.) rather than
    validation failures after generation.  Callers can catch this base class
    to handle all media backend failures uniformly, or catch the subclasses
    (PDFProcessingError, VideoProcessingError) to handle them separately.

    Attributes:
        file_path: Path or description of the media being processed, if available.
    """

    def __init__(self, message: str, file_path: str = "") -> None:
        self.file_path = file_path
        super().__init__(message)


class PDFProcessingError(MediaProcessingError):
    """Raised when PDFKit fails to load or render a PDF.

    Covers failures such as: document could not be loaded, document has no
    pages, page rendering returned None, or intermediate image conversion
    (TIFF/CIImage) failed.
    """


class VideoProcessingError(MediaProcessingError):
    """Raised when AVFoundation fails to load or extract a frame from a video.

    Covers failures such as: asset could not be loaded, no video tracks found,
    frame extraction returned None, or a general framework error during extraction.
    """


class UnsupportedFormatError(ValueError):
    """Raised when an unsupported output format is requested.

    Inherits from ValueError because this is a programming-time contract
    violation (caller passed an invalid argument), but uses a named type so
    callers can distinguish it from other ValueErrors if needed.

    Attributes:
        fmt: The unsupported format string that was provided.
    """

    def __init__(self, fmt: str) -> None:
        self.fmt = fmt
        super().__init__(f"Unsupported format: {fmt!r}")
