# Core Image imports (macOS only)
"""Core Image backend for thumbnail generation using macOS GPU acceleration."""

import io
import os
from contextlib import contextmanager

from PIL import Image, ImageOps

# Try to import Core Image and related macOS frameworks
try:
    import ctypes

    import objc
    from Foundation import NSURL, NSAutoreleasePool, NSData
    from Quartz import (
        CGColorSpaceCreateDeviceRGB,
        CIContext,
        CIFilter,
        CIImage,
        kCIContextCacheIntermediates,
        kCIContextUseSoftwareRenderer,
        kCIContextWorkingColorSpace,
        kCIFormatRGBA8,
    )

    CORE_IMAGE_AVAILABLE = True

    # Fork-safe Metal device cache: tracks the PID to detect post-fork scenarios.
    # After os.fork(), the child inherits the parent's Metal device pointer, but
    # the underlying Mach ports are dead. Re-creating the device in the child
    # process is the only safe option.
    _metal_device_cache: dict[str, object] = {"device": None, "pid": None}

    def _create_metal_device():
        """
        Create or reuse a fork-safe Metal device.

        Uses ctypes to call MTLCreateSystemDefaultDevice since pyobjc-framework-Metal
        is not installed. Caches the device per-PID so that forked child processes
        get a fresh device instead of inheriting a stale one with dead Mach ports.

        Returns:
            PyObjC Metal device object, or None if Metal is unavailable
        """
        current_pid = os.getpid()
        cached = _metal_device_cache["device"]
        if cached is not None and _metal_device_cache["pid"] == current_pid:
            return cached

        # Either first call or post-fork — (re)create
        try:
            metal_lib = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Metal.framework/Metal")
            func = metal_lib.MTLCreateSystemDefaultDevice
            func.restype = ctypes.c_void_p
            func.argtypes = []
            device_ptr = func()
            if device_ptr:
                device = objc.objc_object(c_void_p=ctypes.c_void_p(device_ptr))
                _metal_device_cache["device"] = device
                _metal_device_cache["pid"] = current_pid
                return device
        except (OSError, AttributeError):
            pass
        return None

except ImportError:
    CORE_IMAGE_AVAILABLE = False
    _create_metal_device = None  # type: ignore[assignment]

try:
    from .Abstractbase_thumbnails import AbstractBackend
except ImportError:
    from Abstractbase_thumbnails import AbstractBackend


@contextmanager
def autorelease_pool():
    """
    Context manager for Objective-C autorelease pool.

    CRITICAL for PyObjC memory management: Wraps operations that create
    autoreleased Objective-C objects (CIImage, CGImage, NSData, etc.) to
    ensure they are properly drained and don't accumulate in memory.

    Without explicit autorelease pools, Objective-C objects accumulate
    in the current thread's autorelease pool and may never be drained
    in a long-running Django worker, causing memory leaks.

    Returns:
        Context manager that creates and drains an NSAutoreleasePool

    Example:
        >>> with autorelease_pool():
        ...     ci_image = CIImage.imageWithContentsOfURL_(url)
        ...     # Process image
        ...     # Pool automatically drained on exit
    """
    pool = NSAutoreleasePool.alloc().init()
    try:
        yield pool
    finally:
        del pool


class CoreImageBackend(AbstractBackend):
    """Core Image backend for Apple Silicon GPU acceleration with memory management."""

    def __init__(self):
        if not CORE_IMAGE_AVAILABLE:
            raise ImportError("Core Image not available. This backend requires macOS with pyobjc.")

        with autorelease_pool():
            self._context = None
            self._color_space = CGColorSpaceCreateDeviceRGB()

            # Metal command queue for explicit GPU resource lifecycle management
            # Per WWDC 2020/10008: CIContext.contextWithMTLCommandQueue:options:
            # gives better resource management than contextWithOptions:
            self._metal_device = _create_metal_device()
            if self._metal_device is None:
                raise ImportError("Metal GPU device not available")
            try:
                self._command_queue = self._metal_device.newCommandQueue()
            except Exception as e:
                raise ImportError(f"Metal command queue creation failed (post-fork?): {e}") from e

    @property
    def context(self) -> "CIContext":
        """
        Get long-lived CIContext backed by a Metal command queue.

        Uses Metal command queue for explicit GPU resource lifecycle management
        and disables intermediate caching to prevent GPU memory accumulation
        during batch thumbnail processing (per WWDC 2020/10008).

        Returns:
            CIContext instance
        """
        if self._context is None:
            self._context = CIContext.contextWithMTLCommandQueue_options_(
                self._command_queue,
                {
                    kCIContextUseSoftwareRenderer: False,
                    kCIContextWorkingColorSpace: self._color_space,
                    # CRITICAL: Disable intermediate caching for batch processing.
                    # Every thumbnail is a different image, so cached intermediates
                    # are never reused but accumulate in GPU memory.
                    kCIContextCacheIntermediates: False,
                },
            )
        return self._context

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process image file and generate thumbnails using Core Image.

        :Args:
            file_path: Path to the image file
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
        # Wrap entire operation in autorelease pool to drain Objective-C objects
        with autorelease_pool():
            # Load image using Core Image
            file_url = NSURL.fileURLWithPath_(file_path)
            ci_image = CIImage.imageWithContentsOfURL_(file_url)

            if ci_image is None:
                raise ValueError(f"Could not load image from {file_path}")

            return self._process_ci_image(ci_image, sizes, output_format, quality)

    def process_from_memory(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process image from memory and generate thumbnails using Core Image.

        :Args:
            image_bytes: Image data as bytes
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
        # Wrap entire operation in autorelease pool to drain Objective-C objects
        with autorelease_pool():
            # Convert bytes to NSData
            ns_data = NSData.dataWithBytes_length_(image_bytes, len(image_bytes))
            ci_image = CIImage.imageWithData_(ns_data)

            if ci_image is None:
                raise ValueError("Could not create CIImage from bytes")

            return self._process_ci_image(ci_image, sizes, output_format, quality)

    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process PIL Image object and generate thumbnails using Core Image.

        :Args:
            pil_image: PIL Image object to process
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
        # Wrap entire operation in autorelease pool to drain Objective-C objects
        with autorelease_pool():
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

            return self.process_from_memory(image_bytes, sizes, output_format, quality)

    def _process_ci_image(
        self,
        ci_image: "CIImage",
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process Core Image and generate thumbnails in multiple sizes.

        :Args:
            ci_image: Core Image CIImage object
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
        results = {}

        # Get original image dimensions
        extent = ci_image.extent()
        original_width = extent.size.width
        original_height = extent.size.height

        # Sort sizes by area (largest first) for optimal processing
        sorted_sizes = sorted(sizes.items(), key=lambda x: x[1][0] * x[1][1], reverse=True)

        for size_name, (target_width, target_height) in sorted_sizes:
            # Nested pool drains after each size (more frequent drainage)
            with autorelease_pool():
                # Calculate scale factor to fit within target size (maintaining aspect ratio)
                scale_x = target_width / original_width
                scale_y = target_height / original_height
                scale = min(scale_x, scale_y)

                # Apply GPU-accelerated scaling using Lanczos algorithm
                scale_filter = CIFilter.filterWithName_("CILanczosScaleTransform")
                scale_filter.setValue_forKey_(ci_image, "inputImage")
                scale_filter.setValue_forKey_(scale, "inputScale")
                scale_filter.setValue_forKey_(1.0, "inputAspectRatio")  # Maintain aspect ratio

                scaled_image = scale_filter.outputImage()

                # Render to bytes
                image_bytes = self._render_to_bytes(scaled_image, output_format, quality)
                results[size_name] = image_bytes

                # Objects automatically released when pool exits

        return results

    def _render_to_bytes(self, ci_image: "CIImage", output_format: str, quality: int) -> bytes:
        """
        Render CIImage to bytes in specified format using direct bitmap rendering.

        Uses render:toBitmap:rowBytes:bounds:format:colorSpace: instead of
        createCGImage:fromRect: to avoid IOSurface GPU memory leaks. The GPU
        renders directly into a CPU-side bytearray — no IOSurface is allocated.

        PIL handles the final encoding to JPEG/PNG/WEBP, which is fast since
        the thumbnail pixels are already small after GPU-accelerated Lanczos scaling.

        Args:
            ci_image: Core Image CIImage object to render
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        Returns:
            Image data as bytes
        """
        with autorelease_pool():
            extent = ci_image.extent()
            width = int(extent.size.width)
            height = int(extent.size.height)

            # Render directly to bitmap buffer — NO IOSurface allocation
            bytes_per_row = width * 4  # RGBA8 = 4 bytes per pixel
            buffer_size = bytes_per_row * height
            bitmap_data = bytearray(buffer_size)

            self.context.render_toBitmap_rowBytes_bounds_format_colorSpace_(
                ci_image,
                bitmap_data,
                bytes_per_row,
                extent,
                kCIFormatRGBA8,
                self._color_space,
            )

            # Convert raw RGBA bitmap to target format using PIL
            pil_img = Image.frombytes("RGBA", (width, height), bytes(bitmap_data))

            buffer = io.BytesIO()
            fmt = output_format.upper()
            if fmt == "JPEG":
                pil_img = pil_img.convert("RGB")
                pil_img.save(buffer, format="JPEG", quality=quality)
            elif fmt == "PNG":
                pil_img.save(buffer, format="PNG")
            elif fmt == "WEBP":
                pil_img.save(buffer, format="WEBP", quality=quality)
            else:
                raise ValueError(f"Unsupported output format: {output_format}")

            result = buffer.getvalue()
            buffer.close()
            pil_img.close()

            return result
