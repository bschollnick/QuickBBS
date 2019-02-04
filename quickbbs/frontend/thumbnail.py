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
from frontend.web import return_img_attach, g_option, respond_as_attachment
from quickbbs.models import (index_data,
                             #Thumbnails_Dirs,
                             Thumbnails_Files,
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

    #   What files exist in this directory?
    filters = {'fqpndirectory':webpath.lower(), 'is_dir':False,
               'ignore':False, 'delete_pending':False}
    files = get_xth_image(database, 0, filters)
    if files is None:
        # No files exist in the database for this directory
        print("* scanning due to No files exist, %s" % webpath)
        read_from_disk(webpath, skippable=True)
        # process_dir
        files = get_xth_image(database, 0, filters)
    return files

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
    imagedata = None
    if db_index.directory.SmallThumb != b'':
        # Does the thumbnail exist?
        if db_index.size == db_index.directory.FileSize:
            # If cache is valid, send it.
            return return_img_attach(db_index.name, db_index.directory.SmallThumb.tobytes())

        #   The cached data is invalidated since the filesize is
        #   inaccurate.
        #   Reset the existing thumbnails to ensure that they will be
        #   regenerated
        print("size mismatch, %s - %s" % (db_index.directory.FileSize,
                                               db_index.name))

        db_index.directory.FileSize = -1
        db_index.directory.SmallThumb = b""

    files = images_in_dir(index_data,
                          os.path.join(db_index.fqpndirectory,
                                       db_index.name).lower())

    if files: # found an file in the directory to use for thumbnail purposes
        #print ("Files found in directory")
        fs_d_fname = configdata["locations"]["albums_path"] +\
                    os.path.join(db_index.fqpndirectory.lower(),
                                 db_index.name, files.name)
                 # file system location of directory
        fext = os.path.splitext(files.name)[1][1:].lower()

        temp = cr_tnail_img(return_image_obj(fs_d_fname),
                            sizes["small"],
                            fext=fext)
        imagedata = temp
        db_index.directory.SmallThumb = temp
        db_index.directory.FileSize = db_index.size
        #print("Set size to %s for %s" % (db_index.directory.FileSize,
        #                                 fs_d_fname))
#        db_index.directory.save()
#        db_index.save()
#        return return_img_attach(db_index.name, db_index.directory.SmallThumb)
    else:
        #
        #   There are no files in the directory
        #
        temp = return_image_obj(configdata["locations"]["images_path"]+\
                                os.sep + configdata["filetypes"]["dir"][1])
#            if db_index.size != os.path.getsize(temp):
        img_icon = cr_tnail_img(temp, sizes["small"],
                                configdata["filetypes"]["dir"][2])
        db_index.directory.SmallThumb = img_icon
        db_index.directory.FileSize = db_index.size
#            print("Set size to %s for %s" % (db_index.directory.FileSize,
#                                             fs_d_fname))
    db_index.directory.save()
    db_index.save()
    return return_img_attach(db_index.name, db_index.directory.SmallThumb)

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
    thumb_size = g_option(request, "size", "Small").title()

    existing_data = getattr(entry.file_tnail, "%sThumb" % thumb_size)
    if existing_data != b'':
        # Does the thumbnail exist?
        if entry.size == entry.file_tnail.FileSize:
            # If cache is valid, send it.
            return return_img_attach(entry.name, existing_data.tobytes())


    fs_fname = configdata["locations"]["albums_path"] +\
                os.path.join(entry.fqpndirectory.lower(),
                             entry.name)
    fs_fname = fs_fname.replace("//", "/")
             # file system location of directory

    fext = os.path.splitext(fs_fname)[1][1:].lower()
    imagedata = None
    entry.file_tnail.FileSize = -1
    entry.file_tnail.SmallThumb = b""
    entry.file_tnail.MediumThumb = b""
    entry.file_tnail.LargeThumb = b""

# https://stackoverflow.com/questions/1167398/python-access-class-property-from-string
    temp = return_image_obj(fs_fname)
    setattr(entry.file_tnail,
            "%sThumb" % thumb_size, cr_tnail_img(temp,
                                                 sizes[thumb_size.lower()],
                                                 fext=fext)
            )
    entry.file_tnail.FileSize = entry.size
    entry.file_tnail.save()
    entry.save()
    imagedata = getattr(entry.file_tnail, "%sThumb" % thumb_size)
    return return_img_attach(entry.name, imagedata)

def new_process_archive(ind_entry, request, page=0):
    """
    Process an archive, and return the thumbnail
    """
    thumbsize = g_option(request, "size", "small").lower().strip()
    fs_archname = configdata["locations"]["albums_path"] +\
                os.path.join(ind_entry.fqpndirectory.lower(),
                             ind_entry.name)
    fs_archname = fs_archname.replace("//", "/").strip()

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

#    print ("fs archname: ",fs_archname)
    archive_file = archives.id_cfile_by_sig(fs_archname)
    archive_file.get_listings()
    fn_to_extract = archive_file.listings[page][0]
#    print (fn_to_extract, page)
    fext = os.path.splitext(fn_to_extract)[1][1:].lower()
    data = archive_file.extract_mem_file(fn_to_extract)
    im_data = return_image_obj(data, memory=True)
    if im_data == None:
        #
        # Add Caching
        #
        return return_img_attach(os.path.basename(
            configdata["filetypes"]["dir"][1]), "1431973824_compressed.png")

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
        if specific_page.LargeThumb == b"":
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
        else:
            return return_img_attach(os.path.basename(fs_archname),
                                     specific_page.LargeThumb.tobytes())
    elif thumbsize == "medium":
        if specific_page.MediumThumb == b"":
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
            return_img_attach(os.path.basename(fs_archname),
                              specific_page.MediumThumb)
        else:
            return return_img_attach(os.path.basename(fs_archname),
                                     specific_page.MediumThumb.tobytes())
    elif thumbsize == "small":
        if specific_page.SmallThumb == b"":
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
        else:
            return return_img_attach(os.path.basename(fs_archname),
                                     specific_page.SmallThumb.tobytes())
    return return_img_attach(os.path.basename(fs_archname), None)
