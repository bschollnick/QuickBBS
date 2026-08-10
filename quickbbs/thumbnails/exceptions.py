"""Exceptions for the thumbnails app.

Defines the application-level exceptions that reference database models, and
re-exports the framework-independent engine exceptions from
``thumbnails.engine.exceptions`` so callers have a single import location.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from thumbnails.engine.exceptions import (
    MediaProcessingError,
    PDFProcessingError,
    ThumbnailGenerationError,
    UnsupportedFormatError,
    VideoProcessingError,
)

if TYPE_CHECKING:
    from thumbnails.models import ThumbnailFiles

__all__ = [
    "MediaProcessingError",
    "OrphanedFileIndex",
    "OrphanedThumbnail",
    "PDFProcessingError",
    "ThumbnailGenerationError",
    "UnsupportedFormatError",
    "VideoProcessingError",
]


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

    def __init__(self, thumbnail: ThumbnailFiles, sha256: str) -> None:
        self.thumbnail = thumbnail
        self.sha256 = sha256
        super().__init__(f"Orphaned ThumbnailFiles {thumbnail.id}: No FileIndex records found for SHA256 {sha256}")


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

    def __init__(self, thumbnail: ThumbnailFiles, file_index_id: int, sha256: str) -> None:
        self.thumbnail = thumbnail
        self.file_index_id = file_index_id
        self.sha256 = sha256
        super().__init__(f"FileIndex {file_index_id} (SHA256 {sha256}) has no home_directory")
