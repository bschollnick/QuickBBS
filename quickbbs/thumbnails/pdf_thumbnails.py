import io
from functools import lru_cache

import fitz  # PyMuPDF
from PIL import Image

try:
    from .Abstractbase_thumbnails import AbstractBackend
    from .pil_thumbnails import ImageBackend
except ImportError:
    from Abstractbase_thumbnails import AbstractBackend
    from pil_thumbnails import ImageBackend


class PDFBackend(AbstractBackend):
    """PyMuPDF backend for PDF thumbnail generation.

    Uses PyMuPDF (fitz) to render PDF pages as images, then processes
    them using the PIL backend for thumbnail generation.
    Includes optimization for zoom calculation caching and backend reuse.
    """

    def __init__(self):
        # Cache ImageBackend instance for reuse
        self._image_backend = ImageBackend()

    @staticmethod
    @lru_cache(maxsize=500)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
    def _calculate_optimal_zoom(
        page_width: float, page_height: float, target_width: int, target_height: int
    ) -> float:
        """
        Calculate optimal zoom level to render PDF slightly larger than target size.
        Cached to avoid redundant calculations for similar page dimensions.

        Args:
            page_width: PDF page width
            page_height: PDF page height
            target_width: Target width
            target_height: Target height

        Returns:
            Optimal zoom factor with 10% quality buffer
        """
        # Calculate zoom for each dimension (fit within target bounds)
        zoom_x = target_width / page_width
        zoom_y = target_height / page_height

        # Use smaller zoom to fit, add 10% buffer for quality
        return min(zoom_x, zoom_y) * 1.1

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process a PDF file and generate thumbnails.

        Args:
            file_path: Path to PDF file
            sizes: Dictionary of size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        Returns:
            Dictionary with 'format' key and size-keyed thumbnail bytes
        """
        page_num = 0
        try:
            pdf_doc = fitz.open(file_path)

            if page_num >= len(pdf_doc):
                page_num = 0

            page = pdf_doc[page_num]

            # Calculate optimal zoom for largest requested size using cached method
            largest_size = max(sizes.values(), key=lambda s: s[0] * s[1])
            rect = page.rect
            zoom = self._calculate_optimal_zoom(
                rect.width, rect.height, largest_size[0], largest_size[1]
            )

            # Create matrix for rendering
            mat = fitz.Matrix(zoom, zoom)

            # Render page to pixmap
            pix = page.get_pixmap(matrix=mat)

            # Convert directly to PIL Image from raw pixel data (no PNG encoding)
            mode = "RGBA" if pix.alpha else "RGB"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)

            # Process the image using cached backend
            output = {}
            pillow_output = self._image_backend._process_pil_image(
                img, sizes, output_format, quality
            )
            output["format"] = output_format
            output.update(pillow_output)

            # Clean up
            pdf_doc.close()

            return output

        except Exception as e:
            raise Exception(f"Error processing PDF: {e}")

    def process_from_memory(
        self,
        pdf_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
        page_num: int = 0,
    ) -> dict[str, bytes]:
        """
        Process PDF bytes and generate thumbnails.

        Args:
            pdf_bytes: PDF file as bytes
            sizes: Dictionary of size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)
            page_num: Page number to use for thumbnail (0-indexed, default: 0)

        Returns:
            Dictionary with 'format' key and size-keyed thumbnail bytes
        """
        try:
            pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")

            if page_num >= len(pdf_doc):
                page_num = 0

            page = pdf_doc[page_num]

            # Calculate optimal zoom for largest requested size using cached method
            largest_size = max(sizes.values(), key=lambda s: s[0] * s[1])
            rect = page.rect
            zoom = self._calculate_optimal_zoom(
                rect.width, rect.height, largest_size[0], largest_size[1]
            )

            # Create matrix for rendering
            mat = fitz.Matrix(zoom, zoom)

            # Render page to pixmap
            pix = page.get_pixmap(matrix=mat)

            # Convert directly to PIL Image from raw pixel data
            mode = "RGBA" if pix.alpha else "RGB"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)

            # Process the image using cached backend
            output = {}
            pillow_output = self._image_backend._process_pil_image(
                img, sizes, output_format, quality
            )
            output["format"] = output_format
            output.update(pillow_output)

            # Clean up
            pdf_doc.close()

            return output

        except Exception as e:
            raise Exception(f"Error processing PDF bytes: {e}")

    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """
        Process a PIL Image and generate thumbnails.

        Args:
            pil_image: PIL Image object
            sizes: Dictionary of size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        Raises:
            NotImplementedError: PDF processing from PIL Image is not supported
        """
        raise NotImplementedError("PDF processing from PIL Image is not implemented.")

    # def _process_pil_image(
    #     self,
    #     img: Image.Image,
    #     sizes: dict[str, tuple[int, int]],
    #     output_format: str,
    #     quality: int,
    # ) -> dict[str, bytes]:
    #     """Process PIL image and generate multiple thumbnail sizes."""
    #     results = {}

    #     # Convert to RGB if necessary for JPEG output
    #     if output_format.upper() == "JPEG" and img.mode in ("RGBA", "P", "LA"):
    #         background = Image.new("RGB", img.size, (255, 255, 255))
    #         if img.mode == "P":
    #             img = img.convert("RGBA")
    #         background.paste(
    #             img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None
    #         )
    #         img = background
    #     elif img.mode not in ("RGB", "RGBA", "L"):
    #         img = img.convert("RGB")

    #     # Auto-orient based on EXIF (though PDFs typically don't have EXIF)
    #     img = ImageOps.exif_transpose(img)

    #     # Sort sizes by area (largest first) for better quality
    #     sorted_sizes = sorted(
    #         sizes.items(), key=lambda x: x[1][0] * x[1][1], reverse=True
    #     )

    #     for size_name, target_size in sorted_sizes:
    #         working_img = img.copy()
    #         working_img.thumbnail(target_size, Image.Resampling.LANCZOS)

    #         buffer = io.BytesIO()
    #         save_kwargs = {"format": output_format}

    #         if output_format.upper() in ["JPEG", "JPG"]:
    #             save_kwargs.update(
    #                 {"quality": quality, "optimize": True, "progressive": True}
    #             )
    #         elif output_format.upper() == "PNG":
    #             save_kwargs.update({"optimize": True})
    #         elif output_format.upper() == "WEBP":
    #             save_kwargs.update({"quality": quality, "optimize": True})

    #         working_img.save(buffer, **save_kwargs)
    #         results[size_name] = buffer.getvalue()

    #     return results


# Example usage
if __name__ == "__main__":

    def output_disk(filename, data):
        """Helper function to write bytes to a file."""
        with open(filename, "wb") as f:
            f.write(data)
        print(f"Saved {filename} with {len(data)} bytes.")

    backend = PDFBackend()

    # Define thumbnail sizes
    sizes = {"small": (150, 150), "medium": (300, 300), "large": (600, 600)}

    # Generate thumbnails from PDF file
    try:
        thumbnails = backend.process_pdf_file(
            file_path="test.pdf",
            sizes=sizes,
            output_format="JPEG",
            quality=85,
        )
        print(f"Format: {thumbnails['format']}")
        small_thumb_bytes = thumbnails["small"]
        medium_thumb_bytes = thumbnails["medium"]
        large_thumb_bytes = thumbnails["large"]
        print(small_thumb_bytes[:20], medium_thumb_bytes[:20], large_thumb_bytes[:20])
        print(f"size of small thumbnail: {len(thumbnails['small'])} bytes")
        print(f"size of medium thumbnail: {len(thumbnails['medium'])} bytes")
        print(f"size of large thumbnail: {len(thumbnails['large'])} bytes")

        output_disk("pdf_small_thumb.jpg", small_thumb_bytes)
        output_disk("pdf_medium_thumb.jpg", medium_thumb_bytes)
        output_disk("pdf_large_thumb.jpg", large_thumb_bytes)

        print("PDF thumbnails created successfully!")

    except Exception as e:
        print(f"Error: {e}")
