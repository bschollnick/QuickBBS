"""
Utilities for QuickBBS, the python edition.
"""

import os
import os.path
from io import BytesIO

# from moviepy.video.io import VideoFileClip
# from moviepy.editor import VideoFileClip #* # import everythings (variables, classes, methods...)
# inside moviepy.editor
import av  # Video Previews
import fitz  # PDF previews
from django.conf import settings
from PIL import Image

import filetypes.models as filetype_models


def pdf_to_pil(fspath):
    """
    The load_pdf function loads a PDF file from the filesystem and returns an image.

    :param fspath: Load the file
    :return: A pil
    :doc-author: Trelent
    """
    #    if filetype_models.FILETYPE_DATA[os.path.splitext(fspath).lower()]["is_pdf"]:
    # Do not repair the PDF / validate the PDF.  If it's bad,
    # it should be repaired, not band-aided by a patch from the web server.
    # results = pdf_utilities.check_pdf(fs_path)
    with fitz.open(fspath) as pdf_file:
        pdf_page = pdf_file.load_page(0)
        # matrix=fitz.Identity, alpha=True)
        pix = pdf_page.get_pixmap(alpha=True)
        try:
            source_image = Image.open(BytesIO(pix.tobytes()))
        except UserWarning:
            print("UserWarning!")
            source_image = None
    return source_image


def movie_to_pil(fspath):
    """
    The load_movie function loads a movie from the file system and returns an image.

        Updated - 2022/12/21 - It will now search for the next
    :param fspath: Specify the path to the video file
    :param offset_from: The number of frames to advance *after* detecting a non-solid
        black or white frame.
    :return: A pillow image object

    References:
        * https://stackoverflow.com/questions/14041562/
            python-pil-detect-if-an-image-is-completely-black-or-white
    """
    image = None
    try:
        with av.open(fspath) as container:
            stream = container.streams.video[0]
            # duration_sec = stream.frames / 30
            container.seek(container.duration // 2)
            frame = container.decode(stream)
            image = next(frame).to_image()
    except av.error.InvalidDataError:
        image = Image.open(
            #            return_image_obj(
            os.path.join(
                settings.RESOURCES_PATH, "images", "3559224-200_broken_video.png"
            )
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


def image_to_pil(fspath, mem=False):
    """
    The load_image function loads an image from a file path or byte stream.
    It returns the source_image object, which is a PIL Image object.

    :param fspath: Pass the path of the image file
    :param mem: Determine if the source file is a local file or a byte stream, if true, byte stream
    :return: A pil / Image object
    """
    source_image = None
    if not mem:
        try:
            source_image = Image.open(fspath)
        except OSError:
            print(f"Unable to load source file - {fspath}")
    else:
        try:  # fs_path is a byte stream
            source_image = Image.open(BytesIO(fspath))
        except OSError:
            print("IOError")
            # log.debug("PIL was unable to identify as an image file")
        except UserWarning:
            print("UserWarning!")
    return source_image


def resize_pil_image(source_image, size, fext) -> Image:
    """
    Given the PILLOW object, resize the image to <SIZE>
    and return the saved version of the file (using FEXT
    as the format to save as [eg. PNG])

    Return the binary representation of the file that
    was saved to memory

    Args:
        source_image (PIL.Image): Pillow Image Object to modify
        size (Str) : The size to resize the image to (e.g. 200 for 200x200)
            This always is set as (size, size)
        fext (str): The file extension of the file that is to be processed
            e.g. .jpg, .mp4

    returns:
        blob: The binary blog of the thumbnail

    """
    if source_image is None:
        return None
    fext = fext.lower().strip()
    if not fext.startswith("."):
        fext = f".{fext}"

    if fext in settings.MOVIE_FILE_TYPES:
        fext = ".jpg"

    with BytesIO() as image_data:  # = BytesIO()
        source_image.thumbnail((size, size), Image.Resampling.LANCZOS)
        try:
            source_image.save(
                fp=image_data,
                format="PNG",  # Need alpha channel support for icons, etc.
                optimize=False,
            )
        except OSError:
            source_image = source_image.convert("RGB")
            source_image.save(fp=image_data, format="JPEG", optimize=False)
        image_data.seek(0)
        data = image_data.getvalue()
    return data


def return_image_obj(fs_path, memory=False) -> Image:
    """
    Given a Fully Qualified FileName/Pathname, open the image
    (or PDF) and return the PILLOW object for the image
    Fitz == py


    Args:
        fs_path (str) - File system path
        memory (bool) - Is this to be mapped in memory

    Returns:
        boolean::
            `True` if uuid_to_test is a valid UUID, otherwise `False`.

    Raises:
        obj::
            Pillow image object


    Examples
    --------
    """
    source_image = None
    extension = os.path.splitext(fs_path)[1].lower()

    if extension in ("", b"", None):
        # There is currently no concept of a "None" in filetypes
        extension = ".none"

    if filetype_models.FILETYPE_DATA[extension]["is_pdf"]:
        source_image = pdf_to_pil(fs_path)

    elif filetype_models.FILETYPE_DATA[extension]["is_movie"]:
        source_image = movie_to_pil(fs_path)

    elif filetype_models.FILETYPE_DATA[extension]["is_image"]:
        source_image = image_to_pil(fs_path, mem=memory)
    return source_image
