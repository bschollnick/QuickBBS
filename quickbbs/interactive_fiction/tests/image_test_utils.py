"""Shared image/gallery-file helpers for interactive_fiction's image-linking
tests (test_images.py, test_views.py) — not a test module itself (no Test*
classes).

Since StoryImage.file_index points at a real gallery FileIndex row (see
claude_docs/plans/interactive_fiction_fileindex_mapping.md), these tests
need a real file on disk plus a real DirectoryIndex/FileIndex row backing
it — not just in-memory bytes, since FileIndex.inline_sendfile() opens the
file at its real filesystem path.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

from filetypes.models import filetypes
from quickbbs.models import DirectoryIndex, FileIndex


def make_image_bytes(fmt: str = "JPEG", color: tuple[int, int, int] = (255, 0, 0), size: tuple[int, int] = (4, 4)) -> bytes:
    """Encode a tiny in-memory image for gallery-file test fixtures.

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


def make_gallery_image(directory: Path, name: str, *, fmt: str = "JPEG", color: tuple[int, int, int] = (255, 0, 0)) -> FileIndex:
    """Write a real image file under `directory` and register it as a FileIndex row.

    Mirrors quickbbs/tests/test_fileindex.py's `_make_dir`/`_make_fileindex`
    pattern — a real file on disk (since FileIndex.inline_sendfile() opens
    it directly), registered via DirectoryIndex.add_directory() and a
    matching FileIndex row, content-hashed the same way the real scanner
    would.

    Args:
        directory: The directory to write the file into (created if needed).
        name: The file's name, e.g. "cover.jpg".
        fmt: The Pillow format to encode as.
        color: The solid fill color.

    Returns:
        The created FileIndex row.
    """
    directory.mkdir(parents=True, exist_ok=True)
    raw = make_image_bytes(fmt, color=color)
    file_path = directory / name
    file_path.write_bytes(raw)

    _, dir_index = DirectoryIndex.add_directory(str(directory) + "/")
    assert dir_index is not None

    file_sha = hashlib.sha256(raw).hexdigest()
    fileext = f".{fmt.lower()}"
    ftype = filetypes.objects.get(fileext=fileext)
    return FileIndex.objects.create(
        home_directory=dir_index,
        name=name,
        file_sha256=file_sha,
        unique_sha256=hashlib.sha256((file_sha + str(file_path)).encode()).hexdigest(),
        lastscan=0.0,
        lastmod=0.0,
        size=len(raw),
        filetype=ftype,
        delete_pending=False,
        is_generic_icon=False,
    )
