import io
import os
import platform
import sys
from typing import Literal, Optional, Union

from .Abstractbase_thumbnails import AbstractBackend
from PIL import Image, ImageOps


class ImageBackend(AbstractBackend):
    """PIL/Pillow backend for cross-platform image processing."""

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        with Image.open(file_path) as img:
            return self._process_pil_image(img, sizes, output_format, quality)

    def process_from_memory(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        with Image.open(io.BytesIO(image_bytes)) as img:
            return self._process_pil_image(img, sizes, output_format, quality)

    def process_data(
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
