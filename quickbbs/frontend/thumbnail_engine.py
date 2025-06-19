import platform
from typing import Literal

from Abstractbase_thumbnails import ImageBackend
from PIL import Image
from pil_thumbnails import PillowBackend

# In testing, a Memory leak message keeps arising when using Core Image.
# So we disable it for now.
# from quickbbs.frontend.core_image_thumbnails import CoreImageBackend
CORE_IMAGE_AVAILABLE = False

BackendType = Literal["pillow", "coreimage", "auto"]


class FastImageProcessor:
    """Multi-backend image processor with automatic backend selection."""

    def __init__(
        self, image_sizes: dict[str, tuple[int, int]], backend: BackendType = "auto"
    ):
        """
        Args:
            image_sizes: dict mapping size names to (width, height) tuples
            backend: Backend to use ("pillow", "coreimage", "auto")
        """
        self.image_sizes = image_sizes
        self.backend_type = backend
        self._backend = self._create_backend()

    def _create_backend(self) -> ImageBackend:
        """Create appropriate backend based on system and preference."""
        if self.backend_type == "pillow":
            return PillowBackend()
        # elif self.backend_type == "coreimage":
        #     if not CORE_IMAGE_AVAILABLE:
        #         raise ImportError("Core Image backend not available on this system")
        #     return CoreImageBackend()
        if self.backend_type == "auto":
            # Auto-select: Core Image on macOS with Apple Silicon, Pillow elsewhere
            if CORE_IMAGE_AVAILABLE and self._is_apple_silicon():
                try:
                    raise ValueError(f"{self.backend_type} is unavailable.")
                    # return CoreImageBackend()
                except Exception:
                    # Fall back to Pillow if Core Image setup fails
                    return PillowBackend()
            else:
                return PillowBackend()
        raise ValueError(f"Unknown backend: {self.backend_type}")

    def _is_apple_silicon(self) -> bool:
        """Check if running on Apple Silicon."""
        try:
            return (
                platform.system() == "Darwin"
                and platform.processor() == "arm"
                and "arm64" in platform.machine().lower()
            )
        except Exception:
            return False

    @property
    def current_backend(self) -> str:
        """Get name of currently active backend."""
        return type(self._backend).__name__

    def process_image_file(
        self, file_path: str, output_format: str = "JPEG", quality: int = 85
    ) -> dict[str, bytes]:
        """Process image file and generate multiple thumbnails."""
        return self._backend.process_from_file(
            file_path, self.image_sizes, output_format, quality
        )

    def process_image_bytes(
        self, image_bytes: bytes, output_format: str = "JPEG", quality: int = 85
    ) -> dict[str, bytes]:
        """Process image from bytes and generate multiple thumbnails."""
        return self._backend.process_from_memory(
            image_bytes, self.image_sizes, output_format, quality
        )

    def process_pil_image(
        self, pil_image: Image.Image, output_format: str = "JPEG", quality: int = 85
    ) -> dict[str, bytes]:
        """Process PIL Image object and generate multiple thumbnails."""
        return self._backend.process_data(
            pil_image, self.image_sizes, output_format, quality
        )


# Simplified interface functions
def create_thumbnails_from_path(
    file_path: str,
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from file path."""
    processor = FastImageProcessor(sizes, backend)
    return processor.process_image_file(file_path, output, quality)


def create_thumbnails_from_pil(
    pil_image: Image.Image,
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from PIL Image."""
    processor = FastImageProcessor(sizes, backend)
    return processor.process_pil_image(pil_image, output, quality)


def create_thumbnails_from_bytes(
    image_bytes: bytes,
    sizes: dict[str, tuple[int, int]],
    output: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from image bytes."""
    processor = FastImageProcessor(sizes, backend)
    return processor.process_image_bytes(image_bytes, output, quality)


# Integration with your existing code
# def pil_to_thumbnail_optimized(self, pil_data, backend: BackendType = "auto"):
#     """Optimized version of your pil_to_thumbnail method."""
#     self.invalidate_thumb()

#     # Create thumbnails in one pass
#     thumbnails = create_thumbnails_from_pil(
#         pil_data,
#         settings.IMAGE_SIZE,  # Your existing size settings
#         format="JPEG",
#         quality=85,
#         backend=backend,
#     )

#     # Set attributes
#     for size_name, thumb_bytes in thumbnails.items():
#         setattr(self, f"{size_name}_thumb", thumb_bytes)


# def image_to_thumbnail_optimized(self, backend: BackendType = "auto"):
#     """Optimized version of your image_to_thumbnail method."""
#     if self.IndexData.all().exists():
#         IndexData_item = self.IndexData.first()
#     else:
#         from quickbbs.models import IndexData

#         IndexData_item = IndexData.objects.get(file_sha256=self.sha256_hash)

#     filename = (
#         os.path.join(IndexData_item.fqpndirectory, IndexData_item.name).title().strip()
#     )

#     self.invalidate_thumb()

#     # Create all thumbnails in one pass - directly from file path
#     thumbnails = create_thumbnails_from_path(
#         filename, settings.IMAGE_SIZE, format="JPEG", quality=85, backend=backend
#     )

#     # Set attributes
#     for size_name, thumb_bytes in thumbnails.items():
#         setattr(self, f"{size_name}_thumb", thumb_bytes)

#     self.save(update_fields=["small_thumb", "medium_thumb", "large_thumb"])


# Usage examples


if __name__ == "__main__":

    def output_disk(filename, data):
        """Helper function to write bytes to a file."""
        with open(filename, "wb") as f:
            f.write(data)
        print(f"Saved {filename} with {len(data)} bytes.")

    image_filename = "image.png"
    IMAGE_SIZES = {"large": (800, 600), "medium": (400, 300), "small": (200, 150)}

    # Auto-select backend (Core Image on Apple Silicon, Pillow elsewhere)
    #    img_processor = FastImageProcessor(IMAGE_SIZES, backend="auto")
    #    print(f"Using backend: {img_processor.current_backend}")

    # Process image with auto-selected backend
    # thumbnails = processor.process_image_file(filename)

    # Force specific backend
    # quality: int = 85,
    # backend: BackendType = "auto",
    thumbnails_pillow = create_thumbnails_from_path(
        image_filename, IMAGE_SIZES, output="JPEG", backend="pillow"
    )
    print("CORE_IMAGE_AVAILABLE:", CORE_IMAGE_AVAILABLE)
    # On macOS with Core Image available
    if CORE_IMAGE_AVAILABLE:
        thumbnails_ci = create_thumbnails_from_path(
            image_filename, IMAGE_SIZES, output="JPEG", backend="coreimage"
        )

    # Access the binary data
    small_thumb_bytes = thumbnails_pillow["small"]
    medium_thumb_bytes = thumbnails_pillow["medium"]
    large_thumb_bytes = thumbnails_pillow["large"]
    print(
        f"Generated thumbnails: {len(small_thumb_bytes)} bytes (small), "
        f"{len(medium_thumb_bytes)} bytes (medium), "
        f"{len(large_thumb_bytes)} bytes (large)"
    )
    # Output to disk for verification
    output_disk("small_thumb.jpg", small_thumb_bytes)
    output_disk("medium_thumb.jpg", medium_thumb_bytes)
    output_disk("large_thumb.jpg", large_thumb_bytes)
    if CORE_IMAGE_AVAILABLE:
        output_disk("small_thumb_ci.jpg", thumbnails_ci["small"])
        output_disk("medium_thumb_ci.jpg", thumbnails_ci["medium"])
        output_disk("large_thumb_ci.jpg", thumbnails_ci["large"])
