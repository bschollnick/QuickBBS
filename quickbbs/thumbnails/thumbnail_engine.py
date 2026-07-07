"""Multi-backend thumbnail generation engine with automatic backend selection.

Backend imports are deferred to first use to avoid loading heavy libraries
(PyMuPDF/fitz, ffmpeg, macOS frameworks) at Django startup time.
"""

import logging
import os
import platform
import threading
from typing import TYPE_CHECKING, Literal

try:
    from .exceptions import UnsupportedFormatError
except ImportError:
    from exceptions import UnsupportedFormatError

if __package__ in (None, ""):
    # Running standalone (python thumbnail_engine.py): put the parent directory
    # on sys.path and adopt the package name (PEP 366) so the lazy relative
    # backend imports inside _create_backend resolve at call time.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "thumbnails"  # noqa: A001

logger = logging.getLogger(__name__)

# Availability is checked lazily on first use
_core_image_available: bool | None = None
_avfoundation_available: bool | None = None
_pdfkit_available: bool | None = None


def macintosh_optimizations_enabled() -> bool:
    """Return True if macOS-accelerated backends may be auto-selected.

    Reads settings.MACINTOSH_OPTIMIZATIONS when Django is configured. Outside a
    Django context (standalone scripts, benchmarks, the __main__ block below) the
    hardware backends remain selectable, since the setting is an application
    concern. Explicit backend requests ("coreimage", "pdfkit") are never gated
    by this — only the auto-selecting cases ("auto", "corevideo", "pdf").

    Returns:
        True if the macOS backends may be chosen automatically, False otherwise.
    """
    try:
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured

        try:
            return bool(getattr(settings, "MACINTOSH_OPTIMIZATIONS", False))
        except ImproperlyConfigured:
            return True
    except ImportError:
        return True


def is_apple_silicon() -> bool:
    """Return True if running on Apple Silicon (arm64 macOS).

    Returns:
        True if the current process is running on Apple Silicon, False otherwise.
    """
    try:
        return platform.system() == "Darwin" and platform.processor() == "arm" and "arm64" in platform.machine().lower()
    except OSError:
        return False


def _check_core_image_available() -> bool:
    """Check if Core Image backend is available (cached after first call)."""
    global _core_image_available
    if _core_image_available is None:
        try:
            from .core_image_thumbnails import (  # noqa: F401  # pylint: disable=unused-import  # imported to verify availability via try/except; not used directly
                CoreImageBackend,
            )

            _core_image_available = True
        except ImportError:
            _core_image_available = False
    return _core_image_available


def _check_avfoundation_available() -> bool:
    """Check if AVFoundation backend is available (cached after first call)."""
    global _avfoundation_available
    if _avfoundation_available is None:
        try:
            from . import avfoundation_video_thumbnails as _av_mod

            _avfoundation_available = _av_mod.AVFOUNDATION_AVAILABLE
        except ImportError:
            _avfoundation_available = False
    return _avfoundation_available


def _check_pdfkit_available() -> bool:
    """Check if PDFKit backend is available (cached after first call)."""
    global _pdfkit_available
    if _pdfkit_available is None:
        try:
            from . import pdfkit_thumbnails as _pdf_mod

            _pdfkit_available = _pdf_mod.PDFKIT_AVAILABLE
        except ImportError:
            _pdfkit_available = False
    return _pdfkit_available


if TYPE_CHECKING:
    from PIL import Image

    from .Abstractbase_thumbnails import AbstractBackend

BackendType = Literal["image", "coreimage", "auto", "video", "corevideo", "pdf", "pymupdf", "pdfkit"]


class FastImageProcessor:
    """Multi-backend image processor with automatic backend selection and caching."""

    __slots__ = ("image_sizes", "backend_type", "_backend")

    # Class-level backend cache to reuse backend instances.
    # Protected by _backend_lock for thread safety in multi-threaded workers.
    _backend_cache: dict = {}
    _backend_lock = threading.Lock()

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
        with self._backend_lock:
            if self.backend_type not in self._backend_cache:
                backend = self._create_backend()
                logger.info(
                    "Thumbnail backend resolved: %r -> %s (macintosh optimizations %s)",
                    self.backend_type,
                    type(backend).__name__,
                    "enabled" if macintosh_optimizations_enabled() else "disabled",
                )
                self._backend_cache[self.backend_type] = backend
            return self._backend_cache[self.backend_type]

    def _create_backend(self):
        """Create appropriate backend based on system and preference.

        Returns:
            Backend instance for the configured backend type

        Raises:
            UnsupportedFormatError: If the configured backend type is not recognised.
        """
        # Lazy imports — each backend pulls in heavy dependencies (PIL, fitz, ffmpeg, macOS frameworks)
        # Only the backend actually used gets imported.
        match self.backend_type:
            case "image":
                from .pil_thumbnails import ImageBackend

                return ImageBackend()
            case "coreimage":
                if not _check_core_image_available():
                    raise ImportError("Core Image backend not available on this system")
                from .core_image_thumbnails import CoreImageBackend

                return CoreImageBackend()
            case "video":
                from .video_thumbnails import VideoBackend

                return VideoBackend()
            case "corevideo":
                if macintosh_optimizations_enabled() and _check_avfoundation_available():
                    from .avfoundation_video_thumbnails import AVFoundationVideoBackend

                    return AVFoundationVideoBackend()
                from .video_thumbnails import VideoBackend

                return VideoBackend()
            case "pdf":
                # Prefer PDFKit on Apple Silicon, fall back to PyMuPDF elsewhere
                if macintosh_optimizations_enabled() and _check_pdfkit_available() and self._is_apple_silicon():
                    from .pdfkit_thumbnails import PDFKitBackend

                    return PDFKitBackend()
                from .pdf_thumbnails import PDFBackend

                return PDFBackend()
            case "pymupdf":
                from .pdf_thumbnails import PDFBackend

                return PDFBackend()
            case "pdfkit":
                if _check_pdfkit_available():
                    from .pdfkit_thumbnails import PDFKitBackend

                    return PDFKitBackend()
                from .pdf_thumbnails import PDFBackend

                return PDFBackend()
            case "auto":
                # Prefer Core Image on Apple Silicon for GPU-accelerated Lanczos
                if macintosh_optimizations_enabled() and _check_core_image_available() and self._is_apple_silicon():
                    try:
                        from .core_image_thumbnails import CoreImageBackend

                        return CoreImageBackend()
                    except (ImportError, RuntimeError, OSError):
                        pass
                from .pil_thumbnails import ImageBackend

                return ImageBackend()
            case _:
                raise UnsupportedFormatError(self.backend_type)

    def _is_apple_silicon(self) -> bool:
        """Check if running on Apple Silicon."""
        return is_apple_silicon()

    @property
    def current_backend(self) -> str:
        """Get name of currently active backend."""
        return type(self._backend).__name__

    def process_image_file(self, file_path: str, output_format: str = "JPEG", quality: int = 85) -> dict[str, bytes]:
        """Process image file and generate multiple thumbnails."""
        return self._backend.process_from_file(file_path, self.image_sizes, output_format, quality)

    def process_image_bytes(self, image_bytes: bytes, output_format: str = "JPEG", quality: int = 85) -> dict[str, bytes]:
        """Process image from bytes and generate multiple thumbnails."""
        return self._backend.process_from_memory(image_bytes, self.image_sizes, output_format, quality)

    def process_pil_image(
        self, pil_image: "Image.Image", output_format: str = "JPEG", quality: int = 85
    ) -> dict[str, bytes]:  # pylint: disable=used-before-assignment
        """Process PIL Image object and generate multiple thumbnails."""
        return self._backend.process_data(pil_image, self.image_sizes, output_format, quality)


# Global processor cache for common size configurations.
# Protected by _processor_lock for thread safety in multi-threaded workers.
_processor_cache: dict = {}
_processor_lock = threading.Lock()


def _fork_acquire_locks() -> None:
    """Serialize fork against cache mutation so no lock is held mid-fork.

    Acquired in fixed order (processor, then backend) to avoid lock-order
    inversion with _fork_release_locks_parent.
    """
    _processor_lock.acquire()
    FastImageProcessor._backend_lock.acquire()


def _fork_release_locks_parent() -> None:
    """Release the fork-serialization locks in the parent (reverse order)."""
    FastImageProcessor._backend_lock.release()
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
    global _processor_lock
    _processor_lock = threading.Lock()
    FastImageProcessor._backend_lock = threading.Lock()
    _processor_cache.clear()
    FastImageProcessor._backend_cache.clear()


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
    global _processor_cache

    # Clear caches under their respective locks
    with _processor_lock:
        processors_cleared = len(_processor_cache)
        _processor_cache.clear()

    with FastImageProcessor._backend_lock:
        backends_cleared = len(FastImageProcessor._backend_cache)
        FastImageProcessor._backend_cache.clear()

    # Optional garbage collection to force cleanup
    if force_gc:
        import gc
        import resource

        # Measure memory before GC
        usage_before = resource.getrusage(resource.RUSAGE_SELF)
        rss_before_kb = usage_before.ru_maxrss

        # Force collection of all generations
        collected = gc.collect(generation=2)

        # Measure memory after GC
        usage_after = resource.getrusage(resource.RUSAGE_SELF)
        rss_after_kb = usage_after.ru_maxrss

        # Calculate freed memory (may be negative due to OS caching)
        memory_freed_kb = rss_before_kb - rss_after_kb
        memory_freed_mb = memory_freed_kb / 1024  # Convert to MB
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
        "backend_cache_size": len(FastImageProcessor._backend_cache),
        "total_cached_instances": len(_processor_cache) + len(FastImageProcessor._backend_cache),
    }


# Simplified interface functions
def create_thumbnails_from_path(
    file_path: str,
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
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
        Dictionary mapping size names to thumbnail bytes. Video and PDF
        backends also include 'format' (and videos 'duration') keys.

    Example:
        >>> thumbs = create_thumbnails_from_path(
        ...     "/albums/photos/cover.jpg",
        ...     settings.IMAGE_SIZE,
        ...     output="JPEG",
        ...     quality=85,
        ...     backend="auto",
        ... )
        >>> len(thumbs["small"]) > 0
        True
    """
    proc = _get_cached_processor(sizes, backend)
    return proc.process_image_file(file_path, output, quality)


def create_thumbnails_from_pil(
    pil_image: "Image.Image",  # pylint: disable=used-before-assignment
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from a PIL Image with processor caching.

    Args:
        pil_image: PIL Image object to process.
        sizes: Dictionary mapping size names to (width, height) tuples.
        output: Output format (JPEG, PNG, WEBP).
        quality: Image quality (1-100).
        backend: Backend selector; see FastImageProcessor for valid values.

    Returns:
        Dictionary mapping size names to thumbnail bytes.
    """
    proc = _get_cached_processor(sizes, backend)
    return proc.process_pil_image(pil_image, output, quality)


def create_thumbnails_from_bytes(
    image_bytes: bytes,
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from in-memory image bytes with processor caching.

    Args:
        image_bytes: Raw image (or PDF, per backend) data as bytes.
        sizes: Dictionary mapping size names to (width, height) tuples.
        output: Output format (JPEG, PNG, WEBP).
        quality: Image quality (1-100).
        backend: Backend selector; see FastImageProcessor for valid values.

    Returns:
        Dictionary mapping size names to thumbnail bytes.
    """
    proc = _get_cached_processor(sizes, backend)
    return proc.process_image_bytes(image_bytes, output, quality)


if __name__ == "__main__":

    def output_disk(filename, data):
        """Helper function to write bytes to a file."""
        with open(filename, "wb") as f:
            f.write(data)
        print(f"Saved {filename} with {len(data):,} bytes.")

    print("=" * 60)
    print("Backend Availability")
    print("=" * 60)
    print(f"Core Image Available: {_check_core_image_available()}")
    print(f"AVFoundation Available: {_check_avfoundation_available()}")
    print(f"PDFKit Available: {_check_pdfkit_available()}")
    print()

    # Test image processing
    image_filename = "test.png"
    IMAGE_SIZES = {"large": (1024, 1024), "medium": (740, 740), "small": (200, 200)}

    print("=" * 60)
    print("Testing Image Backends")
    print("=" * 60)

    # Test PIL backend
    thumbnails_pil = create_thumbnails_from_path(image_filename, IMAGE_SIZES, output="JPEG", backend="image")
    print(f"PIL Backend: {len(thumbnails_pil['small']):,} / {len(thumbnails_pil['medium']):,} / {len(thumbnails_pil['large']):,} bytes")
    output_disk("test_thumb_pil_small.jpg", thumbnails_pil["small"])
    output_disk("test_thumb_pil_medium.jpg", thumbnails_pil["medium"])
    output_disk("test_thumb_pil_large.jpg", thumbnails_pil["large"])

    # Test Core Image backend if available
    if _check_core_image_available():
        thumbnails_ci = create_thumbnails_from_path(image_filename, IMAGE_SIZES, output="JPEG", backend="coreimage")
        print(f"Core Image Backend: {len(thumbnails_ci['small']):,} / {len(thumbnails_ci['medium']):,} / {len(thumbnails_ci['large']):,} bytes")
        output_disk("test_thumb_ci_small.jpg", thumbnails_ci["small"])
        output_disk("test_thumb_ci_medium.jpg", thumbnails_ci["medium"])
        output_disk("test_thumb_ci_large.jpg", thumbnails_ci["large"])

    # Test auto backend
    thumbnails_auto = create_thumbnails_from_path(image_filename, IMAGE_SIZES, output="JPEG", backend="auto")
    processor = _get_cached_processor(IMAGE_SIZES, "auto")
    print(
        f"Auto Backend (using {processor.current_backend}): {len(thumbnails_auto['small']):,} / {len(thumbnails_auto['medium']):,} / {len(thumbnails_auto['large']):,} bytes"
    )

    print()
    print("=" * 60)
    print("Testing Video Backends")
    print("=" * 60)

    # Test video processing
    video_filename = "test.mp4"
    VIDEO_SIZES = {"large": (1024, 1024), "medium": (740, 740), "small": (200, 200)}

    # Test FFmpeg backend
    processor_ffmpeg = FastImageProcessor(VIDEO_SIZES, backend="video")
    thumbnails_ffmpeg = processor_ffmpeg.process_image_file(video_filename, output_format="JPEG", quality=85)
    print(
        f"FFmpeg Backend: Duration={thumbnails_ffmpeg.get('duration', 'N/A')}s, Sizes: {len(thumbnails_ffmpeg['small']):,} / {len(thumbnails_ffmpeg['medium']):,} / {len(thumbnails_ffmpeg['large']):,} bytes"
    )
    output_disk("test_thumb_ffmpeg_small.jpg", thumbnails_ffmpeg["small"])
    output_disk("test_thumb_ffmpeg_medium.jpg", thumbnails_ffmpeg["medium"])
    output_disk("test_thumb_ffmpeg_large.jpg", thumbnails_ffmpeg["large"])

    # Test AVFoundation backend if available
    if _check_avfoundation_available():
        processor_av = FastImageProcessor(VIDEO_SIZES, backend="corevideo")
        thumbnails_av = processor_av.process_image_file(video_filename, output_format="JPEG", quality=85)
        print(
            f"AVFoundation Backend: Duration={thumbnails_av.get('duration', 'N/A')}s, Sizes: {len(thumbnails_av['small']):,} / {len(thumbnails_av['medium']):,} / {len(thumbnails_av['large']):,} bytes"
        )
        output_disk("test_thumb_av_small.jpg", thumbnails_av["small"])
        output_disk("test_thumb_av_medium.jpg", thumbnails_av["medium"])
        output_disk("test_thumb_av_large.jpg", thumbnails_av["large"])

    print()
    print("=" * 60)
    print("Testing PDF Backends")
    print("=" * 60)

    # Test PDF processing
    pdf_filename = "test.pdf"
    PDF_SIZES = {"large": (1024, 1024), "medium": (740, 740), "small": (200, 200)}

    # Test PDF backend (auto-selects PDFKit on Apple Silicon, PyMuPDF otherwise)
    processor_pdf = FastImageProcessor(PDF_SIZES, backend="pdf")
    thumbnails_pdf = processor_pdf.process_image_file(pdf_filename, output_format="JPEG", quality=85)
    print(
        f"PDF Backend (using {processor_pdf.current_backend}): Sizes: {len(thumbnails_pdf['small']):,} / {len(thumbnails_pdf['medium']):,} / {len(thumbnails_pdf['large']):,} bytes"
    )
    output_disk("test_thumb_pdf_small.jpg", thumbnails_pdf["small"])
    output_disk("test_thumb_pdf_medium.jpg", thumbnails_pdf["medium"])
    output_disk("test_thumb_pdf_large.jpg", thumbnails_pdf["large"])
