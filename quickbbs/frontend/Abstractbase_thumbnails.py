from abc import ABC, abstractmethod
from typing import Literal, Optional, Union

from PIL import Image, ImageOps


class ImageBackend(ABC):
    """Abstract base class for image processing backends."""

    @abstractmethod
    def process_from_file(
        self,
        file_path: str,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        pass

    @abstractmethod
    def process_from_memory(
        self,
        image_bytes: bytes,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        pass

    @abstractmethod
    def process_data(
        self,
        pil_image: Image.Image,
        sizes: dict[str, tuple[int, int]],
        output_format: str,
        quality: int,
    ) -> dict[str, bytes]:
        pass
