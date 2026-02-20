"""Multi-backend thumbnail generation engine with automatic backend selection.

Backend imports are deferred to first use to avoid loading heavy libraries
(PyMuPDF/fitz, ffmpeg, macOS frameworks) at Django startup time.
"""

import platform
import threading
from typing import TYPE_CHECKING, Literal

# Availability is checked lazily on first use
_core_image_available: bool | None = None
_avfoundation_available: bool | None = None
_pdfkit_available: bool | None = None


def _check_core_image_available() -> bool:
    """Check if Core Image backend is available (cached after first call)."""
    global _core_image_available
    if _core_image_available is None:
        try:
            from .core_image_thumbnails import CoreImageBackend  # noqa: F401  # imported to verify availability via try/except; not used directly

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
        Args:
            image_sizes: dict mapping size names to (width, height) tuples
            backend: Backend to use ("image", "coreimage", "auto")
        """
        self.image_sizes = image_sizes
        self.backend_type = backend.lower()
        self._backend = self._get_cached_backend()

    def _get_cached_backend(self):
        """Get or create cached backend instance for reuse (thread-safe)."""
        with self._backend_lock:
            if self.backend_type not in self._backend_cache:
                self._backend_cache[self.backend_type] = self._create_backend()
            return self._backend_cache[self.backend_type]

    def _create_backend(self):
        """Create appropriate backend based on system and preference.

        Returns:
            Backend instance for the configured backend type
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
                if _check_avfoundation_available():
                    from .avfoundation_video_thumbnails import AVFoundationVideoBackend

                    return AVFoundationVideoBackend()
                from .video_thumbnails import VideoBackend

                return VideoBackend()
            case "pdf":
                # Prefer PDFKit on Apple Silicon, fall back to PyMuPDF elsewhere
                if _check_pdfkit_available() and self._is_apple_silicon():
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
                if _check_core_image_available() and self._is_apple_silicon():
                    try:
                        from .core_image_thumbnails import CoreImageBackend

                        return CoreImageBackend()
                    except (ImportError, RuntimeError, OSError):
                        pass
                from .pil_thumbnails import ImageBackend

                return ImageBackend()
            case _:
                raise ValueError(f"Unknown backend type: {self.backend_type}")

    def _is_apple_silicon(self) -> bool:
        """Check if running on Apple Silicon."""
        try:
            return platform.system() == "Darwin" and platform.processor() == "arm" and "arm64" in platform.machine().lower()
        except OSError:
            return False

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


def _get_cached_processor(sizes: dict[str, tuple[int, int]], backend: BackendType) -> FastImageProcessor:
    """Get or create cached processor for common configurations (thread-safe)."""
    cache_key = (tuple(sorted(sizes.items())), backend)
    with _processor_lock:
        if cache_key not in _processor_cache:
            _processor_cache[cache_key] = FastImageProcessor(sizes, backend)
        return _processor_cache[cache_key]


def clear_backend_caches(force_gc: bool = True) -> dict[str, int]:
    """
    Clear cached processor and backend instances to release resources.

    Call this periodically (e.g., after processing batches of thumbnails)
    to release accumulated resources in both the processor cache and
    the backend cache.

    This is particularly important for Core Image backends on macOS, where
    CIContext instances accumulate GPU resources. Clearing caches forces
    recreation of these instances, releasing GPU memory.

    :Args:
        force_gc: If True, run garbage collection after clearing caches

    :return: Dictionary with cache statistics:
        - processors_cleared: Number of processor instances cleared
        - backends_cleared: Number of backend instances cleared
        - gc_objects_collected: Number of objects collected by GC
        - memory_freed_mb: Estimated memory freed (if available)

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

    :return: Dictionary with current cache statistics:
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
    """Create thumbnails from file path with processor caching."""
    proc = _get_cached_processor(sizes, backend)
    return proc.process_image_file(file_path, output, quality)


def create_thumbnails_from_pil(
    pil_image: "Image.Image",  # pylint: disable=used-before-assignment
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from PIL Image with processor caching."""
    proc = _get_cached_processor(sizes, backend)
    return proc.process_pil_image(pil_image, output, quality)


def create_thumbnails_from_bytes(
    image_bytes: bytes,
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from image bytes with processor caching."""
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
