"""
Thumbnail routines for QuickBBS
"""
import os
#import sys

import frontend.archives3 as archives
from frontend.config import configdata as configdata
#from frontend.serve_up import resources
from frontend.utilities import (cr_tnail_img, get_xth_image,
                                return_image_obj, return_img_attach,
                                g_option)
#import utilities
from utilities import read_from_disk
from quickbbs.models import (index_data,
                             Thumbnails_Dirs,
                             Thumbnails_Files,
                             Thumbnails_Archives)

sizes = {
    "small":configdata["configuration"]["small"],
    "medium":configdata["configuration"]["medium"],
    "large":configdata["configuration"]["large"],
    "unknown":configdata["configuration"]["small"]
}

def images_in_dir(database, webpath):
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
        if entry.directory is None:
            # The directory entry does not exist
            entry.directory = Thumbnails_Dirs.objects.create(
                uuid=entry.uuid, FilePath=entry.fqpndirectory.lower())
            entry.directory.save()
            entry.save()

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
            #
            #   The cached data is invalidated since the filesize is
            #   inaccurate.
            #   Reset the existing thumbnails to ensure that they will be
            #   regenerated
            #
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

    if not entry.file_tnail:
        # The file thumbnail entry does not exist
#            print("Creating tnail record")
        entry.file_tnail = Thumbnails_Files.objects.create(
            uuid=entry.uuid, FilePath=entry.fqpndirectory.lower(),
            FileName=entry.name)
        entry.save()

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

def new_process_archive(entry, request):
    """
    Process an archive, and return the thumbnail
    """
#        compressed_file = configdata["locations"]["resources_path"] + \
#            os.sep + "images" + os.sep + "1431973824_compressed.png"

    thumbsize = g_option(request, "size", "small").lower().strip()
    fs_archname = configdata["locations"]["albums_path"] +\
                os.path.join(entry.fqpndirectory.lower(),
                             entry.name)
    fs_archname = fs_archname.replace("//", "/")
#        print("archive - %s" % fs_fname)

             # file system location of directory

    archive_file = archives.id_cfile_by_sig(fs_archname)
    archive_file.get_listings()
    page = int(g_option(request, "arch", 0))
    if page == "":
        page = 0
    fn_to_extract = archive_file.listings[page]
    data = archive_file.extract_mem_file(fn_to_extract)
    if not entry.archives:
        # The file thumbnail entry does not exist
        entry.archives = Thumbnails_Archives.objects.create(
            uuid=entry.uuid, FilePath=entry.fqpndirectory.lower(),
            FileName=entry.name, page=page)
        entry.archives.save()

    if entry.archives.FileSize != os.path.getsize(fs_archname):
        #
        #   The cached data is invalidated since the filesize is inaccurate
        #   Reset the existing thumbnails to ensure that they will be
        #   regenerated
        #
        entry.archives.SmallThumb = b""
        entry.archives.MediumThumb = b""
        entry.archives.LargeThumb = b""
        entry.archives.FileSize = os.path.getsize(fs_archname)
        entry.archives.save()
        #
        #  Clear the django cache here

    fext = os.path.splitext(archive_file.listings[page])[1][1:].lower()
                                   # ".pdf_png_preview")

#        if fext in configdata["filetypes"]:
#            if configdata["filetypes"][fext][1].strip() != "None":
#                fs_path = os.path.join(
#                    configdata["locations"]["resources_path"],
#                    "images",
#                    configdata["filetypes"][fext][1])

    if thumbsize == "large":
        if not entry.archives.LargeThumb:
            try:
                im_data = return_image_obj(data, memory=True)
            except IOError:
                im_data = return_image_obj(os.path.join(
                    configdata["locations"]["resources_path"],
                    "images", configdata["filetypes"]["archive"][1]),
                                           memory=True)

            entry.archives.LargeThumb = cr_tnail_img(im_data,
                                                     sizes[thumbsize],
                                                     fext=fext)
            entry.archives.save()
        return return_img_attach(os.path.basename(fs_archname),
                                 entry.archives.LargeThumb)
    elif thumbsize == "medium":
        if not entry.archives.MediumThumb:
#                print("Creating Med Thumb for %s" % os.path.basename(fs_path))
            try:
                im_data = return_image_obj(data, memory=True)
            except IOError:
                im_data = return_image_obj(os.path.join(
                    configdata["locations"]["resources_path"],
                    "images",
                    configdata["filetypes"]["archive"][1]),
                                           memory=True)
            entry.archives.MediumThumb = cr_tnail_img(im_data,
                                                      sizes[thumbsize],
                                                      fext=fext)
            entry.archives.save()
        return return_img_attach(os.path.basename(fs_archname),
                                 entry.archives.MediumThumb)
    elif thumbsize == "small":
        if not entry.archives.SmallThumb:
#                print("Creating Small Thumb for %s" %
#                        os.path.basename(fs_path))
            try:
                im_data = return_image_obj(data, memory=True)
            except IOError:
                im_data = return_image_obj(os.path.join(
                    configdata["locations"]["resources_path"],
                    "images",
                    configdata["filetypes"]["archive"][1]),
                                           memory=True)
            entry.archives.SmallThumb = cr_tnail_img(im_data,
                                                     sizes[thumbsize],
                                                     fext=fext)
            entry.archives.save()
        return return_img_attach(os.path.basename(fs_archname),
                                 entry.archives.SmallThumb)

    return return_img_attach(os.path.basename(fs_archname), None)
