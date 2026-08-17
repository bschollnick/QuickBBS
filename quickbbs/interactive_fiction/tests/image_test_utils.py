"""Shared image-building helpers for interactive_fiction's Step 5 tests
(test_images.py, test_views.py) — not a test module itself (no Test* classes).
"""

from __future__ import annotations

import zipfile
from io import BytesIO

from PIL import Image


def make_image_bytes(fmt: str = "JPEG", color: tuple[int, int, int] = (255, 0, 0), size: tuple[int, int] = (4, 4)) -> bytes:
    """Encode a tiny in-memory image for upload-path tests.

    Args:
        fmt: The Pillow format to encode as (e.g. "JPEG", "PNG").
        color: The solid fill color.
        size: The pixel dimensions.

    Returns:
        The encoded image bytes.
    """
    buf = BytesIO()
    Image.new("RGB", size, color=color).save(buf, format=fmt)
    return buf.getvalue()


def make_image_zip(members: dict[str, bytes]) -> bytes:
    """Build an in-memory zip archive for images_zip upload tests.

    Args:
        members: Mapping of archive member name to its raw content.

    Returns:
        The encoded zip archive bytes.
    """
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buf.getvalue()
