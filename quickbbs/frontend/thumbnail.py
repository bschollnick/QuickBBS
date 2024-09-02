"""
Thumbnail routines for QuickBBS
"""

import os

from django.conf import settings
from django.db.utils import IntegrityError

from cache_watcher.models import Cache_Storage
import filetypes
from frontend.utilities import \
    sync_database_disk  # cr_tnail_img,; return_image_obj,; read_from_disk,
# from quickbbs.models import IndexData  # , Thumbnails_Archives
from thumbnails.image_utils import (  # image_to_pil,; movie_to_pil,; pdf_to_pil,
    resize_pil_image, return_image_obj)

# from typing import Iterator  # , Optional, Union, TypeVar, Generic





def new_process_dir2(db_entry):
    """
    input:
        entry - The IndexData entry

    Read directory, and identify the first thumbnailable file.
    Make thumbnail of that file
    Return thumbnail results

    Since we are just looking for a thumbnailable image, it doesn't have
    to be the most up to date, nor the most current.  Cached is fine.
    """
    #
    # webpath contains the URL equivalent to the file system path (fs_path)
    #
    if not filetypes.models.FILETYPE_DATA:
        print("Loading thumbnails filetypes")
        filetypes.models.FILETYPE_DATA = filetypes.models.load_filetypes()

    if db_entry.small_thumb not in [b"", None]:
        # Does the thumbnail exist?
        raise ValueError(
            "I shouldn't be here! - new_process_dir2 w/entry that has thumbnail"
        )

    files = db_entry.files_in_dir()
    if not files:
        sync_database_disk(db_entry.fqpndirectory)
        files = db_entry.files_in_dir()

    if files:  # found an file in the directory to use for thumbnail purposes
        for file_to_thumb in files:
            if file_to_thumb.filetype.is_image:
                fs_d_fname = os.path.join(
                    file_to_thumb.fqpndirectory, file_to_thumb.name
                )
                # file system location of directory
                fext = os.path.splitext(file_to_thumb.name)[1].lower()
                img_icon = resize_pil_image(
                    return_image_obj(fs_d_fname),
                    settings.IMAGE_SIZE["small"],
                    fext=fext,
                )
                # imagedata = temp
                db_entry.small_thumb = img_icon
                break
    if not db_entry.small_thumb:
        temp = return_image_obj(
            os.path.join(settings.IMAGES_PATH, filetypes.models.FILETYPE_DATA[".dir"]["icon_filename"])
        )
        img_icon = resize_pil_image(
            temp, settings.IMAGE_SIZE["small"], filetypes.models.FILETYPE_DATA[".dir"]["icon_filename"]
        )
        # configdata["filetypes"]["dir"][2])
        db_entry.is_generic_icon = True
        db_entry.small_thumb = img_icon
    try:
        db_entry.save()
    except IntegrityError:
        pass


def new_process_img(
    entry,
):
    """
    input:
        entry - The IndexData entry

    Read directory, and identify the first thumbnailable file.
    Make thumbnail of that file
    Return thumbnail results

    Since we are just looking for a thumbnailable image, it doesn't have
    to be the most up to date, nor the most current.  Cached is fine.
    """
    fs_fname = os.path.join(entry.fqpndirectory, entry.name).replace("//", "/")
    # file system location of directory
    if not os.path.exists(fs_fname):
        Cache_Storage.remove_from_cache_name(DirName=entry.fqpndirectory)
        return None
    # fext = os.path.splitext(fs_fname)[1][1:].lower()
    entry.file_tnail.invalidate_thumb()
    entry.file_tnail.image_to_thumbnail()
    entry.file_tnail.FileSize = entry.size
    return entry