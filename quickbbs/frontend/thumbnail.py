"""
Thumbnail routines for QuickBBS
"""

import os

#import filetypes
from filetypes.models import filetypes as filetypes_model
from cache_watcher.models import Cache_Storage
from django.conf import settings
from django.db.utils import IntegrityError
from frontend.utilities import (
    sync_database_disk,  # cr_tnail_img,; return_image_obj,; read_from_disk,
)

# from quickbbs.models import IndexData  # , Thumbnails_Archives
from thumbnails.image_utils import (  # image_to_pil,; movie_to_pil,; pdf_to_pil,
    resize_pil_image,
    return_image_obj,
)


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
    
    files = db_entry.files_in_dir(additional_filters={"filetype__is_image": True})

    if not files:
        sync_database_disk(db_entry.fqpndirectory)
        files = db_entry.files_in_dir(additional_filters={"filetype__is_image": True})

    if files:  # found an file in the directory to use for thumbnail purposes
        for file_to_thumb in files:
            fs_d_fname = os.path.join(file_to_thumb.fqpndirectory, file_to_thumb.name)
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
    if db_entry.small_thumb in [b"", None]:
        temp = return_image_obj(
            filetypes_model.return_any_icon_filename(fileext=".dir")
        )
        img_icon = resize_pil_image(
            temp,
            settings.IMAGE_SIZE["small"],
            fext=".dir",
        )
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
    entry.file_tnail.invalidate_thumb()
    if entry.file_tnail.image_to_thumbnail() is None:
        Cache_Storage.remove_from_cache_name(DirName=entry.fqpndirectory)
        return None

    entry.file_tnail.FileSize = entry.size
    return entry
