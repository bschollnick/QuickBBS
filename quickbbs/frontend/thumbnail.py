"""
Thumbnail routines for QuickBBS
"""

import os

# from typing import Iterator  # , Optional, Union, TypeVar, Generic

from django.conf import settings
from django.db.utils import IntegrityError
from filetypes.models import FILETYPE_DATA

# from quickbbs.models import IndexData  # , Thumbnails_Archives
from thumbnails.image_utils import (
    #    image_to_pil,
    #    movie_to_pil,
    #    pdf_to_pil,
    resize_pil_image,
    return_image_obj,
)
from cache_watcher.models import Cache_Storage

from frontend.utilities import (  # cr_tnail_img,; return_image_obj,
    #    read_from_disk,
    sync_database_disk,
)


# def images_in_dir(database, webpath) -> Iterator[IndexData]:
#     """
#     Check for images in the directory.
#     If they do not exist, try to load the directory, and test again.
#     If they do exist, grab the 1st image from the file list.
#
#     Args:
#         database (obj) - Django Database
#         webpath (str) - The directory to examine
#
#     Returns:
#         object::
#             The thumbnail (in memory) of the first image
#
#     Raises:
#         None
#
#     Examples
#     --------
#     """
#
#     #   What files exist in this directory?
#     filters = {"fqpndirectory": ensures_endswith(webpath.lower(), os.sep)}
#     # ,'ignore': False, 'delete_pending': False, "filetype__is_image": True}
#     files = get_xth_image(database, 0, filters)
#
#     if files is None or not os.path.exists(os.path.join(webpath, files.name)):
#         # No files exist in the database for this directory
#         print(f"* scanning due to No files exist, {webpath}")
#         read_from_disk(webpath, skippable=True)
#         # process_dir
#         files = get_xth_image(database, 0, filters)
#     return files


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
    if db_entry.small_thumb not in [b"", None]:
        # Does the thumbnail exist?
        raise ValueError("I shouldn't be here! - new_process_dir2 w/entry that has thumbnail")

    _, files = db_entry.files_in_dir()
    if not files:
        sync_database_disk(db_entry.fqpndirectory)
        _, files = db_entry.files_in_dir()

    if files:  # found an file in the directory to use for thumbnail purposes
        for file_to_thumb in files:
            if file_to_thumb.filetype.is_image:
                fs_d_fname = os.path.join(file_to_thumb.fqpndirectory, file_to_thumb.name)
                # file system location of directory
                fext = os.path.splitext(file_to_thumb.name)[1].lower()
                temp = resize_pil_image(
                    return_image_obj(fs_d_fname),
                    settings.IMAGE_SIZE["small"],
                    fext=fext,
                )
                # imagedata = temp
                db_entry.small_thumb = temp
                break
    if not db_entry.small_thumb:
        temp = return_image_obj(os.path.join(settings.IMAGES_PATH, FILETYPE_DATA[".dir"]["icon_filename"]))
        img_icon = resize_pil_image(temp, settings.IMAGE_SIZE["small"], FILETYPE_DATA[".dir"]["icon_filename"])
        # configdata["filetypes"]["dir"][2])
        db_entry.is_generic_icon = True
        db_entry.small_thumb = img_icon
    try:
        db_entry.save()
    except IntegrityError:
        pass


def invalidate_thumb(thumbnail):
    """
    The invalidate_thumb function accepts a Thumbnail object and sets all of its attributes
    to an empty byte string. It is used when the thumbnail file cannot be found on disk,
    or when the thumbnail file has been corrupted.

    :param thumbnail: Store the thumbnail data
    :return: The thumbnail object
    >>> test = quickbbs.models.IndexData()
    >>> test = invalidate_thumb(test)
    """
    thumbnail.FileSize = -1
    thumbnail.small_thumb = b""
    thumbnail.medium_thumb = b""
    thumbnail.large_thumb = b""
    return thumbnail


def new_process_img(
    entry,
):  # , imagesize="small"):
    """
    input:
        entry - The IndexData entry
        request - The request data from Django
        imagesize - (small, medium, large constant)

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
    fext = os.path.splitext(fs_fname)[1][1:].lower()
    entry.file_tnail = invalidate_thumb(entry.file_tnail)

    # https://stackoverflow.com/questions/1167398/python-access-class-property-from-string
    temp = return_image_obj(fs_fname)
    for size in ["large", "medium", "small"]:
        imagedata = resize_pil_image(temp, settings.IMAGE_SIZE[size], fext=fext)
        setattr(entry.file_tnail, f"{size}_thumb", imagedata)

    entry.file_tnail.FileSize = entry.size
    # entry.file_tnail.save()
    return entry


#
# def new_process_archive(ind_entry, request, page=0):
#     """
#     Process an archive, and return the thumbnail
#
#     TBD: Broken, needs rewrite, it's been broken for a *while*.
#     """
#     thumbsize = g_option(request, "size", "small").lower().strip()
#     fs_archname = settings.ALBUMS_PATH + os.path.join(
#         ind_entry.fqpndirectory.lower(), ind_entry.name
#     )
#     fs_archname = fs_archname.replace("//", "/").strip()
#
#     # file system location of directory
#
#     # existing_tnails = Thumbnails_Archives.objects.filter(uuid=ind_entry.uuid)
#     # This contains all the Archive thumbnails that match the uuid, in otherwords
#     # all existing cached pages.
#
#     # Check to see if the page in question is being cached.
#     #    specific_page, created = Thumbnails_Archives.objects.get_or_create(
#     specific_page, _ = Thumbnails_Archives.objects.get_or_create(
#         uuid=ind_entry.uuid,
#         page=page,
#         defaults={
#             "uuid": ind_entry.uuid,
#             "page": page,
#             "FilePath": ind_entry.fqpndirectory,
#             "FileName": ind_entry.name,
#         },
#     )
#
#     #    print ("fs archname: ",fs_archname)
#     archive_file = archives.id_cfile_by_sig(fs_archname)
#     archive_file.get_listings()
#     fn_to_extract = archive_file.listings[page][0]
#     #    print (fn_to_extract, page)
#     fext = os.path.splitext(fn_to_extract)[1][1:].lower()
#     data = archive_file.extract_mem_file(fn_to_extract)
#     im_data = return_image_obj(data, memory=True)
#     if im_data is None:
#         im_data = return_image_obj(
#             os.path.join(
#                 settings.RESOURCES_PATH, "images", FILETYPE_DATA[fext]["icon_filename"]
#             ),
#             memory=True,
#         )
#
#         return return_img_attach(
#             FILETYPE_DATA[fext]["icon_filename"], im_data, fext_override="JPEG"
#         )
#
#     if specific_page.FileSize != os.path.getsize(fs_archname):
#         #   The cached data is invalidated since the filesize is inaccurate.
#         #   Reset the existing thumbnails to ensure that they will be regenerated
#         specific_page = invalidate_thumb(specific_page)
#         specific_page.save()
#
#     specific_page.FileSize = os.path.getsize(fs_archname)
#     if thumbsize == "large":
#         if specific_page.large_thumb == b"":
#             try:
#                 specific_page.large_thumb = resize_pil_image(
#                     im_data, settings.IMAGE_SIZE[thumbsize], fext=fext
#                 )
#                 specific_page.save()
#             except OSError:
#                 im_data = return_image_obj(
#                     os.path.join(
#                         settings.RESOURCES_PATH,
#                         "images",
#                         FILETYPE_DATA["archive"]["icon_filename"],
#                     ),
#                     memory=True,
#                 )
#
#             return return_img_attach(
#                 os.path.basename(fs_archname),
#                 specific_page.large_thumb,
#                 fext_override="JPEG",
#             )
#         return return_img_attach(
#             os.path.basename(fs_archname),
#             specific_page.large_thumb.tobytes(),
#             fext_override="JPEG",
#         )
#
#     if thumbsize == "medium":
#         if specific_page.medium_thumb == b"":
#             try:
#                 specific_page.medium_thumb = resize_pil_image(
#                     im_data, settings.IMAGE_SIZE[thumbsize], fext=fext
#                 )
#                 specific_page.save()
#             except OSError:
#                 im_data = return_image_obj(
#                     os.path.join(
#                         settings.RESOURCES_PATH,
#                         "images",
#                         FILETYPE_DATA["archive"]["icon_filename"],
#                     ),
#                     memory=True,
#                 )
#             return_img_attach(
#                 os.path.basename(fs_archname),
#                 specific_page.medium_thumb,
#                 fext_override="JPEG",
#             )
#         return return_img_attach(
#             os.path.basename(fs_archname),
#             specific_page.medium_thumb.tobytes(),
#             fext_override="JPEG",
#         )
#
#     if thumbsize == "small":
#         if specific_page.small_thumb == b"":
#             try:
#                 specific_page.small_thumb = resize_pil_image(
#                     im_data, settings.IMAGE_SIZE[thumbsize], fext=fext
#                 )
#                 specific_page.save()
#             except OSError:
#                 im_data = return_image_obj(
#                     os.path.join(
#                         settings.RESOURCES_PATH,
#                         "images",
#                         FILETYPE_DATA["archive"]["icon_filename"],
#                     ),
#                     memory=True,
#                 )
#             return return_img_attach(
#                 os.path.basename(fs_archname),
#                 specific_page.small_thumb,
#                 fext_override="JPEG",
#             )
#         return return_img_attach(
#             os.path.basename(fs_archname),
#             specific_page.small_thumb.tobytes(),
#             fext_override="JPEG",
#         )
#     return return_img_attach(os.path.basename(fs_archname), None, fext_override="JPEG")
