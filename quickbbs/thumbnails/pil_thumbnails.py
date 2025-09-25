import io

from PIL import Image, ImageOps

try:
    from .Abstractbase_thumbnails import AbstractBackend
except ImportError:
    from Abstractbase_thumbnails import AbstractBackend


class ImageBackend(AbstractBackend):
    """PIL/Pillow backend for cross-platform image processing.

    Provides image thumbnail generation using the PIL/Pillow library,
    supporting multiple output formats and sizes.
    """

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process image file and generate thumbnails.

        :Args:
            file_path: Path to the image file
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
        with Image.open(file_path) as img:
            return self._process_pil_image(img, sizes, output_format, quality)

    def process_from_memory(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process image from memory and generate thumbnails.

        :Args:
            image_bytes: Image data as bytes
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
        with Image.open(io.BytesIO(image_bytes)) as img:
            return self._process_pil_image(img, sizes, output_format, quality)

    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process PIL Image object and generate thumbnails.

        :Args:
            pil_image: PIL Image object to process
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
        img_copy = pil_image.copy()
        return self._process_pil_image(img_copy, sizes, output_format, quality)

    def _process_pil_image(
        self,
        img: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Internal method to process PIL image and generate thumbnails.

        Handles color space conversion, EXIF orientation, and creates
        thumbnails in multiple sizes with appropriate compression.

        :Args:
            img: PIL Image object to process
            sizes: Dictionary mapping size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary mapping size names to thumbnail bytes
        """
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

            if output_format.upper() in ["JPEG", "JPG"]:
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
