"""Custom exceptions for the thumbnails subsystem."""

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


class OrphanedThumbnail(Exception):
    """Raised when a ThumbnailFiles record has no associated FileIndex records.

    This occurs when a ThumbnailFiles row exists for a SHA256 hash that has no
    matching FileIndex entries — typically caused by files being removed from the
    gallery without a corresponding database cleanup.  The caller is responsible
    for deleting the orphaned ThumbnailFiles record.

    Attributes:
        thumbnail: The orphaned ThumbnailFiles instance.
        sha256: The SHA256 hash of the orphaned record.
    """

    def __init__(self, thumbnail: object, sha256: str) -> None:
        self.thumbnail = thumbnail
        self.sha256 = sha256
        super().__init__(
            f"Orphaned ThumbnailFiles {thumbnail.id}: No FileIndex records found for SHA256 {sha256}"  # type: ignore[union-attr]
        )


class OrphanedFileIndex(Exception):
    """Raised when a FileIndex record has no associated home_directory.

    This occurs when a directory is deleted but its FileIndex rows remain in the
    database.  The caller is responsible for deleting the associated ThumbnailFiles
    record so it can be regenerated if the file is re-added to the gallery.

    Attributes:
        thumbnail: The ThumbnailFiles instance to be deleted by the caller.
        file_index_id: The primary key of the orphaned FileIndex record.
        sha256: The SHA256 hash of the record.
    """

    def __init__(self, thumbnail: object, file_index_id: int, sha256: str) -> None:
        self.thumbnail = thumbnail
        self.file_index_id = file_index_id
        self.sha256 = sha256
        super().__init__(
            f"FileIndex {file_index_id} (SHA256 {sha256}) has no home_directory"
        )


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
