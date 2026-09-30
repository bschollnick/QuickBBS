"""PDFKit backend for PDF thumbnail generation (macOS native)."""

# pylint: disable=no-name-in-module  # pyobjc uses dynamic imports

from pathlib import Path

from cachetools import cached
from django.conf import settings

# Try to import PDFKit (part of Quartz) and related macOS frameworks
try:
    from Foundation import NSURL, NSData
    from Quartz import CIImage, PDFDocument

    PDFKIT_AVAILABLE = True
except ImportError:
    PDFKIT_AVAILABLE = False

from quickbbs.MonitoredCache import create_cache

from .base import AbstractBackend, ThumbnailResult
from .core_image_thumbnails import CoreImageBackend, autorelease_pool, hide_dock_icon
from .exceptions import PDFProcessingError

_scale_cache = create_cache(settings.PDFKIT_SCALE_CACHE_SIZE, "pdfkit_scale", monitored=settings.CACHE_MONITORING)


class PDFKitBackend(AbstractBackend):
    """PDFKit backend for PDF thumbnail generation.

    Uses macOS native PDFKit framework to render PDF pages, then processes
    them using Core Image for GPU-accelerated thumbnail generation.
    Significantly faster than PyMuPDF and fully GPU-accelerated.

    Example:
        >>> backend = PDFKitBackend()
        >>> thumbs = backend.process_from_file(
        ...     "/albums/docs/manual.pdf",
        ...     sizes={"small": (200, 200)},
        ...     output_format="JPEG",
        ...     quality=85,
        ... )
        >>> sorted(thumbs.images), thumbs.format
        (['small'], 'JPEG')
    """

    def __init__(self):
        """Initialize the PDFKit backend.

        Sets the AppKit activation policy to prohibited (prevents a dock icon
        from appearing) and caches a CoreImageBackend instance for rendering.

        Raises:
            ImportError: If PDFKit is not available (non-macOS).
        """
        if not PDFKIT_AVAILABLE:
            raise ImportError("PDFKit not available. This backend requires macOS with pyobjc-framework-quartz.")

        hide_dock_icon()

        # Cache CoreImageBackend instance for reuse
        self._image_backend = CoreImageBackend()

    @staticmethod
    @cached(_scale_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
    def _calculate_optimal_scale(page_width: float, page_height: float, target_width: int, target_height: int) -> float:
        """Calculate the optimal scale to render a PDF page at a target size.

        Cached to avoid redundant calculations for similar page dimensions.

        Args:
            page_width: PDF page width in points.
            page_height: PDF page height in points.
            target_width: Target width in pixels.
            target_height: Target height in pixels.

        Returns:
            Scale factor that fits the page within the target bounds, with a
            10% buffer for quality.
        """
        # Calculate scale for each dimension (fit within target bounds)
        scale_x = target_width / page_width
        scale_y = target_height / page_height

        # Use smaller scale to fit, add 10% buffer for quality
        return min(scale_x, scale_y) * 1.1

    def _render_pdf_page_to_ciimage(self, pdf_doc: "PDFDocument", page_num: int, target_size: tuple[int, int]) -> "CIImage":
        """Render a PDF page to a CIImage using PDFKit.

        Args:
            pdf_doc: PDFKit PDFDocument object.
            page_num: Page number (0-indexed).
            target_size: Target (width, height) for rendering; the page is
                rendered at the optimal scale for this size.

        Returns:
            CIImage of the rendered page.

        Raises:
            PDFProcessingError: If the page cannot be fetched, rendered, or
                converted to a CIImage.
        """
        # No inner autorelease pool — callers (process_from_file, process_from_memory)
        # have outer pools. An inner pool here would drain tiff_data that the
        # returned CIImage may still reference.

        # Get the page
        page = pdf_doc.pageAtIndex_(page_num)
        if page is None:
            raise PDFProcessingError(f"Could not get page {page_num} from PDF")

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
            raise PDFProcessingError("Failed to render PDF page thumbnail")

        # Convert NSImage to CGImage then to CIImage
        # Get the bitmap representation
        tiff_data = ns_image.TIFFRepresentation()
        if tiff_data is None:
            raise PDFProcessingError("Failed to get TIFF representation from NSImage")

        # Create CIImage from TIFF data
        ci_image = CIImage.imageWithData_(tiff_data)

        if ci_image is None:
            raise PDFProcessingError("Failed to create CIImage from TIFF data")

        return ci_image

    def process_from_file(
        self,
        file_path: str | Path,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """Process a PDF file and generate thumbnails of its first page.

        Args:
            file_path: Path to the PDF file.
            sizes: Dictionary of size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Returns:
            The thumbnails, keyed by size name, in `output_format`.

        Raises:
            FileNotFoundError: If the PDF file does not exist.
            PDFProcessingError: If the document cannot be loaded, has no
                pages, or page rendering fails.
        """
        # Wrap entire operation in autorelease pool to drain PDFKit objects
        with autorelease_pool():
            file_path = Path(file_path)

            if not file_path.exists():
                raise FileNotFoundError(f"PDF file not found: {file_path}")

            # Load PDF document
            file_url = NSURL.fileURLWithPath_(str(file_path))
            pdf_doc = PDFDocument.alloc().initWithURL_(file_url)

            if pdf_doc is None:
                raise PDFProcessingError(f"Could not load PDF from {file_path}", file_path=str(file_path))

            try:
                # Use first page (page 0)
                page_num = 0
                if pdf_doc.pageCount() == 0:
                    raise PDFProcessingError("PDF has no pages", file_path=str(file_path))

                if page_num >= pdf_doc.pageCount():
                    page_num = 0

                # Get largest target size for optimal rendering
                largest_size = max(sizes.values(), key=lambda s: s[0] * s[1])

                # Render page to CIImage
                ci_image = self._render_pdf_page_to_ciimage(pdf_doc, page_num, largest_size)

                # Process using Core Image backend for GPU-accelerated thumbnails
                images = self._image_backend.render_sizes(ci_image, sizes, output_format, quality)
                return ThumbnailResult(images, output_format)

            finally:
                # Clean up
                pdf_doc = None

    def process_from_memory(
        self,
        source_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
        page_num: int = 0,
    ) -> ThumbnailResult:
        """Process PDF bytes and generate thumbnails.

        Args:
            source_bytes: PDF file as bytes.
            sizes: Dictionary of size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).
            page_num: Page number to use for the thumbnail (0-indexed,
                default 0). Falls back to page 0 if out of range.

        Returns:
            The thumbnails, keyed by size name, in `output_format`.

        Raises:
            PDFProcessingError: If the document cannot be loaded, has no
                pages, or page rendering fails.
        """
        # Wrap entire operation in autorelease pool to drain PDFKit objects
        with autorelease_pool():
            # Convert bytes to NSData
            ns_data = NSData.dataWithBytes_length_(source_bytes, len(source_bytes))

            # Load PDF document from data
            pdf_doc = PDFDocument.alloc().initWithData_(ns_data)

            if pdf_doc is None:
                raise PDFProcessingError("Could not load PDF from bytes")

            try:
                if pdf_doc.pageCount() == 0:
                    raise PDFProcessingError("PDF has no pages")

                if page_num >= pdf_doc.pageCount():
                    page_num = 0

                # Get largest target size for optimal rendering
                largest_size = max(sizes.values(), key=lambda s: s[0] * s[1])

                # Render page to CIImage
                ci_image = self._render_pdf_page_to_ciimage(pdf_doc, page_num, largest_size)

                # Process using Core Image backend for GPU-accelerated thumbnails
                images = self._image_backend.render_sizes(ci_image, sizes, output_format, quality)
                return ThumbnailResult(images, output_format)

            finally:
                # Clean up
                pdf_doc = None

    def process_data(self, pil_image, sizes, output_format, quality):
        """Process a PIL Image and generate thumbnails.

        Args:
            pil_image: PIL Image object.
            sizes: Dictionary of size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Raises:
            NotImplementedError: Always — PDF processing from a PIL Image is
                not supported.
        """
        raise NotImplementedError("PDF processing from PIL Image is not implemented.")
