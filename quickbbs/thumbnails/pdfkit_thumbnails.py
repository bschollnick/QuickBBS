"""PDFKit backend for PDF thumbnail generation (macOS native)."""

# pylint: disable=no-name-in-module  # pyobjc uses dynamic imports

from functools import lru_cache
from pathlib import Path

# Try to import PDFKit (part of Quartz) and related macOS frameworks
try:
    from Foundation import NSData, NSURL
    from Quartz import CIImage, PDFDocument

    PDFKIT_AVAILABLE = True
except ImportError:
    PDFKIT_AVAILABLE = False

try:
    from .Abstractbase_thumbnails import AbstractBackend
    from .core_image_thumbnails import CoreImageBackend
except ImportError:
    from Abstractbase_thumbnails import AbstractBackend
    from core_image_thumbnails import CoreImageBackend


class PDFKitBackend(AbstractBackend):
    """PDFKit backend for PDF thumbnail generation.

    Uses macOS native PDFKit framework to render PDF pages, then processes
    them using Core Image for GPU-accelerated thumbnail generation.
    Significantly faster than PyMuPDF and fully GPU-accelerated.
    """

    def __init__(self):
        """Initialize PDFKit backend.

        :raises ImportError: If PDFKit is not available (non-macOS)
        """
        if not PDFKIT_AVAILABLE:
            raise ImportError("PDFKit not available. This backend requires macOS with pyobjc-framework-quartz.")

        # Cache CoreImageBackend instance for reuse
        self._image_backend = CoreImageBackend()

    @staticmethod
    @lru_cache(maxsize=500)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
    def _calculate_optimal_scale(page_width: float, page_height: float, target_width: int, target_height: int) -> float:
        """Calculate optimal scale level to render PDF at target size.

        Cached to avoid redundant calculations for similar page dimensions.

        :Args:
            page_width: PDF page width in points
            page_height: PDF page height in points
            target_width: Target width in pixels
            target_height: Target height in pixels

        :return: Optimal scale factor with 10% quality buffer
        """
        # Calculate scale for each dimension (fit within target bounds)
        scale_x = target_width / page_width
        scale_y = target_height / page_height

        # Use smaller scale to fit, add 10% buffer for quality
        return min(scale_x, scale_y) * 1.1

    def _render_pdf_page_to_ciimage(self, pdf_doc: "PDFDocument", page_num: int, target_size: tuple[int, int]) -> "CIImage":
        """Render a PDF page to CIImage using PDFKit.

        :Args:
            pdf_doc: PDFKit PDFDocument object
            page_num: Page number (0-indexed)
            target_size: Target size (width, height) for rendering

        :return: CIImage of the rendered page
        :raises RuntimeError: If page rendering fails
        """
        # Get the page
        page = pdf_doc.pageAtIndex_(page_num)
        if page is None:
            raise RuntimeError(f"Could not get page {page_num} from PDF")

        # Get page bounds
        page_rect = page.boundsForBox_(1)  # 1 = kPDFDisplayBoxMediaBox
        page_width = page_rect.size.width
        page_height = page_rect.size.height

        # Calculate optimal scale
        scale = self._calculate_optimal_scale(page_width, page_height, target_size[0], target_size[1])

        # Calculate scaled dimensions
        scaled_width = int(page_width * scale)
        scaled_height = int(page_height * scale)

        # Render page to CIImage using PDFKit's thumbnail method
        # This is GPU-accelerated and very fast
        ns_image = page.thumbnailOfSize_forBox_((scaled_width, scaled_height), 1)

        if ns_image is None:
            raise RuntimeError("Failed to render PDF page thumbnail")

        # Convert NSImage to CGImage then to CIImage
        # Get the bitmap representation
        tiff_data = ns_image.TIFFRepresentation()
        if tiff_data is None:
            raise RuntimeError("Failed to get TIFF representation from NSImage")

        # Create CIImage from TIFF data
        ci_image = CIImage.imageWithData_(tiff_data)

        if ci_image is None:
            raise RuntimeError("Failed to create CIImage from TIFF data")

        return ci_image

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """Process a PDF file and generate thumbnails.

        :Args:
            file_path: Path to PDF file
            sizes: Dictionary of size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :return: Dictionary with 'format' key and size-keyed thumbnail bytes
        :raises FileNotFoundError: If PDF file doesn't exist
        :raises RuntimeError: If PDF processing fails
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        # Load PDF document
        file_url = NSURL.fileURLWithPath_(str(file_path))
        pdf_doc = PDFDocument.alloc().initWithURL_(file_url)

        if pdf_doc is None:
            raise RuntimeError(f"Could not load PDF from {file_path}")

        try:
            # Use first page (page 0)
            page_num = 0
            if pdf_doc.pageCount() == 0:
                raise RuntimeError("PDF has no pages")

            if page_num >= pdf_doc.pageCount():
                page_num = 0

            # Get largest target size for optimal rendering
            largest_size = max(sizes.values(), key=lambda s: s[0] * s[1])

            # Render page to CIImage
            ci_image = self._render_pdf_page_to_ciimage(pdf_doc, page_num, largest_size)

            # Process using Core Image backend for GPU-accelerated thumbnails
            # pylint: disable=protected-access
            image_output = self._image_backend._process_ci_image(ci_image, sizes, output_format, quality)

            output = {"format": output_format}
            output.update(image_output)

            return output

        finally:
            # Clean up
            pdf_doc = None

    def process_from_memory(
        self,
        pdf_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
        page_num: int = 0,
    ) -> dict[str, bytes]:
        """Process PDF bytes and generate thumbnails.

        :Args:
            pdf_bytes: PDF file as bytes
            sizes: Dictionary of size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)
            page_num: Page number to use for thumbnail (0-indexed, default: 0)

        :return: Dictionary with 'format' key and size-keyed thumbnail bytes
        :raises RuntimeError: If PDF processing fails
        """
        # Convert bytes to NSData
        ns_data = NSData.dataWithBytes_length_(pdf_bytes, len(pdf_bytes))

        # Load PDF document from data
        pdf_doc = PDFDocument.alloc().initWithData_(ns_data)

        if pdf_doc is None:
            raise RuntimeError("Could not load PDF from bytes")

        try:
            if pdf_doc.pageCount() == 0:
                raise RuntimeError("PDF has no pages")

            if page_num >= pdf_doc.pageCount():
                page_num = 0

            # Get largest target size for optimal rendering
            largest_size = max(sizes.values(), key=lambda s: s[0] * s[1])

            # Render page to CIImage
            ci_image = self._render_pdf_page_to_ciimage(pdf_doc, page_num, largest_size)

            # Process using Core Image backend for GPU-accelerated thumbnails
            # pylint: disable=protected-access
            image_output = self._image_backend._process_ci_image(ci_image, sizes, output_format, quality)

            output = {"format": output_format}
            output.update(image_output)

            return output

        finally:
            # Clean up
            pdf_doc = None

    def process_data(self, pil_image, sizes, output_format, quality):
        """Process a PIL Image and generate thumbnails.

        :Args:
            pil_image: PIL Image object
            sizes: Dictionary of size names to (width, height) tuples
            output_format: Output format (JPEG, PNG, WEBP)
            quality: Image quality (1-100)

        :raises NotImplementedError: PDF processing from PIL Image is not supported
        """
        raise NotImplementedError("PDF processing from PIL Image is not implemented.")


# Example usage
if __name__ == "__main__":
    import sys

    def output_disk(filename, data):
        """Helper function to write bytes to a file."""
        with open(filename, "wb") as f:
            f.write(data)
        print(f"Saved {filename} with {len(data):,} bytes.")

    if len(sys.argv) < 2:
        print("Usage: python pdfkit_thumbnails.py <pdf_file>")
        sys.exit(1)

    pdf_file = sys.argv[1]

    if not Path(pdf_file).exists():
        print(f"Error: PDF file not found: {pdf_file}")
        sys.exit(1)

    try:
        backend = PDFKitBackend()

        # Define thumbnail sizes
        sizes = {"small": (200, 200), "medium": (740, 740), "large": (1024, 1024)}

        # Generate thumbnails from PDF file
        print("=" * 60)
        print("Generating PDF Thumbnails with PDFKit")
        print("=" * 60)

        thumbnails = backend.process_from_file(file_path=pdf_file, sizes=sizes, output_format="JPEG", quality=85)

        print(f"Format: {thumbnails['format']}")
        print(f"Small thumbnail: {len(thumbnails['small']):,} bytes")
        print(f"Medium thumbnail: {len(thumbnails['medium']):,} bytes")
        print(f"Large thumbnail: {len(thumbnails['large']):,} bytes")

        output_disk("pdf_small_thumb.jpg", thumbnails["small"])
        output_disk("pdf_medium_thumb.jpg", thumbnails["medium"])
        output_disk("pdf_large_thumb.jpg", thumbnails["large"])

        print("\nPDF thumbnails created successfully!")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
