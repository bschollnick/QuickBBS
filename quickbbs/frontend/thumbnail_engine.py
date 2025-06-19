import io
import os
import platform
import sys
from abc import ABC, abstractmethod
from typing import Literal, Optional, Union

from PIL import Image, ImageOps

# Core Image imports (macOS only)
try:
    import objc
    from Foundation import NSURL, NSData
    from UniformTypeIdentifiers import UTType
    objc.loadBundle('CoreImage', globals(), '/System/Library/Frameworks/CoreImage.framework')
    objc.loadBundle('CoreGraphics', globals(), '/System/Library/Frameworks/CoreGraphics.framework')
    from Quartz import (
        CGColorSpaceCreateDeviceRGB, 
        CGImageDestinationCreateWithData,
        CGImageDestinationAddImage, 
        CGImageDestinationFinalize,
        kCGImageDestinationLossyCompressionQuality,
        kCGColorSpaceSRGB, 
        kCIContextWorkingColorSpace,    )
    CORE_IMAGE_AVAILABLE = True
except ImportError:
    CORE_IMAGE_AVAILABLE = False

BackendType = Literal["pillow", "coreimage", "auto"]


class ImageBackend(ABC):
    """Abstract base class for image processing backends."""

    @abstractmethod
    def process_image_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        pass

    @abstractmethod
    def process_image_bytes(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        pass

    @abstractmethod
    def process_pil_image(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        pass


class PillowBackend(ImageBackend):
    """PIL/Pillow backend for cross-platform image processing."""

    def process_image_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        with Image.open(file_path) as img:
            return self._process_pil_image(img, sizes, output_format, quality)

    def process_image_bytes(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return self._process_pil_image(img, sizes, output_format, quality)

    def process_pil_image(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        img_copy = pil_image.copy()
        return self._process_pil_image(img_copy, sizes, output_format, quality)

    def _process_pil_image(
        self,
        img: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        results = {}

        # Convert to RGB if necessary
        if output_format.upper() == "JPEG" and img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            background.paste(
                img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None
            )
            img = background
        elif img.mode not in ("RGB", "RGBA", "L"):
            img = img.convert("RGB")

        # Auto-orient based on EXIF
        img = ImageOps.exif_transpose(img)

        # Sort sizes by area (largest first)
        sorted_sizes = sorted(
            sizes.items(), key=lambda x: x[1][0] * x[1][1], reverse=True
        )

        for size_name, target_size in sorted_sizes:
            working_img = img.copy()
            working_img.thumbnail(target_size, Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            save_kwargs = {"format": output_format}

            if output_format.upper() == "JPEG":
                save_kwargs.update(
                    {"quality": quality, "optimize": True, "progressive": True}
                )
            elif output_format.upper() == "PNG":
                save_kwargs.update({"optimize": True})
            elif output_format.upper() == "WEBP":
                save_kwargs.update({"quality": quality, "optimize": True})

            working_img.save(buffer, **save_kwargs)
            results[size_name] = buffer.getvalue()

        return results


class CoreImageBackend(ImageBackend):
    """Core Image backend for Apple Silicon GPU acceleration."""

    def __init__(self):
        if not CORE_IMAGE_AVAILABLE:
            raise ImportError(
                "Core Image not available. This backend requires macOS with pyobjc."
            )

        # Create GPU-accelerated Core Image context
        self.context = CIContext.contextWithOptions_(
            {
                # Use GPU acceleration
                "kCIContextUseSoftwareRenderer": False,
                # Use wide color gamut
                kCIContextWorkingColorSpace: CGColorSpaceCreateDeviceRGB(),
            }
        )

    def process_image_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        # Load image using Core Image
        file_url = NSURL.fileURLWithPath_(file_path)
        ci_image = CIImage.imageWithContentsOfURL_(file_url)

        if ci_image is None:
            raise ValueError(f"Could not load image from {file_path}")

        return self._process_ci_image(ci_image, sizes, output_format, quality)

    def process_image_bytes(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        # Convert bytes to NSData
        ns_data = NSData.dataWithBytes_length_(image_bytes, len(image_bytes))
        ci_image = CIImage.imageWithData_(ns_data)

        if ci_image is None:
            raise ValueError("Could not create CIImage from bytes")

        return self._process_ci_image(ci_image, sizes, output_format, quality)

    def process_pil_image(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        # Convert PIL image to bytes, then to Core Image
        buffer = io.BytesIO()

        # Ensure RGB mode for consistency
        if pil_image.mode not in ("RGB", "RGBA"):
            pil_image = pil_image.convert("RGB")

        # Auto-orient based on EXIF
        pil_image = ImageOps.exif_transpose(pil_image)

        # Save as PNG to preserve quality during conversion
        pil_image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        return self.process_image_bytes(image_bytes, sizes, output_format, quality)

    def _process_ci_image(
        self,
        ci_image: "CIImage",
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        results = {}

        # Get original image dimensions
        extent = ci_image.extent()
        original_width = extent.size.width
        original_height = extent.size.height

        # Sort sizes by area (largest first) for optimal processing
        sorted_sizes = sorted(
            sizes.items(), key=lambda x: x[1][0] * x[1][1], reverse=True
        )

        for size_name, (target_width, target_height) in sorted_sizes:
            # Calculate scale factor to fit within target size (maintaining aspect ratio)
            scale_x = target_width / original_width
            scale_y = target_height / original_height
            scale = min(scale_x, scale_y)

            # Apply GPU-accelerated scaling using Lanczos algorithm
            scale_filter = CIFilter.filterWithName_("CILanczosScaleTransform")
            scale_filter.setValue_forKey_(ci_image, "inputImage")
            scale_filter.setValue_forKey_(scale, "inputScale")
            scale_filter.setValue_forKey_(
                1.0, "inputAspectRatio"
            )  # Maintain aspect ratio

            scaled_image = scale_filter.outputImage()

            # Render to bytes
            image_bytes = self._render_to_bytes(scaled_image, output_format, quality)
            results[size_name] = image_bytes

        return results

    def _render_to_bytes(
        self, ci_image: "CIImage", output_format: str, quality: int
    ) -> bytes:
        """Render CIImage to bytes in specified format."""
        # Get image extent
        extent = ci_image.extent()

        # Render to CGImage
        cg_image = self.context.createCGImage_fromRect_(ci_image, extent)

        if cg_image is None:
            raise RuntimeError("Failed to create CGImage from CIImage")

        # Determine UTI type
        if output_format.upper() == "JPEG":
            uti_type = UTType.typeWithIdentifier_("public.jpeg")
        elif output_format.upper() == "PNG":
            uti_type = UTType.typeWithIdentifier_("public.png")
        elif output_format.upper() == "WEBP":
            uti_type = UTType.typeWithIdentifier_("org.webmproject.webp")
        else:
            raise ValueError(f"Unsupported output format: {output_format}")

        # Create mutable data for output
        output_data = NSData.data().mutableCopy()

        # Create image destination
        destination = CGImageDestinationCreateWithData(
            output_data, uti_type.identifier(), 1, None  # image count
        )

        if destination is None:
            raise RuntimeError(
                f"Failed to create image destination for {output_format}"
            )

        # Set properties
        properties = {}
        if output_format.upper() == "JPEG":
            properties[kCGImageDestinationLossyCompressionQuality] = quality / 100.0

        # Add image to destination
        CGImageDestinationAddImage(destination, cg_image, properties)

        # Finalize
        if not CGImageDestinationFinalize(destination):
            raise RuntimeError("Failed to finalize image destination")

        # Convert NSData to Python bytes
        return bytes(output_data)


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
        elif self.backend_type == "coreimage":
            if not CORE_IMAGE_AVAILABLE:
                raise ImportError("Core Image backend not available on this system")
            return CoreImageBackend()
        elif self.backend_type == "auto":
            # Auto-select: Core Image on macOS with Apple Silicon, Pillow elsewhere
            if CORE_IMAGE_AVAILABLE and self._is_apple_silicon():
                try:
                    return CoreImageBackend()
                except Exception:
                    # Fall back to Pillow if Core Image setup fails
                    return PillowBackend()
            else:
                return PillowBackend()
        else:
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
        return self._backend.process_image_file(
            file_path, self.image_sizes, output_format, quality
        )

    def process_image_bytes(
        self, image_bytes: bytes, output_format: str = "JPEG", quality: int = 85
    ) -> dict[str, bytes]:
        """Process image from bytes and generate multiple thumbnails."""
        return self._backend.process_image_bytes(
            image_bytes, self.image_sizes, output_format, quality
        )

    def process_pil_image(
        self, pil_image: Image.Image, output_format: str = "JPEG", quality: int = 85
    ) -> dict[str, bytes]:
        """Process PIL Image object and generate multiple thumbnails."""
        return self._backend.process_pil_image(
            pil_image, self.image_sizes, output_format, quality
        )


# Simplified interface functions
def create_thumbnails_from_path(
    file_path: str,
    sizes: dict[str, tuple[int, int]],
    format: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from file path."""
    processor = FastImageProcessor(sizes, backend)
    return processor.process_image_file(file_path, format, quality)


def create_thumbnails_from_pil(
    pil_image: Image.Image,
    sizes: dict[str, tuple[int, int]],
    format: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from PIL Image."""
    processor = FastImageProcessor(sizes, backend)
    return processor.process_pil_image(pil_image, format, quality)


def create_thumbnails_from_bytes(
    image_bytes: bytes,
    sizes: dict[str, tuple[int, int]],
    format: str = "JPEG",
    quality: int = 85,
    backend: BackendType = "auto",
) -> dict[str, bytes]:
    """Create thumbnails from image bytes."""
    processor = FastImageProcessor(sizes, backend)
    return processor.process_image_bytes(image_bytes, format, quality)


# Integration with your existing code
def pil_to_thumbnail_optimized(self, pil_data, backend: BackendType = "auto"):
    """Optimized version of your pil_to_thumbnail method."""
    self.invalidate_thumb()

    # Create thumbnails in one pass
    thumbnails = create_thumbnails_from_pil(
        pil_data,
        settings.IMAGE_SIZE,  # Your existing size settings
        format="JPEG",
        quality=85,
        backend=backend,
    )

    # Set attributes
    for size_name, thumb_bytes in thumbnails.items():
        setattr(self, f"{size_name}_thumb", thumb_bytes)


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


    filename = "image.png"
    IMAGE_SIZES = {"large": (800, 600), "medium": (400, 300), "small": (200, 150)}

    # Auto-select backend (Core Image on Apple Silicon, Pillow elsewhere)
    processor = FastImageProcessor(IMAGE_SIZES, backend="auto")
    print(f"Using backend: {processor.current_backend}")

    # Process image with auto-selected backend
    # thumbnails = processor.process_image_file(filename)

    # Force specific backend
    thumbnails_pillow = create_thumbnails_from_path(
        filename, IMAGE_SIZES, format="PNG", backend="pillow"
    )
    print("CORE_IMAGE_AVAILABLE:", CORE_IMAGE_AVAILABLE)
    # On macOS with Core Image available
    if CORE_IMAGE_AVAILABLE:
        thumbnails_ci = create_thumbnails_from_path(
            filename, IMAGE_SIZES, format="PNG", backend="coreimage"
        )

    # Access the binary data
    small_thumb_bytes = thumbnails_pillow["small"]
    medium_thumb_bytes = thumbnails_pillow["medium"]
    large_thumb_bytes = thumbnails_pillow["large"]
    print(f"Generated thumbnails: {len(small_thumb_bytes)} bytes (small), "
          f"{len(medium_thumb_bytes)} bytes (medium), "
          f"{len(large_thumb_bytes)} bytes (large)")
    # Output to disk for verification
    output_disk("small_thumb.jpg", small_thumb_bytes)
    output_disk("medium_thumb.jpg", medium_thumb_bytes)
    output_disk("large_thumb.jpg", large_thumb_bytes)
    if CORE_IMAGE_AVAILABLE:
        output_disk("small_thumb_ci.jpg", thumbnails_ci["small"])
        output_disk("medium_thumb_ci.jpg", thumbnails_ci["medium"])
        output_disk("large_thumb_ci.jpg", thumbnails_ci["large"])

        