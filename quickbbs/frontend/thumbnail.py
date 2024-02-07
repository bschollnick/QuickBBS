"""
Thumbnail routines for QuickBBS
"""

import os
from typing import Iterator  # , Optional, Union, TypeVar, Generic

from django.conf import settings
from quickbbs.models import Thumbnails_Archives, index_data

import frontend.archives3 as archives
from filetypes.models import FILETYPE_DATA
from frontend.database import get_xth_image
from frontend.utilities import (
    cr_tnail_img,
    read_from_disk,
    return_image_obj,
    sync_database_disk,
)
from frontend.web import g_option  # , respond_as_attachment
from frontend.web import return_img_attach  # , return_inline_attach
from django.db.utils import IntegrityError


def ensures_endswith(string_to_check, value) -> str:
    """
    The ensures_endswith function ensures that the string_to_check ends with value.
    If it does not, then value is appended to the end of string_to_check.

    :param string_to_check: Store the string that is being checked
    :param value: Add a value to the end of the string_to_check if it doesn't
        already have that value at its end
    :return: A string with the value appended to it

    Examples
    --------
    >>> ensures_endswith("test", os.sep)
    test/
    >>> ensures_endswith("balony", os.sep)
    balony/
    """
    if not string_to_check.endswith(value):
        string_to_check = f"{string_to_check}{value}"
    return string_to_check


def images_in_dir(database, webpath) -> Iterator[index_data]:
    """
    Check for images in the directory.
    If they do not exist, try to load the directory, and test again.
    If they do exist, grab the 1st image from the file list.

    Args:
        database (obj) - Django Database
        webpath (str) - The directory to examine

    Returns:
        object::
            The thumbnail (in memory) of the first image

    Raises:
        None

    Examples
    --------
    """

    #   What files exist in this directory?
    filters = {"fqpndirectory": ensures_endswith(webpath.lower(), os.sep)}
    # ,'ignore': False, 'delete_pending': False, "filetype__is_image": True}
    files = get_xth_image(database, 0, filters)

    if files is None or not os.path.exists(os.path.join(webpath, files.name)):
        # No files exist in the database for this directory
        print(f"* scanning due to No files exist, {webpath}")
        read_from_disk(webpath, skippable=True)
        # process_dir
        files = get_xth_image(database, 0, filters)
    return files


def new_process_dir2(db_entry):
    """
    input:
        entry - The index_data entry

    Read directory, and identify the first thumbnailable file.
    Make thumbnail of that file
    Return thumbnail results

    Since we are just looking for a thumbnailable image, it doesn't have
    to be the most up to date, nor the most current.  Cached is fine.
    """
    #
    # webpath contains the URL equivalent to the file system path (fs_path)
    #
    if db_entry.SmallThumb not in [b"", None]:
        # Does the thumbnail exist?
        raise ValueError(
            "I shouldn't be here! - new_process_dir2 w/entry that has thumbnail"
        )

    files_found, files = db_entry.files_in_dir()
    if not files:
        sync_database_disk(db_entry.DirName)
        files = db_entry.files_in_directory()

    if files:  # found an file in the directory to use for thumbnail purposes
        for file_to_thumb in files:
            if file_to_thumb.filetype.is_image:
                fs_d_fname = os.path.join(
                    file_to_thumb.fqpndirectory, file_to_thumb.name
                )
                # file system location of directory
                fext = os.path.splitext(file_to_thumb.name)[1].lower()
                temp = cr_tnail_img(
                    return_image_obj(fs_d_fname),
                    settings.IMAGE_SIZE["small"],
                    fext=fext,
                )
                # imagedata = temp
                db_entry.SmallThumb = temp
    if not db_entry.SmallThumb:
        temp = return_image_obj(
            os.path.join(settings.IMAGES_PATH, FILETYPE_DATA[".dir"]["icon_filename"])
        )
        img_icon = cr_tnail_img(
            temp, settings.IMAGE_SIZE["small"], FILETYPE_DATA[".dir"]["icon_filename"]
        )
        # configdata["filetypes"]["dir"][2])
        db_entry.is_generic_icon = True
        db_entry.SmallThumb = img_icon
    try:
        db_entry.save()
    except IntegrityError:
        pass


def new_process_dir(db_index):
    """
    input:
        entry - The index_data entry

    Read directory, and identify the first thumbnailable file.
    Make thumbnail of that file
    Return thumbnail results

    Since we are just looking for a thumbnailable image, it doesn't have
    to be the most up to date, nor the most current.  Cached is fine.
    """
    #
    # webpath contains the URL equivalent to the file system path (fs_path)
    #
    # imagedata = None
    if db_index.directory.SmallThumb not in [b"", None]:
        # Does the thumbnail exist?
        # if db_index.size == db_index.directory.FileSize:
        # print(f"size mismatch, {db_index.name} - {db_index.directory.FileSize}")
        #    return db_index.send_thumbnail(filename=db_index.name, size="small")
        #   The cached data is invalidated since the filesize is
        #   inaccurate or the image does not pass verify.
        #   Reset the existing thumbnails to ensure that they will be
        #   regenerated
        db_index.directory.FileSize = -1
        db_index.directory.SmallThumb = b""

    files = images_in_dir(
        index_data,
        ensures_endswith(
            os.path.join(db_index.fqpndirectory, db_index.name).lower(), os.sep
        ),
    )
    #    print("\n\n !!! = ",os.path.join(db_index.fqpndirectory,
    #                                       db_index.name).lower(), files)
    if files:  # found an file in the directory to use for thumbnail purposes
        # print ("Files found in directory")
        fs_d_fname = os.path.join(
            db_index.fqpndirectory.lower(), db_index.name, files.name
        )
        # file system location of directory
        fext = os.path.splitext(files.name)[1].lower()

        temp = cr_tnail_img(
            return_image_obj(fs_d_fname), settings.IMAGE_SIZE["small"], fext=fext
        )
        # imagedata = temp
        db_index.directory.SmallThumb = temp
        db_index.directory.FileSize = db_index.size
    else:
        #
        #   There are no files in the directory
        #
        temp = return_image_obj(
            os.path.join(settings.IMAGES_PATH, FILETYPE_DATA[".dir"]["icon_filename"])
        )
        img_icon = cr_tnail_img(
            temp, settings.IMAGE_SIZE["small"], FILETYPE_DATA[".dir"]["icon_filename"]
        )
        # configdata["filetypes"]["dir"][2])
        db_index.is_generic_icon = True
        db_index.directory.SmallThumb = img_icon
        db_index.directory.FileSize = db_index.size
    #            print("Set size to %s for %s" % (db_index.directory.FileSize,
    #                                             fs_d_fname))
    try:
        db_index.directory.save()
        db_index.save()
    except IntegrityError:
        pass


def invalidate_thumb(thumbnail):
    """
    The invalidate_thumb function accepts a Thumbnail object and sets all of its attributes
    to an empty byte string. It is used when the thumbnail file cannot be found on disk,
    or when the thumbnail file has been corrupted.

    :param thumbnail: Store the thumbnail data
    :return: The thumbnail object
    >>> test = quickbbs.models.index_data()
    >>> test = invalidate_thumb(test)
    """
    thumbnail.FileSize = -1
    thumbnail.SmallThumb = b""
    thumbnail.MediumThumb = b""
    thumbnail.LargeThumb = b""
    return thumbnail


def new_process_img(entry, request, imagesize="Small"):
    """
    input:
        entry - The index_data entry
        request - The request data from Django
        imagesize - (small, medium, large constant)

    Read directory, and identify the first thumbnailable file.
    Make thumbnail of that file
    Return thumbnail results

    Since we are just looking for a thumbnailable image, it doesn't have
    to be the most up to date, nor the most current.  Cached is fine.
    """
    thumb_size = g_option(request, "size", "Small").title()
    existing_data = getattr(entry.file_tnail, f"{thumb_size}Thumb")
    if existing_data != b"":
        # Does the thumbnail exist?
        if entry.size == entry.file_tnail.FileSize:
            # If size matches, then image is most likely the existing cached image
            # return the existing cached image
            # return return_inline_attach(entry.name, existing_data)
            return entry  # entry.send_thumbnail(filename=entry.name, fext_override=None, size=imagesize)

    fs_fname = os.path.join(entry.fqpndirectory, entry.name).replace("//", "/")
    # file system location of directory

    fext = os.path.splitext(fs_fname)[1][1:].lower()
    entry.file_tnail = invalidate_thumb(entry.file_tnail)

    # https://stackoverflow.com/questions/1167398/python-access-class-property-from-string
    temp = return_image_obj(fs_fname)
    #
    for size in ["Large", "Medium", "Small"]:
        imagedata = cr_tnail_img(temp, settings.IMAGE_SIZE[size.lower()], fext=fext)
        setattr(entry.file_tnail, f"{size}Thumb", imagedata)

    entry.file_tnail.FileSize = entry.size
    # entry.file_tnail.save()
    return entry
    #
    #   switch to new
    # entry.send_inline


#    imagedata = getattr(entry.file_tnail, f"{thumb_size}Thumb")
#    return return_img_attach(entry.name, imagedata, fext_override="JPEG")


def new_process_archive(ind_entry, request, page=0):
    """
    Process an archive, and return the thumbnail

    TBD: Broken, needs rewrite, it's been broken for a *while*.
    """
    thumbsize = g_option(request, "size", "small").lower().strip()
    fs_archname = settings.ALBUMS_PATH + os.path.join(
        ind_entry.fqpndirectory.lower(), ind_entry.name
    )
    fs_archname = fs_archname.replace("//", "/").strip()

    # file system location of directory

    # existing_tnails = Thumbnails_Archives.objects.filter(uuid=ind_entry.uuid)
    # This contains all the Archive thumbnails that match the uuid, in otherwords
    # all existing cached pages.

    # Check to see if the page in question is being cached.
    #    specific_page, created = Thumbnails_Archives.objects.get_or_create(
    specific_page, _ = Thumbnails_Archives.objects.get_or_create(
        uuid=ind_entry.uuid,
        page=page,
        defaults={
            "uuid": ind_entry.uuid,
            "page": page,
            "FilePath": ind_entry.fqpndirectory,
            "FileName": ind_entry.name,
        },
    )

    #    print ("fs archname: ",fs_archname)
    archive_file = archives.id_cfile_by_sig(fs_archname)
    archive_file.get_listings()
    fn_to_extract = archive_file.listings[page][0]
    #    print (fn_to_extract, page)
    fext = os.path.splitext(fn_to_extract)[1][1:].lower()
    data = archive_file.extract_mem_file(fn_to_extract)
    im_data = return_image_obj(data, memory=True)
    if im_data is None:
        im_data = return_image_obj(
            os.path.join(
                settings.RESOURCES_PATH, "images", FILETYPE_DATA[fext]["icon_filename"]
            ),
            memory=True,
        )

        return return_img_attach(
            FILETYPE_DATA[fext]["icon_filename"], im_data, fext_override="JPEG"
        )

    if specific_page.FileSize != os.path.getsize(fs_archname):
        #   The cached data is invalidated since the filesize is inaccurate.
        #   Reset the existing thumbnails to ensure that they will be regenerated
        specific_page = invalidate_thumb(specific_page)
        specific_page.save()

    specific_page.FileSize = os.path.getsize(fs_archname)
    if thumbsize == "large":
        if specific_page.LargeThumb == b"":
            try:
                specific_page.LargeThumb = cr_tnail_img(
                    im_data, settings.IMAGE_SIZE[thumbsize], fext=fext
                )
                specific_page.save()
            except OSError:
                im_data = return_image_obj(
                    os.path.join(
                        settings.RESOURCES_PATH,
                        "images",
                        FILETYPE_DATA["archive"]["icon_filename"],
                    ),
                    memory=True,
                )

            return return_img_attach(
                os.path.basename(fs_archname),
                specific_page.LargeThumb,
                fext_override="JPEG",
            )
        return return_img_attach(
            os.path.basename(fs_archname),
            specific_page.LargeThumb.tobytes(),
            fext_override="JPEG",
        )

    if thumbsize == "medium":
        if specific_page.MediumThumb == b"":
            try:
                specific_page.MediumThumb = cr_tnail_img(
                    im_data, settings.IMAGE_SIZE[thumbsize], fext=fext
                )
                specific_page.save()
            except OSError:
                im_data = return_image_obj(
                    os.path.join(
                        settings.RESOURCES_PATH,
                        "images",
                        FILETYPE_DATA["archive"]["icon_filename"],
                    ),
                    memory=True,
                )
            return_img_attach(
                os.path.basename(fs_archname),
                specific_page.MediumThumb,
                fext_override="JPEG",
            )
        return return_img_attach(
            os.path.basename(fs_archname),
            specific_page.MediumThumb.tobytes(),
            fext_override="JPEG",
        )

    if thumbsize == "small":
        if specific_page.SmallThumb == b"":
            try:
                specific_page.SmallThumb = cr_tnail_img(
                    im_data, settings.IMAGE_SIZE[thumbsize], fext=fext
                )
                specific_page.save()
            except OSError:
                im_data = return_image_obj(
                    os.path.join(
                        settings.RESOURCES_PATH,
                        "images",
                        FILETYPE_DATA["archive"]["icon_filename"],
                    ),
                    memory=True,
                )
            return return_img_attach(
                os.path.basename(fs_archname),
                specific_page.SmallThumb,
                fext_override="JPEG",
            )
        return return_img_attach(
            os.path.basename(fs_archname),
            specific_page.SmallThumb.tobytes(),
            fext_override="JPEG",
        )
    return return_img_attach(os.path.basename(fs_archname), None, fext_override="JPEG")
