"""Multi-backend thumbnail generation engine with automatic backend selection.

Backend imports are deferred to first use to avoid loading heavy libraries
(PyMuPDF, ffmpeg, macOS frameworks) at import time — only the backend
actually selected is ever loaded.

This module is framework-independent: it reads its settings from
:mod:`thumbnails.engine.config` rather than from any application framework.
"""

import functools
import gc
import importlib
import io
import logging
import os
import platform
import threading
from collections.abc import Callable
from typing import Any, Literal

from PIL import Image

from .base import AbstractBackend, ThumbnailResult
from .config import config
from .exceptions import MediaProcessingError, UnsupportedFormatError

logger = logging.getLogger(__name__)


def macintosh_optimizations_enabled() -> bool:
    """Return True if macOS-accelerated backends may be auto-selected.

    Reads :data:`thumbnails.engine.config.config`, which the embedding
    application sets at startup. Explicit backend requests ("coreimage",
    "pdfkit") are never gated by this — only the auto-selecting cases
    ("auto", "corevideo", "pdf").

    Returns:
        True if the macOS backends may be chosen automatically, False otherwise.
    """
    return config.macintosh_optimizations


def is_apple_silicon() -> bool:
    """Return True if running on Apple Silicon (arm64 macOS).

    Returns:
        True if the current process is running on Apple Silicon, False otherwise.
    """
    try:
        return platform.system() == "Darwin" and platform.processor() == "arm" and "arm64" in platform.machine().lower()
    except OSError:
        return False


@functools.cache
def _check_core_image_available() -> bool:
    """Check if the Core Image backend can be imported (checked once)."""
    try:
        importlib.import_module(".core_image_thumbnails", __package__)
    except ImportError:
        return False
    return True


@functools.cache
def _check_avfoundation_available() -> bool:
    """Check if the AVFoundation backend is available (checked once)."""
    try:
        module = importlib.import_module(".avfoundation_video_thumbnails", __package__)
    except ImportError:
        return False
    return bool(module.AVFOUNDATION_AVAILABLE)


@functools.cache
def _check_pdfkit_available() -> bool:
    """Check if the PDFKit backend is available (checked once)."""
    try:
        module = importlib.import_module(".pdfkit_thumbnails", __package__)
    except ImportError:
        return False
    return bool(module.PDFKIT_AVAILABLE)


BackendType = Literal["image", "coreimage", "auto", "video", "corevideo", "pdf", "pymupdf", "pdfkit"]


def _ffmpeg_video_info() -> Callable[[str], dict[str, Any]]:
    """Return the ffmpeg metadata probe, which reads every container ffmpeg supports."""
    return importlib.import_module(".video_thumbnails", __package__).read_video_info


@functools.cache
def _resolve_video_info_impl() -> Callable[[str], dict[str, Any]]:
    """Resolve the video-metadata probe for this platform (checked once).

    Prefers AVFoundation on macOS (no subprocess spawn, roughly 10x faster than
    the ffmpeg probe) and falls back to the ffmpeg probe elsewhere, or when
    pyobjc is not installed. Imported on first call: pyobjc/AVFoundation is
    macOS-only and expensive to import.

    Returns:
        The resolved metadata function taking a path and returning a dict.
    """
    if platform.system() == "Darwin":
        try:
            return importlib.import_module(".avfoundation_video_thumbnails", __package__).read_video_info
        except ImportError:
            pass
    return _ffmpeg_video_info()


def get_video_info(path: str) -> dict[str, Any]:
    """Return metadata for a video file, using the fastest available probe.

    Resolves the probe on first use (AVFoundation on macOS, ffmpeg elsewhere)
    and caches it for subsequent calls.

    Args:
        path: Fully qualified path to the video file.

    Returns:
        Dictionary of video metadata: duration, width, height, fps, codec,
        and format.

    Raises:
        MediaProcessingError: If no available probe can read the file.
    """
    impl = _resolve_video_info_impl()
    try:
        return impl(path)
    except MediaProcessingError:
        # AVFoundation has no decoder for some containers/codecs (e.g. WMV,
        # FLV, MPEG-1) and reports "No video tracks found" for them. Retry
        # with the ffmpeg probe, which supports those formats. If the resolved
        # probe already IS the ffmpeg one, there is nothing to fall back to.
        ffmpeg_probe = _ffmpeg_video_info()
        if impl is ffmpeg_probe:
            raise
        return ffmpeg_probe(path)


def is_all_white_thumbnail(small_thumb: bytes | memoryview | None) -> bool:
    """Return True if the thumbnail blob decodes to an entirely white image.

    Detects the all-white output that GPU-accelerated backends can produce
    instead of raising — most often after a fork, when a cached Metal command
    queue references the parent process's dead Mach ports.

    Callers apply their own size prefilter; a large all-white image is
    generally legitimate content rather than corruption.

    Args:
        small_thumb: JPEG/PNG blob of the small thumbnail (bytes or a
            memoryview from a binary column), or None.

    Returns:
        True if every pixel is white, False for empty/None blobs, non-RGB/L
        modes, or any non-white pixel.
    """
    if not small_thumb:
        return False
    with Image.open(io.BytesIO(small_thumb)) as img:
        extrema = img.getextrema()
        if img.mode == "RGB":
            return extrema == ((255, 255), (255, 255), (255, 255))
        if img.mode == "L":
            return extrema == (255, 255)
    return False


#: Where each concrete backend class lives, relative to this package.
#: Imported on first use: each pulls in heavy optional libraries (PIL,
#: PyMuPDF, ffmpeg, the macOS frameworks).
_BACKEND_CLASSES: dict[str, tuple[str, str]] = {
    "image": (".pil_thumbnails", "ImageBackend"),
    "coreimage": (".core_image_thumbnails", "CoreImageBackend"),
    "video": (".video_thumbnails", "VideoBackend"),
    "corevideo": (".avfoundation_video_thumbnails", "AVFoundationVideoBackend"),
    "pymupdf": (".pdf_thumbnails", "PDFBackend"),
    "pdfkit": (".pdfkit_thumbnails", "PDFKitBackend"),
}


def _backend_class(name: str) -> type[AbstractBackend]:
    """Import and return the concrete backend class named in `_BACKEND_CLASSES`."""
    module_name, class_name = _BACKEND_CLASSES[name]
    return getattr(importlib.import_module(module_name, __package__), class_name)


def _require_core_image() -> str:
    """Choose Core Image for an explicit request, which never falls back."""
    if not _check_core_image_available():
        raise ImportError("Core Image backend not available on this system")
    return "coreimage"


def _macos_accelerated(available: Callable[[], bool], *, needs_apple_silicon: bool) -> bool:
    """Return whether a macOS backend may be auto-selected on this machine."""
    return macintosh_optimizations_enabled() and available() and (not needs_apple_silicon or is_apple_silicon())


#: How each backend selector chooses a concrete backend. Only the chosen
#: backend's availability is checked, so an unused one is never imported.
_BACKEND_RULES: dict[str, Callable[[], str]] = {
    "image": lambda: "image",
    "coreimage": _require_core_image,
    # Core Image on Apple Silicon for GPU-accelerated Lanczos, else PIL.
    "auto": lambda: "coreimage" if _macos_accelerated(_check_core_image_available, needs_apple_silicon=True) else "image",
    "video": lambda: "video",
    "corevideo": lambda: "corevideo" if _macos_accelerated(_check_avfoundation_available, needs_apple_silicon=False) else "video",
    # PDFKit on Apple Silicon, else PyMuPDF.
    "pdf": lambda: "pdfkit" if _macos_accelerated(_check_pdfkit_available, needs_apple_silicon=True) else "pymupdf",
    "pymupdf": lambda: "pymupdf",
    "pdfkit": lambda: "pdfkit" if _check_pdfkit_available() else "pymupdf",
}

#: Selectors whose chosen backend may fail to construct (no Metal device,
#: say) and then fall back instead of raising.
_FALLBACK_ON_CONSTRUCTION_ERROR: dict[str, str] = {"auto": "image"}


class FastImageProcessor:
    """Multi-backend image processor with automatic backend selection and caching."""

    __slots__ = ("_backend", "backend_type", "image_sizes")

    def __init__(self, image_sizes: dict[str, tuple[int, int]], backend: BackendType = "auto"):
        """
        Initialize the processor and resolve (or reuse) its backend instance.

        Args:
            image_sizes: Dict mapping size names to (width, height) tuples.
            backend: Backend selector — one of "image", "coreimage", "auto"
                (still images), "video", "corevideo" (videos), or "pdf",
                "pymupdf", "pdfkit" (PDFs). The "auto"/"corevideo"/"pdf"
                selectors pick the macOS-accelerated backend when available
                and permitted, falling back to the cross-platform one.

        Raises:
            UnsupportedFormatError: If the backend selector is not recognised.
            ImportError: If an explicitly requested macOS backend is
                unavailable on this system.
        """
        self.image_sizes = image_sizes
        self.backend_type = backend.lower()
        self._backend = self._get_cached_backend()

    def _get_cached_backend(self):
        """Get or create cached backend instance for reuse (thread-safe).

        Logs the resolved backend class once per process per backend type so
        worker logs show whether the macOS-accelerated paths are actually in
        use (backends are cached, so this does not spam per-file).
        """
        with _backend_lock:
            if self.backend_type not in _backend_cache:
                backend = self._create_backend()
                logger.info(
                    "Thumbnail backend resolved: %r -> %s (macintosh optimizations %s)",
                    self.backend_type,
                    type(backend).__name__,
                    "enabled" if macintosh_optimizations_enabled() else "disabled",
                )
                _backend_cache[self.backend_type] = backend
            return _backend_cache[self.backend_type]

    def _create_backend(self) -> AbstractBackend:
        """Create appropriate backend based on system and preference.

        Returns:
            Backend instance for the configured backend type

        Raises:
            UnsupportedFormatError: If the configured backend type is not recognised.
            ImportError: If "coreimage" is requested and Core Image is unavailable.
        """
        choose = _BACKEND_RULES.get(self.backend_type)
        if choose is None:
            raise UnsupportedFormatError(self.backend_type)
        name = choose()
        fallback = _FALLBACK_ON_CONSTRUCTION_ERROR.get(self.backend_type)
        if fallback is None or name == fallback:
            return _backend_class(name)()
        try:
            return _backend_class(name)()
        except (ImportError, RuntimeError, OSError):
            return _backend_class(fallback)()

    @property
    def current_backend(self) -> str:
        """Get name of currently active backend."""
        return type(self._backend).__name__

    def process_image_file(self, file_path: str, output_format: str = "JPEG", quality: int = 85) -> ThumbnailResult:
        """Process image file and generate multiple thumbnails."""
        return self._backend.process_from_file(file_path, self.image_sizes, output_format, quality)

    def process_image_bytes(self, image_bytes: bytes, output_format: str = "JPEG", quality: int = 85) -> ThumbnailResult:
        """Process image from bytes and generate multiple thumbnails."""
        return self._backend.process_from_memory(image_bytes, self.image_sizes, output_format, quality)

    def process_pil_image(self, pil_image: Image.Image, output_format: str = "JPEG", quality: int = 85) -> ThumbnailResult:
        """Process PIL Image object and generate multiple thumbnails."""
        return self._backend.process_data(pil_image, self.image_sizes, output_format, quality)


# Global processor cache for common size configurations.
# Protected by _processor_lock for thread safety in multi-threaded workers.
_processor_cache: dict = {}
_processor_lock = threading.Lock()

# Backend instances reused across processors, keyed by backend selector.
# Protected by _backend_lock for thread safety in multi-threaded workers.
_backend_cache: dict[str, Any] = {}
_backend_lock = threading.Lock()


def _fork_acquire_locks() -> None:
    """Serialize fork against cache mutation so no lock is held mid-fork.

    Acquired in fixed order (processor, then backend) to avoid lock-order
    inversion with _fork_release_locks_parent.
    """
    # _fork_release_locks_parent and _fork_reset_child release these after the fork.
    _processor_lock.acquire()  # pylint: disable=consider-using-with
    _backend_lock.acquire()  # pylint: disable=consider-using-with


def _fork_release_locks_parent() -> None:
    """Release the fork-serialization locks in the parent (reverse order)."""
    _backend_lock.release()
    _processor_lock.release()


def _fork_reset_child() -> None:
    """Reset engine state in a forked child process.

    The child gets fresh locks (the inherited ones are owned by threads that do
    not exist in the child) and empty caches — discarding any CoreImageBackend
    whose Metal command queue references the parent's now-dead Mach ports.
    Using such a backend can silently produce blank/white renders instead of
    raising, so the caches must be cleared before any thumbnail work runs.

    Note: register_at_fork makes THIS module fork-correct; forking after the
    ObjC/Metal runtime is initialized remains discouraged by Apple. The child
    recovers via the per-PID Metal device recreation in core_image_thumbnails.
    """
    # The inherited locks are owned by threads that do not exist in the child.
    global _processor_lock, _backend_lock  # pylint: disable=global-statement
    _processor_lock = threading.Lock()
    _backend_lock = threading.Lock()
    _processor_cache.clear()
    _backend_cache.clear()


os.register_at_fork(
    before=_fork_acquire_locks,
    after_in_parent=_fork_release_locks_parent,
    after_in_child=_fork_reset_child,
)


def _get_cached_processor(sizes: dict[str, tuple[int, int]], backend: BackendType) -> FastImageProcessor:
    """Get or create cached processor for common configurations (thread-safe)."""
    cache_key = (tuple(sorted(sizes.items())), backend)
    with _processor_lock:
        if cache_key not in _processor_cache:
            _processor_cache[cache_key] = FastImageProcessor(sizes, backend)
        return _processor_cache[cache_key]


def resolve_backend_name(backend: BackendType, sizes: dict[str, tuple[int, int]]) -> str:
    """Return the class name of the backend that will process this configuration.

    Resolves (and caches) the backend exactly as generation will, so callers
    can log which frontend — e.g. CoreImageBackend vs ImageBackend — is active.

    Args:
        backend: Backend selector (e.g. "auto", "corevideo", "pdf").
        sizes: Dictionary mapping size names to (width, height) tuples.

    Returns:
        Backend class name, e.g. "CoreImageBackend" or "ImageBackend".
    """
    return _get_cached_processor(sizes, backend).current_backend


def _peak_rss_kb() -> int | None:
    """Return the process's peak resident set size in KB, or None where `resource` does not exist (Windows)."""
    try:
        resource = importlib.import_module("resource")
    except ImportError:
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def clear_backend_caches(force_gc: bool = True) -> dict[str, int | float]:
    """
    Clear cached processor and backend instances to release resources.

    Call this periodically (e.g., after processing batches of thumbnails)
    to release accumulated resources in both the processor cache and
    the backend cache.

    This is particularly important for Core Image backends on macOS, where
    CIContext instances accumulate GPU resources. Clearing caches forces
    recreation of these instances, releasing GPU memory.

    Args:
        force_gc: If True, run garbage collection after clearing caches.

    Returns:
        Dictionary with cache statistics:
        - processors_cleared: Number of processor instances cleared
        - backends_cleared: Number of backend instances cleared
        - gc_objects_collected: Number of objects collected by GC
        - memory_freed_mb: Estimated memory freed (may be negative due to
          OS caching; 0 when force_gc is False)

    Example:
        >>> # After batch thumbnail generation
        >>> stats = clear_backend_caches()
        >>> print(f"Cleared {stats['processors_cleared']} processors")
    """
    # Clear caches under their respective locks
    with _processor_lock:
        processors_cleared = len(_processor_cache)
        _processor_cache.clear()

    with _backend_lock:
        backends_cleared = len(_backend_cache)
        _backend_cache.clear()

    # Optional garbage collection to force cleanup
    if force_gc:
        rss_before_kb = _peak_rss_kb()
        # Force collection of all generations
        collected = gc.collect(generation=2)
        rss_after_kb = _peak_rss_kb()
        memory_freed_mb = (rss_before_kb - rss_after_kb) / 1024 if rss_before_kb is not None and rss_after_kb is not None else 0
    else:
        collected = 0
        memory_freed_mb = 0

    return {
        "processors_cleared": processors_cleared,
        "backends_cleared": backends_cleared,
        "gc_objects_collected": collected,
        "memory_freed_mb": memory_freed_mb,
    }


def get_cache_stats() -> dict[str, int]:
    """
    Get current cache statistics without clearing.

    Useful for monitoring cache growth and determining when to call
    clear_backend_caches().

    Returns:
        Dictionary with current cache statistics:
        - processor_cache_size: Number of cached processors
        - backend_cache_size: Number of cached backends
        - total_cached_instances: Combined total

    Example:
        >>> stats = get_cache_stats()
        >>> if stats['total_cached_instances'] > 10:
        ...     clear_backend_caches()
    """
    return {
        "processor_cache_size": len(_processor_cache),
        "backend_cache_size": len(_backend_cache),
        "total_cached_instances": len(_processor_cache) + len(_backend_cache),
    }


# Simplified interface functions
def create_thumbnails_from_path(
    file_path: str,
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> ThumbnailResult:
    """Create thumbnails from a file path with processor caching.

    Main entry point for thumbnail generation. The processor (and its
    backend instance) is cached per (sizes, backend) configuration.

    Args:
        file_path: Path to the source media file (image, video, or PDF —
            must match the chosen backend).
        sizes: Dictionary mapping size names to (width, height) tuples.
        output: Output format (JPEG, PNG, WEBP).
        quality: Image quality (1-100).
        backend: Backend selector; see FastImageProcessor for valid values.

    Returns:
        The thumbnails, keyed by size name, in `output`. A video's result
        also carries its duration.

    Example:
        >>> thumbs = create_thumbnails_from_path(
        ...     "/albums/photos/cover.jpg",
        ...     settings.IMAGE_SIZE,
        ...     output="JPEG",
        ...     quality=85,
        ...     backend="auto",
        ... )
        >>> len(thumbs.images["small"]) > 0
        True
    """
    proc = _get_cached_processor(sizes, backend)
    return proc.process_image_file(file_path, output, quality)


def create_thumbnails_from_pil(
    pil_image: Image.Image,
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> ThumbnailResult:
    """Create thumbnails from a PIL Image with processor caching.

    Args:
        pil_image: PIL Image object to process.
        sizes: Dictionary mapping size names to (width, height) tuples.
        output: Output format (JPEG, PNG, WEBP).
        quality: Image quality (1-100).
        backend: Backend selector; see FastImageProcessor for valid values.

    Returns:
        The thumbnails, keyed by size name, in `output`.
    """
    proc = _get_cached_processor(sizes, backend)
    return proc.process_pil_image(pil_image, output, quality)


def create_thumbnails_from_bytes(
    image_bytes: bytes,
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> ThumbnailResult:
    """Create thumbnails from in-memory image bytes with processor caching.

    Args:
        image_bytes: Raw image (or PDF, per backend) data as bytes.
        sizes: Dictionary mapping size names to (width, height) tuples.
        output: Output format (JPEG, PNG, WEBP).
        quality: Image quality (1-100).
        backend: Backend selector; see FastImageProcessor for valid values.

    Returns:
        The thumbnails, keyed by size name, in `output`.
    """
    proc = _get_cached_processor(sizes, backend)
    return proc.process_image_bytes(image_bytes, output, quality)


def _demo() -> None:
    """Manual smoke test: run from a directory holding test.png, test.mp4 and test.pdf."""
    demo_sizes = {"large": (1024, 1024), "medium": (740, 740), "small": (200, 200)}
    demo_runs: list[tuple[str, BackendType, bool]] = [
        ("test.png", "image", True),
        ("test.png", "coreimage", _check_core_image_available()),
        ("test.png", "auto", True),
        ("test.mp4", "video", True),
        ("test.mp4", "corevideo", _check_avfoundation_available()),
        ("test.pdf", "pdf", True),
    ]

    print(f"Core Image: {_check_core_image_available()}, AVFoundation: {_check_avfoundation_available()}, PDFKit: {_check_pdfkit_available()}")
    for source, selector, available in demo_runs:
        if not available:
            print(f"{selector}: not available, skipped")
            continue
        processor = FastImageProcessor(demo_sizes, backend=selector)
        result = processor.process_image_file(source, output_format="JPEG", quality=85)
        byte_counts = " / ".join(f"{len(result.images[name]):,}" for name in demo_sizes)
        print(f"{selector} (using {processor.current_backend}) on {source}: {byte_counts} bytes, duration={result.duration}")
        for name, data in result.images.items():
            with open(f"test_thumb_{selector}_{name}.jpg", "wb") as output_file:
                output_file.write(data)


if __name__ == "__main__":
    _demo()
