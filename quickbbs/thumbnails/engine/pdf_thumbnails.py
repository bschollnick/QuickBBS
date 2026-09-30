"""PyMuPDF backend for cross-platform PDF thumbnail generation."""

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pymupdf
from cachetools import cached
from django.conf import settings
from PIL import Image, ImageOps

from quickbbs.MonitoredCache import create_cache

from .base import AbstractBackend, ThumbnailResult
from .exceptions import PDFProcessingError
from .pil_thumbnails import ImageBackend

_zoom_cache = create_cache(settings.PDF_ZOOM_CACHE_SIZE, "pdf_zoom", monitored=settings.CACHE_MONITORING)


@contextmanager
def _open_page(open_document: Callable[[], pymupdf.Document], *, page_num: int, source: str) -> Iterator[pymupdf.Page]:
    """Yield page `page_num` (page 0 if out of range) of the document `open_document` returns, closing it after.

    Any PyMuPDF error (all subclass RuntimeError), or PIL's OSError or ValueError, raised
    while opening or inside the `with` block is re-raised as PDFProcessingError.
    """
    try:
        with open_document() as pdf_doc:
            yield pdf_doc[page_num if page_num < len(pdf_doc) else 0]
    except (RuntimeError, OSError, ValueError) as e:
        raise PDFProcessingError(f"Error processing PDF: {e}", file_path=source) from e


class PDFBackend(AbstractBackend):
    """PyMuPDF backend for PDF thumbnail generation.

    Uses PyMuPDF to render PDF pages as images, then processes
    them using the PIL backend for thumbnail generation.
    Includes optimization for zoom calculation caching and backend reuse.

    Example:
        >>> backend = PDFBackend()
        >>> thumbs = backend.process_from_file(
        ...     "/albums/docs/manual.pdf",
        ...     sizes={"small": (200, 200)},
        ...     output_format="JPEG",
        ...     quality=85,
        ... )
        >>> sorted(thumbs.images), thumbs.format
        (['small'], 'JPEG')
    """

    __slots__ = ("_image_backend",)

    def __init__(self):
        """Initialize the backend with a cached ImageBackend for PIL processing."""
        self._image_backend = ImageBackend()

    @staticmethod
    @cached(_zoom_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
    def _calculate_optimal_zoom(page_width: float, page_height: float, target_width: int, target_height: int) -> float:
        """
        Calculate the optimal zoom to render a PDF page slightly larger than target size.

        Cached to avoid redundant calculations for similar page dimensions.

        Args:
            page_width: PDF page width in points.
            page_height: PDF page height in points.
            target_width: Target width in pixels.
            target_height: Target height in pixels.

        Returns:
            Zoom factor that fits the page within the target bounds, with a
            10% buffer for quality.
        """
        # Calculate zoom for each dimension (fit within target bounds)
        zoom_x = target_width / page_width
        zoom_y = target_height / page_height

        # Use smaller zoom to fit, add 10% buffer for quality
        return min(zoom_x, zoom_y) * 1.1

    def _render_pdf_page(
        self,
        page,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """
        Render a PDF page to thumbnails in every requested size.

        Renders once at the optimal zoom for the largest size, then resizes
        via the PIL backend.

        ASYNC-SAFE: Pure computation with no DB/IO operations.

        Args:
            page: PyMuPDF page object.
            sizes: Dictionary of size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Returns:
            The thumbnails, keyed by size name, in `output_format`.
        """
        # Calculate optimal zoom for largest requested size using cached method
        largest_size = max(sizes.values(), key=lambda s: s[0] * s[1])
        rect = page.rect
        zoom = self._calculate_optimal_zoom(rect.width, rect.height, largest_size[0], largest_size[1])

        # Create matrix for rendering
        mat = pymupdf.Matrix(zoom, zoom)

        # Render page to pixmap
        pix = page.get_pixmap(matrix=mat)

        # Convert directly to PIL Image from raw pixel data (no PNG encoding)
        mode = "RGBA" if pix.alpha else "RGB"
        img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)

        # Auto-orient based on EXIF (PDFs typically don't have EXIF, but handle it if present)
        img = ImageOps.exif_transpose(img)

        # Process the image using cached backend
        output = ThumbnailResult(self._image_backend.render_sizes(img, sizes, output_format, quality), output_format)

        return output

    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """
        Process a PDF file and generate thumbnails of its first page.

        Args:
            file_path: Path to the PDF file.
            sizes: Dictionary of size names to (width, height) tuples.
            output_format: Output format (JPEG, PNG, WEBP).
            quality: Image quality (1-100).

        Returns:
            The thumbnails, keyed by size name, in `output_format`.

        Raises:
            FileNotFoundError: If the PDF file does not exist.
            PDFProcessingError: If the PDF cannot be opened or rendered.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        with _open_page(lambda: pymupdf.open(file_path), page_num=0, source=file_path) as page:
            return self._render_pdf_page(page, sizes, output_format, quality)

    def process_from_memory(
        self,
        source_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
        page_num: int = 0,
    ) -> ThumbnailResult:
        """
        Process PDF bytes and generate thumbnails.

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
            PDFProcessingError: If the PDF cannot be opened or rendered.
        """
        with _open_page(lambda: pymupdf.open(stream=source_bytes, filetype="pdf"), page_num=page_num, source="PDF bytes") as page:
            return self._render_pdf_page(page, sizes, output_format, quality)

    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """
        Process a PIL Image and generate thumbnails.

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
