"""
Abstract base class for image processing backends.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True, slots=True)
class ThumbnailResult:
    """The thumbnails generated from one source.

    Attributes:
        images: The encoded thumbnails, keyed by the size names the caller
            passed in `sizes`.
        format: The encoding of every image, e.g. "JPEG".
        duration: The source video's length in seconds; None for a still
            image or a PDF.
    """

    images: dict[str, bytes]
    format: str
    duration: float | None = None


class AbstractBackend(ABC):
    """Abstract base class for image processing backends."""

    __slots__ = ()

    @abstractmethod
    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """Process a media file from disk and generate multiple thumbnails."""

    @abstractmethod
    def process_from_memory(
        self,
        source_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """Process an in-memory blob and generate multiple thumbnails."""

    @abstractmethod
    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> ThumbnailResult:
        """Process an image (PILLOW) and generate multiple thumbnails."""
