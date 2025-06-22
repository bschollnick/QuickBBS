import io
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

try:
    from .Abstractbase_thumbnails import AbstractBackend
    from .pil_thumbnails import ImageBackend
except ImportError:
    from Abstractbase_thumbnails import AbstractBackend
    from pil_thumbnails import ImageBackend




class PDFBackend(ImageBackend):
    """PyMuPDF backend for PDF thumbnail generation."""

    def process_pdf_file(
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
        """
        page_num = 0  # Page number to use for thumbnail (0-indexed)
        zoom = 2.0  # Zoom level for rendering (higher = better quality)
        print(file_path)
        try:
            pdf_doc = fitz.open(file_path)

            # Get the specified page (default first page)
            if page_num >= len(pdf_doc):
                page_num = 0

            page = pdf_doc[page_num]

            # Create matrix for rendering
            mat = fitz.Matrix(zoom, zoom)

            # Render page to pixmap
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))

            # Process the image
#            results = self._process_pil_image(img, sizes, output_format, quality)
            output = {}
            converter = ImageBackend()
            pillow_output = converter._process_pil_image(img, sizes, output_format, quality)
            output["format"] = output_format
            output.update(pillow_output)

            # Clean up
            pdf_doc.close()

            #return results
            return output

        except Exception as e:
            raise Exception(f"Error processing PDF: {e}")

    def process_pdf_bytes(
        self,
        pdf_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
        page_num: int = 0,
        zoom: float = 2.0,
    ) -> dict[str, bytes]:
        """
        Process PDF bytes and generate thumbnails.

        Args:
            pdf_bytes: PDF file as bytes
            sizes: Dictionary of size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)
            page_num: Page number to use for thumbnail (0-indexed)
            zoom: Zoom level for rendering (higher = better quality)
        """
        try:
            pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")

            # Get the specified page (default first page)
            if page_num >= len(pdf_doc):
                page_num = 0

            page = pdf_doc[page_num]

            # Create matrix for rendering
            mat = fitz.Matrix(zoom, zoom)

            # Render page to pixmap
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))

            # Process the image
            results = self._process_pil_image(img, sizes, output_format, quality)

            # Clean up
            pdf_doc.close()

            return results

        except Exception as e:
            raise Exception(f"Error processing PDF bytes: {e}")

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
        small_thumb_bytes = thumbnails['small']
        medium_thumb_bytes = thumbnails['medium']
        large_thumb_bytes = thumbnails['large']
        print(small_thumb_bytes[:20], medium_thumb_bytes[:20], large_thumb_bytes[:20])
        print(f"size of small thumbnail: {len(thumbnails['small'])} bytes")
        print(f"size of medium thumbnail: {len(thumbnails['medium'])} bytes")
        print(f"size of large thumbnail: {len(thumbnails['large'])} bytes")
        # Save thumbnails
        for size_name, thumbnail_bytes in thumbnails.items():
            with open(f"thumbnail_{size_name}.jpg", "wb") as f:
                f.write(thumbnail_bytes)

        print("PDF thumbnails created successfully!")

    except Exception as e:
        print(f"Error: {e}")
