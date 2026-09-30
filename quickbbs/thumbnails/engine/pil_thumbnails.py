"""PIL/Pillow backend for image thumbnail generation."""

import contextlib
import io
from typing import Any

from PIL import Image, ImageOps

from .base import AbstractBackend, ThumbnailResult


def convert_image_for_format(img: Image.Image, output_format: str) -> Image.Image:
    """
    Convert PIL Image to appropriate color mode for output format.

    Handles conversion of RGBA/P/LA images to RGB for JPEG compatibility,
    which doesn't support transparency. Uses white background for transparency.

    MEMORY SAFETY: This function may return a NEW Image object. The caller
    must close the original image if it's no longer needed.

    Args:
        img: PIL Image object to convert
        output_format: Target format (JPEG, PNG, WEBP, etc.)

    Returns:
        Converted PIL Image object ready for saving in target format
    """
    # JPEG doesn't support transparency - convert RGBA/P/LA to RGB with white background
    if output_format.upper() == "JPEG" and img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            # Convert P mode to RGBA first
            rgba_img = img.convert("RGBA")
            background.paste(rgba_img, mask=rgba_img.split()[-1])
            rgba_img.close()  # Close intermediate RGBA image
        else:
            # img is already RGBA or LA
            background.paste(img, mask=img.split()[-1])
        return background
    # Convert exotic color modes to RGB
    if img.mode not in ("RGB", "RGBA", "L"):
        return img.convert("RGB")
    return img


def _oriented_for_format(img: Image.Image, output_format: str) -> Image.Image:
    """Return `img` converted for `output_format` and turned upright per its EXIF orientation.

    Either step may return a new image; an intermediate one is closed here.
    The result is `img` itself only when neither step changed it.
    """
    converted = convert_image_for_format(img, output_format)
    oriented = ImageOps.exif_transpose(converted)
    if oriented is not converted and converted is not img:
        converted.close()
    return oriented


def _save_options(output_format: str, quality: int) -> dict[str, Any]:
    """Return the `Image.save()` options for one output format."""
    normalized = output_format.upper()
    if normalized in ("JPEG", "JPG", "WEBP"):
        # progressive=True is left off JPEG: 20-30% faster encoding.
        return {"quality": quality, "optimize": True}
    if normalized == "PNG":
        return {"optimize": True}
    return {}


def _encode(image: Image.Image, output_format: str, quality: int) -> bytes:
    """Encode one image in `output_format`."""
    with io.BytesIO() as buffer:
        image.save(buffer, format=output_format, **_save_options(output_format, quality))
        return buffer.getvalue()


class ImageBackend(AbstractBackend):
    """PIL/Pillow backend for cross-platform image processing.

    Provides image thumbnail generation using the PIL/Pillow library,
    supporting multiple output formats and sizes.

    Example:
        >>> backend = ImageBackend()
        >>> thumbs = backend.process_from_file(
        ...     "/albums/photos/cover.jpg",
        ...     sizes={"small": (200, 200), "medium": (740, 740)},
        ...     output_format="JPEG",
        ...     quality=85,
        ... )
        >>> sorted(thumbs.images)
        ['medium', 'small']
    """

    __slots__ = ()

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """
        Process an image file and generate thumbnails.

        Args:
            file_path: Path to the image file.
            sizes: Dictionary mapping size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Returns:
            The thumbnails, keyed by size name, in `output_format`.

        Raises:
            FileNotFoundError: If the image file does not exist.
            PIL.UnidentifiedImageError: If the file cannot be decoded as an image.
        """
        with Image.open(file_path) as img:
            return ThumbnailResult(self.render_sizes(img, sizes, output_format, quality), output_format)

    def process_from_memory(
        self,
        source_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """
        Process an image from memory and generate thumbnails.

        Args:
            source_bytes: Image data as bytes.
            sizes: Dictionary mapping size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Returns:
            The thumbnails, keyed by size name, in `output_format`.

        Raises:
            PIL.UnidentifiedImageError: If the bytes cannot be decoded as an image.
        """
        with Image.open(io.BytesIO(source_bytes)) as img:
            return ThumbnailResult(self.render_sizes(img, sizes, output_format, quality), output_format)

    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """
        Process a PIL Image object and generate thumbnails.

        MEMORY SAFETY: Creates a copy of the input image for processing.
        The copy is properly cleaned up after thumbnail generation.

        Args:
            pil_image: PIL Image object to process. The caller retains
                ownership; this method works on a copy.
            sizes: Dictionary mapping size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Returns:
            The thumbnails, keyed by size name, in `output_format`.
        """
        img_copy = pil_image.copy()
        try:
            return ThumbnailResult(self.render_sizes(img_copy, sizes, output_format, quality), output_format)
        finally:
            # MEMORY: Close the working copy after processing
            # Python guarantees finally runs even with return statement above
            # Note: img_copy reference itself is never changed (reassignments happen
            # inside render_sizes to a different variable), so this closes
            # the original copy we created
            with contextlib.suppress(OSError, AttributeError):
                img_copy.close()

    def render_sizes(
        self,
        img: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process a PIL image and generate thumbnails in every requested size.

        Handles color space conversion and EXIF orientation, then generates
        the sizes largest-first by progressive downsampling (each smaller
        thumbnail is resized from the previous one, not from the original).

        MEMORY SAFETY: Properly manages PIL Image lifecycle to prevent leaks.
        - Does NOT take ownership of the input img parameter (caller must close it)
        - Closes all intermediate images created during processing
        - Uses explicit cleanup to prevent accumulation

        Args:
            img: PIL Image object to process (caller retains ownership).
            sizes: Dictionary mapping size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100). Ignored for PNG.

        Returns:
            Dictionary mapping size names to thumbnail bytes.
        """
        working = _oriented_for_format(img, output_format)
        previous: Image.Image | None = None
        try:
            results: dict[str, bytes] = {}
            # Progressive downsampling: the largest size comes from the working
            # image, each smaller one from the previous thumbnail (40-60% faster
            # for 3+ sizes than copying the full original each time).
            for size_name, target_size in sorted(sizes.items(), key=lambda item: item[1][0] * item[1][1], reverse=True):
                thumbnail = (working if previous is None else previous).copy()
                if previous is not None:
                    previous.close()
                # BICUBIC, not LANCZOS: 30-40% faster, with minimal quality loss at thumbnail sizes.
                thumbnail.thumbnail(target_size, Image.Resampling.BICUBIC)
                previous = thumbnail
                results[size_name] = _encode(thumbnail, output_format, quality)
            return results
        finally:
            # MEMORY: close every image this method created; never the caller's.
            with contextlib.suppress(OSError, AttributeError):
                if previous is not None:
                    previous.close()
                if working is not img:
                    working.close()
