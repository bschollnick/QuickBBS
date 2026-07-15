"""
Utilities for QuickBBS, the python edition.
"""

import os
import os.path
from io import BytesIO
from pathlib import Path

import av  # Video Previews
import fitz  # PDF previews
from django.conf import settings
from PIL import Image

import filetypes


def pdf_to_pil(fspath: str) -> Image.Image | None:
    """
    Render the first page of a PDF file as a PIL Image.

    Args:
        fspath: Filesystem path to the PDF file.

    Returns:
        PIL Image of the first page (with alpha channel), or None if PIL
        raises a UserWarning while decoding the rendered pixmap.
    """
    with fitz.open(fspath) as pdf_file:
        pdf_page = pdf_file.load_page(0)
        pix = pdf_page.get_pixmap(alpha=True)
        try:
            source_image = Image.open(BytesIO(pix.tobytes()))
        except UserWarning:
            print("UserWarning!")
            source_image = None
    return source_image


def movie_duration(fspath: str) -> int | None:
    """
    Return the duration of a video file in whole seconds.

    Args:
        fspath: Path to the video file.

    Returns:
        Duration in seconds as an int, or None if the first video stream
        has no readable duration.
    """
    # try:
    with av.open(fspath) as container:
        stream = container.streams.video[0]
        # print(stream)
        try:
            duration_sec = int(stream.duration * stream.time_base)
        except (av.error.InvalidDataError, StopIteration, TypeError):
            duration_sec = None
    # except (av.error.InvalidDataError, StopIteration, TypeError):
    #    duration_sec = None
    return duration_sec


def movie_to_pil(fspath: str) -> Image.Image:
    """
    Extract a frame from the midpoint of a video file as a PIL Image.

    Seeks to half the container duration and decodes the next frame from
    the first video stream.

    Args:
        fspath: Path to the video file.

    Returns:
        PIL Image of the decoded frame. If the file cannot be decoded,
        returns the "broken video" placeholder image from RESOURCES_PATH
        instead.
    """
    image = None
    try:
        with av.open(fspath) as container:
            stream = container.streams.video[0]
            # duration_sec = stream.frames / 30
            container.seek(container.duration // 2)
            frame = container.decode(stream)
            image = next(frame).to_image()
    except (av.error.InvalidDataError, StopIteration):
        image = Image.open(
            #            return_image_obj(
            os.path.join(settings.RESOURCES_PATH, "images", "3559224-200_broken_video.png")
        )
    return image


# def load_movie_alt(fspath):
#     """
#     The load_movie_av function loads a movie from the filesystem and returns an image of the first frame.
#
#     :param fspath: Specify the path of the file
#     :return: An Pillow image object
#     """
#     with av.open(fspath) as container:
#         stream = container.streams.video[0]
#         frame = next(container.decode(stream))
#         return frame.to_image()


def image_to_pil(fspath: str | bytes, mem: bool = False) -> Image.Image | None:
    """
    Load an image from a file path or from bytes in memory.

    Args:
        fspath: Path to the image file, or the raw image bytes when
            mem is True.
        mem: If True, treat fspath as raw image bytes instead of a path.

    Returns:
        PIL Image object, or None if the data could not be opened as
        an image.
    """
    source_image = None
    if not mem:
        try:
            source_image = Image.open(fspath)
        except OSError:
            print(f"Unable to load source file - {fspath!r}")
    else:
        # mem is True: fspath holds the raw image bytes.
        image_bytes = fspath if isinstance(fspath, bytes) else fspath.encode()
        try:  # fspath is a byte stream
            source_image = Image.open(BytesIO(image_bytes))
        except OSError:
            print("IOError")
            # log.debug("PIL was unable to identify as an image file")
        except UserWarning:
            print("UserWarning!")
    return source_image


def resize_pil_image(source_image: Image.Image | None, size: tuple[int, int], fext: str) -> bytes | None:
    """
    Resize a PIL Image in place and return the encoded thumbnail bytes.

    Saves as PNG (to preserve alpha for icons); falls back to JPEG with an
    RGB conversion if the PNG save fails.

    Args:
        source_image: Pillow Image object to resize (modified in place).
        size: Maximum (width, height) for the thumbnail; aspect ratio is
            preserved.
        fext: File extension of the source file (e.g. .jpg). Currently
            unused — output format is always PNG or the JPEG fallback.

    Returns:
        Encoded thumbnail bytes, or None when source_image is None.
    """
    if source_image is None:
        return None

    with BytesIO() as image_data:  # = BytesIO()
        source_image.thumbnail(size, Image.Resampling.LANCZOS)
        try:
            source_image.save(
                fp=image_data,
                format="PNG",  # Need alpha channel support for icons, etc.
                compression=4,
                optimize=False,
            )
        except OSError:
            source_image = source_image.convert("RGB")
            source_image.save(fp=image_data, format="JPEG", optimize=False, quality=60)
        image_data.seek(0)
        data = image_data.getvalue()
    return data


def return_image_obj(fs_path: str, memory: bool = False) -> Image.Image | None:
    """
    Open a media file and return a PIL Image, dispatching by file extension.

    Looks up the extension in FILETYPE_DATA (loading it on first use) and
    routes to the matching loader: first PDF page for PDFs, midpoint frame
    for movies, or a direct image load for images.

    Args:
        fs_path: Fully qualified path to the media file.
        memory: If True and the file is an image, treat fs_path as raw
            image bytes instead of a path.

    Returns:
        PIL Image object, or None if the extension is not a PDF, movie,
        or image type (or the file could not be decoded).
    """
    if not filetypes.models.FILETYPE_DATA:
        print("Loading filetypes")
        filetypes.models.FILETYPE_DATA = filetypes.models.load_filetypes()

    source_image = None
    extension = Path(fs_path).suffix.lower() if Path(fs_path).suffix else ""

    if extension in ("", b"", None):
        # There is currently no concept of a "None" in filetypes
        extension = ".none"

    filetype = filetypes.models.FILETYPE_DATA[extension]
    if filetype.is_pdf:
        source_image = pdf_to_pil(fs_path)

    elif filetype.is_movie:
        source_image = movie_to_pil(fs_path)

    elif filetype.is_image:
        source_image = image_to_pil(fs_path, mem=memory)
    return source_image
