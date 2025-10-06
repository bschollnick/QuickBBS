"""
Abstract base class for image processing backends.
"""

from abc import ABC, abstractmethod

from PIL import Image


class AbstractBackend(ABC):
    """Abstract base class for image processing backends."""

    @abstractmethod
    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """Process an file and generate multiple thumbnails."""

    @abstractmethod
    def process_from_memory(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """Process an in-memory blob and generate multiple thumbnails."""

    @abstractmethod
    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        """Process an image (PILLOW) and generate multiple thumbnails."""
