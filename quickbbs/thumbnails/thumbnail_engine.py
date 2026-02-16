"""Multi-backend thumbnail generation engine with automatic backend selection."""

import platform
import threading
from typing import Literal

from PIL import Image

try:
    from .Abstractbase_thumbnails import AbstractBackend
    from .pdf_thumbnails import PDFBackend
    from .pil_thumbnails import ImageBackend
    from .video_thumbnails import VideoBackend
except ImportError:
    from Abstractbase_thumbnails import AbstractBackend
    from pdf_thumbnails import PDFBackend
    from pil_thumbnails import ImageBackend
    from video_thumbnails import VideoBackend

# CoreImage re-enabled 2026-02-12: GPU memory leak fixed by replacing
# createCGImage:fromRect: (IOSurface leak) with render:toBitmap: (direct
# CPU buffer), disabling intermediate caching, and using Metal command queue.
# See: claude_docs/macintosh_optimizations_memory.md for full analysis.
try:
    from .core_image_thumbnails import CoreImageBackend

    CORE_IMAGE_AVAILABLE = True
except ImportError:
    CORE_IMAGE_AVAILABLE = False

# AVFoundation and PDFKit remain disabled — they use CoreImage internally
# and would need similar fixes before re-enabling.
AVFOUNDATION_AVAILABLE = False
PDFKIT_AVAILABLE = False

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

    def _get_cached_backend(self) -> AbstractBackend:
        """Get or create cached backend instance for reuse (thread-safe)."""
        with self._backend_lock:
            if self.backend_type not in self._backend_cache:
                self._backend_cache[self.backend_type] = self._create_backend()
            return self._backend_cache[self.backend_type]

    def _create_backend(self) -> AbstractBackend:
        """Create appropriate backend based on system and preference."""
        match self.backend_type:
            case "image":
                return ImageBackend()
            case "coreimage":
                if not CORE_IMAGE_AVAILABLE:
                    raise ImportError("Core Image backend not available on this system")
                return CoreImageBackend()
            case "video":
                return VideoBackend()
            case "corevideo":
                # DISABLED 2025-12-02: AVFoundation uses CoreImage internally (GPU memory leak)
                # if not AVFOUNDATION_AVAILABLE:
                #     raise ImportError("AVFoundation backend not available on this system")
                # return AVFoundationVideoBackend()
                return VideoBackend()  # Fall back to ffmpeg-based backend
            case "pdf":
                # DISABLED 2025-12-02: PDFKit disabled due to GPU memory concerns
                # Auto-select: Prefer PDFKit on Apple Silicon if available, fallback to PyMuPDF
                # if PDFKIT_AVAILABLE and self._is_apple_silicon():
                #     try:
                #         return PDFKitBackend()
                #     except Exception:
                #         # Fall back to PyMuPDF if PDFKit initialization fails
                #         return PDFBackend()
                # else:
                #     return PDFBackend()
                return PDFBackend()  # Always use PyMuPDF (CPU-based)
            case "pymupdf":
                return PDFBackend()
            case "pdfkit":
                # DISABLED 2025-12-02: PDFKit has GPU memory concerns
                # if not PDFKIT_AVAILABLE:
                #     raise ImportError("PDFKit backend not available on this system")
                # return PDFKitBackend()
                return PDFBackend()  # Fall back to PyMuPDF
            case "auto":
                # Prefer Core Image on Apple Silicon for GPU-accelerated Lanczos
                if CORE_IMAGE_AVAILABLE and self._is_apple_silicon():
                    try:
                        return CoreImageBackend()
                    except Exception:
                        return ImageBackend()
                else:
                    return ImageBackend()
            case _:
                raise ValueError(f"Unknown backend type: {self.backend_type}")

    def _is_apple_silicon(self) -> bool:
        """Check if running on Apple Silicon."""
        try:
            return platform.system() == "Darwin" and platform.processor() == "arm" and "arm64" in platform.machine().lower()
        except Exception:
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

    def process_pil_image(self, pil_image: Image.Image, output_format: str = "JPEG", quality: int = 85) -> dict[str, bytes]:
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
    pil_image: Image.Image,
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
    print(f"Core Image Available: {CORE_IMAGE_AVAILABLE}")
    print(f"AVFoundation Available: {AVFOUNDATION_AVAILABLE}")
    print(f"PDFKit Available: {PDFKIT_AVAILABLE}")
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
    if CORE_IMAGE_AVAILABLE:
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
    if AVFOUNDATION_AVAILABLE:
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
