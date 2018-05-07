# coding: utf-8
"""
Thumbnail routines for QuickBBS
"""
from __future__ import absolute_import, print_function, unicode_literals

import os
#import sys

import frontend.archives3 as archives
from frontend.config import configdata as configdata
from frontend.database import get_xth_image
from frontend.utilities import (cr_tnail_img, return_image_obj,
                                read_from_disk)
from frontend.web import return_img_attach, g_option
from quickbbs.models import (index_data,
                             #Thumbnails_Dirs,
                             #Thumbnails_Files,
                             Thumbnails_Archives)

sizes = {
    "small":configdata["configuration"]["small"],
    "medium":configdata["configuration"]["medium"],
    "large":configdata["configuration"]["large"],
    "unknown":configdata["configuration"]["small"]
}

def images_in_dir(database, webpath):
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
    #>>> is_valid_uuid('c9bf9e57-1685-4c89-bafb-ff5af830be8a')
    #True
    #>>> is_valid_uuid('c9bf9e58')
    #False
    """

    files = None
    prefilters = {'fqpndirectory':webpath.lower(), 'is_dir':False,
                  'ignore':False, 'delete_pending':False}
    filters = {'fqpndirectory':webpath.lower(), 'is_dir':False,
               'is_image':True, 'is_archive':False,
               'ignore':False, 'delete_pending':False}

    #   What files exist in this directory?
    files = get_xth_image(database, 0, prefilters)
    if files is None:
        # No files exist in the database for this directory
        print("* No files exist, %s" % webpath)
        read_from_disk(configdata["locations"]["albums_path"] + webpath)
        # process_dir
    files = get_xth_image(database, 0, filters)
    return files

def new_process_dir(entry):
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
    files = images_in_dir(index_data,
                          os.path.join(entry.fqpndirectory.lower(),
                                       entry.name))
    if files: # found an file in the directory to use for thumbnail purposes
        fs_d_fname = configdata["locations"]["albums_path"] +\
                    os.path.join(entry.fqpndirectory.lower(),
                                 entry.name, files.name)
                 # file system location of directory

        fext = os.path.splitext(files.name)[1][1:].lower()

#            if fext in configdata["filetypes"]:
#                if configdata["filetypes"][fext][1].strip() != "None":
#                    fs_path = os.path.join(
#                        configdata["locations"]["resources_path"],
#                        "images", configdata["filetypes"][fext][1])

        if entry.directory.FileSize != os.path.getsize(fs_d_fname):
            #   The cached data is invalidated since the filesize is
            #   inaccurate.
            #   Reset the existing thumbnails to ensure that they will be
            #   regenerated
            print("size mismatch, %s - %s - %s" % (entry.directory.FileSize,
                                                   entry.name, fs_d_fname))
            entry.directory.FileSize = -1
            entry.directory.SmallThumb = b""
            entry.directory.save()
            entry.save()

        if not entry.directory.SmallThumb or entry.directory.FileSize == -1:
            print("No existing SmallThumb")
            temp = return_image_obj(fs_d_fname)
            entry.directory.SmallThumb = cr_tnail_img(temp,
                                                      sizes["small"],
                                                      fext=fext)
            entry.directory.FileSize = os.path.getsize(fs_d_fname)
            print("Set size to %s for %s" % (entry.directory.FileSize,
                                             fs_d_fname))
            entry.directory.save()
            entry.save()
    else:
        temp = return_image_obj(configdata["locations"]["images_path"]+\
            os.sep + configdata["filetypes"]["dir"][1])
        img_icon = cr_tnail_img(temp, sizes["small"],
                                configdata["filetypes"]["dir"][2])
        return return_img_attach(os.path.basename(
            configdata["filetypes"]["dir"][1]), img_icon)

    return return_img_attach(entry.name, entry.directory.SmallThumb)

def new_process_img(entry, request):
    """
    input:
        entry - The index_data entry

    Read directory, and identify the first thumbnailable file.
    Make thumbnail of that file
    Return thumbnail results

    Since we are just looking for a thumbnailable image, it doesn't have
    to be the most up to date, nor the most current.  Cached is fine.
    """
    thumb_size = g_option(request, "size", "small").lower().strip()

    fs_fname = configdata["locations"]["albums_path"] +\
                os.path.join(entry.fqpndirectory.lower(),
                             entry.name)
    fs_fname = fs_fname.replace("//", "/")
             # file system location of directory

    fext = os.path.splitext(fs_fname)[1][1:].lower()


    if entry.file_tnail.FileSize != os.path.getsize(fs_fname):
        #   The cached data is invalidated since the filesize is
        #   inaccurate.
        #   Reset the existing thumbnails to ensure that they will be
        #   regenerated
        print("size mismatch, %s - %s - %s" % (entry.size,
                                               entry.name, fs_fname))
        entry.file_tnail.FileSize = -1
        entry.file_tnail.SmallThumb = b""
        entry.file_tnail.MediumThumb = b""
        entry.file_tnail.LargeThumb = b""
        entry.file_tnail.save()
    if thumb_size == "small":
        if entry.file_tnail.SmallThumb == b"":
            print("No existing SmallThumb")
            temp = return_image_obj(fs_fname)
            entry.file_tnail.SmallThumb = cr_tnail_img(temp, sizes["small"],
                                                       fext=fext)
            entry.file_tnail.FileSize = os.path.getsize(fs_fname)
            entry.file_tnail.save()
            print("Set size to %s for %s" % (entry.file_tnail.FileSize,
                                             fs_fname))
            entry.save()
        return return_img_attach(entry.name, entry.file_tnail.SmallThumb)
    elif thumb_size == "medium":
        if not entry.file_tnail.MediumThumb:
            print("No existing MediumThumb")
            temp = return_image_obj(fs_fname)
            entry.file_tnail.MediumThumb = cr_tnail_img(temp,
                                                        sizes["medium"],
                                                        fext=fext)
            entry.file_tnail.FileSize = os.path.getsize(fs_fname)
            entry.file_tnail.save()
            print("Set size to %s for %s" % (entry.file_tnail.FileSize,
                                             fs_fname))
            entry.save()
        return return_img_attach(entry.name, entry.file_tnail.MediumThumb)
    elif thumb_size == "large":
        if not entry.file_tnail.LargeThumb:
            print("No existing LargeThumb")
            temp = return_image_obj(fs_fname)
            entry.file_tnail.LargeThumb = cr_tnail_img(temp, sizes["large"],
                                                       fext=fext)
            entry.file_tnail.FileSize = os.path.getsize(fs_fname)
            print("Set size to %s for %s" % (entry.file_tnail.FileSize,
                                             fs_fname))
            entry.file_tnail.save()
            entry.save()
        return return_img_attach(entry.name, entry.file_tnail.LargeThumb)
    return return_img_attach(entry.name, entry.file_tnail.SmallThumb)

def new_process_archive(ind_entry, request, page=0):
    """
    Process an archive, and return the thumbnail
    """
    thumbsize = g_option(request, "size", "small").lower().strip()
    fs_archname = configdata["locations"]["albums_path"] +\
                os.path.join(ind_entry.fqpndirectory.lower(),
                             ind_entry.name)
    fs_archname = fs_archname.replace("//", "/")

             # file system location of directory

    existing_tnails = Thumbnails_Archives.objects.filter(uuid=ind_entry.uuid)
        # This contains all the Archive thumbnails that match the uuid, in otherwords
        # all existing cached pages.

    # Check to see if the page in question is being cached.
    specific_page, created = Thumbnails_Archives.objects.get_or_create(
        uuid=ind_entry.uuid, page=page,
        defaults={'uuid':ind_entry.uuid,
                  'page':page,
                  'FilePath':ind_entry.fqpndirectory,
                  'FileName':ind_entry.name})

    archive_file = archives.id_cfile_by_sig(fs_archname)
    archive_file.get_listings()
    fn_to_extract = archive_file.listings[page]
    fext = os.path.splitext(fn_to_extract)[1][1:].lower()
    data = archive_file.extract_mem_file(fn_to_extract)
    im_data = return_image_obj(data, memory=True)
    if specific_page.FileSize != os.path.getsize(fs_archname):
        #   The cached data is invalidated since the filesize is
        #   inaccurate.
        #   Reset the existing thumbnails to ensure that they will be
        #   regenerated
        specific_page.FileSize = -1
        specific_page.SmallThumb = b""
        specific_page.MediumThumb = b""
        specific_page.LargeThumb = b""
        specific_page.save()

    specific_page.FileSize = os.path.getsize(fs_archname)
    if thumbsize == "large":
        if not specific_page.LargeThumb:
            try:
                specific_page.LargeThumb = cr_tnail_img(im_data,
                                                        sizes[thumbsize],
                                                        fext=fext)
                specific_page.save()
            except IOError:
                im_data = return_image_obj(os.path.join(
                    configdata["locations"]["resources_path"],
                    "images", configdata["filetypes"]["archive"][1]),
                                           memory=True)

        return return_img_attach(os.path.basename(fs_archname),
                                 specific_page.LargeThumb)
    elif thumbsize == "medium":
        if not specific_page.MediumThumb:
#                print("Creating Med Thumb for %s" % os.path.basename(fs_path))
            try:
                specific_page.MediumThumb = cr_tnail_img(im_data,
                                                        sizes[thumbsize],
                                                        fext=fext)
                specific_page.save()
            except IOError:
                im_data = return_image_obj(os.path.join(
                    configdata["locations"]["resources_path"],
                    "images",
                    configdata["filetypes"]["archive"][1]),
                                           memory=True)
        return return_img_attach(os.path.basename(fs_archname),
                                 specific_page.MediumThumb)
    elif thumbsize == "small":
        if not specific_page.SmallThumb:
            try:
                specific_page.SmallThumb = cr_tnail_img(im_data,
                                                        sizes[thumbsize],
                                                        fext=fext)
                specific_page.save()
            except IOError:
                im_data = return_image_obj(os.path.join(
                    configdata["locations"]["resources_path"],
                    "images",
                    configdata["filetypes"]["archive"][1]),
                                           memory=True)
        return return_img_attach(os.path.basename(fs_archname),
                                 specific_page.SmallThumb)
    return return_img_attach(os.path.basename(fs_archname), None)
