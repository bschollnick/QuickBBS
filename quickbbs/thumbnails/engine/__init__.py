"""Multi-backend thumbnail generation engine.

A framework-independent thumbnail generator that selects between cross-platform
backends (PIL, PyMuPDF, ffmpeg) and macOS-accelerated ones (Core Image,
AVFoundation, PDFKit) based on the host and the requested media type.

This subpackage deliberately contains no Django imports so it can be extracted
into a standalone distribution. The embedding application supplies its settings
as plain arguments and via :data:`thumbnails.engine.config.config`.

Typical use::

    from thumbnails.engine import create_thumbnails_from_path

    thumbs = create_thumbnails_from_path(
        "/albums/photos/cover.jpg",
        {"small": (200, 200), "large": (1024, 1024)},
        output="JPEG",
        quality=85,
    )
"""

from __future__ import annotations

from .config import EngineConfig, config
from .engine import (
    BackendType,
    FastImageProcessor,
    clear_backend_caches,
    create_thumbnails_from_bytes,
    create_thumbnails_from_path,
    create_thumbnails_from_pil,
    get_cache_stats,
    get_video_info,
    is_all_white_thumbnail,
    resolve_backend_name,
)
from .exceptions import (
    MediaProcessingError,
    PDFProcessingError,
    ThumbnailGenerationError,
    UnsupportedFormatError,
    VideoProcessingError,
)

__all__ = [
    "BackendType",
    "EngineConfig",
    "FastImageProcessor",
    "MediaProcessingError",
    "PDFProcessingError",
    "ThumbnailGenerationError",
    "UnsupportedFormatError",
    "VideoProcessingError",
    "clear_backend_caches",
    "config",
    "create_thumbnails_from_bytes",
    "create_thumbnails_from_path",
    "create_thumbnails_from_pil",
    "get_cache_stats",
    "get_video_info",
    "is_all_white_thumbnail",
    "resolve_backend_name",
]
