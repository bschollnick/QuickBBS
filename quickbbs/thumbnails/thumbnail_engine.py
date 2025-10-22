"""Multi-backend thumbnail generation engine with automatic backend selection."""

import platform
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

# Try to import Core Image and AVFoundation backends (macOS only)
CORE_IMAGE_AVAILABLE = False
AVFOUNDATION_AVAILABLE = False
PDFKIT_AVAILABLE = False

try:
    from .core_image_thumbnails import CORE_IMAGE_AVAILABLE as _CI_AVAIL
    from .core_image_thumbnails import CoreImageBackend

    CORE_IMAGE_AVAILABLE = _CI_AVAIL
except ImportError:
    try:
        from core_image_thumbnails import CORE_IMAGE_AVAILABLE as _CI_AVAIL
        from core_image_thumbnails import CoreImageBackend

        CORE_IMAGE_AVAILABLE = _CI_AVAIL
    except ImportError:
        CoreImageBackend = None

try:
    from .avfoundation_video_thumbnails import AVFOUNDATION_AVAILABLE as _AV_AVAIL
    from .avfoundation_video_thumbnails import AVFoundationVideoBackend

    AVFOUNDATION_AVAILABLE = _AV_AVAIL
except ImportError:
    try:
        from avfoundation_video_thumbnails import AVFOUNDATION_AVAILABLE as _AV_AVAIL
        from avfoundation_video_thumbnails import AVFoundationVideoBackend

        AVFOUNDATION_AVAILABLE = _AV_AVAIL
    except ImportError:
        AVFoundationVideoBackend = None

try:
    from .pdfkit_thumbnails import PDFKIT_AVAILABLE as _PDF_AVAIL
    from .pdfkit_thumbnails import PDFKitBackend

    PDFKIT_AVAILABLE = _PDF_AVAIL
except ImportError:
    try:
        from pdfkit_thumbnails import PDFKIT_AVAILABLE as _PDF_AVAIL
        from pdfkit_thumbnails import PDFKitBackend

        PDFKIT_AVAILABLE = _PDF_AVAIL
    except ImportError:
        PDFKitBackend = None

BackendType = Literal["image", "coreimage", "auto", "video", "corevideo", "pdf", "pymupdf", "pdfkit"]


class FastImageProcessor:
    """Multi-backend image processor with automatic backend selection and caching."""

    # Class-level backend cache to reuse backend instances
    _backend_cache = {}

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
        """Get or create cached backend instance for reuse."""
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
                if not AVFOUNDATION_AVAILABLE:
                    raise ImportError("AVFoundation backend not available on this system")
                return AVFoundationVideoBackend()
            case "pdf":
                # Auto-select: Prefer PDFKit on Apple Silicon if available, fallback to PyMuPDF
                if PDFKIT_AVAILABLE and self._is_apple_silicon():
                    try:
                        return PDFKitBackend()
                    except Exception:
                        # Fall back to PyMuPDF if PDFKit initialization fails
                        return PDFBackend()
                else:
                    return PDFBackend()
            case "pymupdf":
                return PDFBackend()
            case "pdfkit":
                if not PDFKIT_AVAILABLE:
                    raise ImportError("PDFKit backend not available on this system")
                return PDFKitBackend()
            case "auto":
                # Auto-select: Prefer Core Image on Apple Silicon if available, fallback to PIL
                if CORE_IMAGE_AVAILABLE and self._is_apple_silicon():
                    try:
                        return CoreImageBackend()
                    except Exception:
                        # Fall back to PIL if Core Image initialization fails
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


# Global processor cache for common size configurations
_processor_cache = {}


def _get_cached_processor(sizes: dict[str, tuple[int, int]], backend: BackendType) -> FastImageProcessor:
    """Get or create cached processor for common configurations."""
    cache_key = (tuple(sorted(sizes.items())), backend)
    if cache_key not in _processor_cache:
        _processor_cache[cache_key] = FastImageProcessor(sizes, backend)
    return _processor_cache[cache_key]


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
