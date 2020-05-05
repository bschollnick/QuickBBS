# coding: utf-8
"""
Utilities for QuickBBS, the python edition.
"""
from __future__ import absolute_import, print_function, unicode_literals

import os
import os.path
from io import BytesIO
import uuid
#import urllib
import re
import stat
import sys
import time
import html

from PIL import Image
import frontend.constants as constants
import fitz
from pathvalidate import sanitize_filename

import frontend
import frontend.ftypes as ftypes
from frontend.database import check_dup_thumbs
from frontend.database import (validate_database)
from quickbbs.models import (index_data, Thumbnails_Files, Thumbnails_Archives,
                             Thumbnails_Dirs, filetypes)
import frontend.pdf_utilities as pdf_utilities
from django.core.exceptions import MultipleObjectsReturned
from django.db import transaction
#from constants import *
import logging
log = logging.getLogger(__name__)

import frontend.archives3 as archives
import quickbbs.settings
from frontend.cached_exists import cached_exist

CACHE = cached_exist(use_modify=True, use_extended=True, use_filtering=True)
CACHE.IgnoreDotFiles = True
CACHE.FilesOnly = False
CACHE.AcceptableExtensions = list(ftypes.get_ftype_dict())
CACHE.AcceptableExtensions.append("")


if quickbbs.settings.SILK:
    from silk.profiling.profiler import silk_profile

Image.MAX_IMAGE_PIXELS = None
# Disable PILLOW DecompressionBombError errors.

#@silk_profile(name='utilities.rename_file')
def rename_file(old_filename, new_filename):
    try:
        os.rename(old_filename, new_filename)
    except OSError:
        pass

# @silk_profile(name='utilities.get_lastmod in dir')
# def get_lm_in_dir(fqpn):
#     """
#     return the directory listing in reverse last modified (oldest -> Newest)
#     as list of scandir items.
#     """
#     lastmod_list = sorted(os.scandir(fqpn),
#                           key=lambda x: x.stat().st_mtime,
#                           reverse=True)
#     for data in lastmod_list:
#         if not data.name.startswith("."):
#             return data.name.title()

#@silk_profile(name='utilities.ensures_endswith')
def ensures_endswith(string_to_check, value):
    if not string_to_check.endswith(value):
        string_to_check = "%s%s" % (string_to_check, value)
    return string_to_check

#@silk_profile(name='utilities.sort_order')
def sort_order(request, context):
    """
    Grab the sort order from the request (cookie)
    and apply it to the session, and to the context for the web page.

    Args:
        request (obj) - The request object
        context (dict) - The dictionary for the web page template

    Returns:
        obj::
            The request object
        dict::
            The context dictionary

    Raises:
        None

    Examples
    --------
    """
    context["sort"] = int(request.GET.get("sort", default=0))
    return request, context


#@silk_profile(name='utilities.is_valid_uuid')
def is_valid_uuid(uuid_to_test, version=4):
    """
    Check if uuid_to_test is a valid UUID.
    https://stackoverflow.com/questions/19989481

    Args:
        uuid_to_test (str) - UUID code to validate
        version (int) - UUID version to validate against (eg  1, 2, 3, 4)

    Returns:
        boolean::
            `True` if uuid_to_test is a valid UUID, otherwise `False`.

    Raises:
        None

    Examples
    --------
    >>> is_valid_uuid('c9bf9e57-1685-4c89-bafb-ff5af830be8a')
    True
    >>> is_valid_uuid('c9bf9e58')
    False
    """
    try:
        uuid_obj = uuid.UUID(uuid_to_test, version=version)
    except:
        return False

    return str(uuid_obj) == uuid_to_test


#@silk_profile(name='utilities.test_extension')
def test_extension(name, ext_list):
    """
    Check if filename has an file extension that is in passed list.

    Args:
        name (str): The Filename to examine
        ext_list (list): ['zip', 'rar', etc] # list of file extensions (w/o .),
            lowercase.

    Returns:
        boolean::
            `True` if name does match an extension passed, otherwise `False`.

    Raises:
        None

    Examples
    --------
    >>> test_extension("test.zip", ['zip', 'cbz'])
    True
    >>> test_extension("test.rar", ['zip', 'cbz'])
    False

    """
    return os.path.splitext(name)[1].lower() in ext_list

# @silk_profile(name='utilities.is_archive')
# def is_archive(fqfn):
#   None = not an archive.
#   """
#   Check if filename has an file extension that in the archive file types list
#
#   Args:
#       fqfn (str): Filename of the file
#
#   Returns:
#       boolean::
#           `True` if name does match an extension in the archive_fts
#           (archive filetypes) list.  Otherwise return none.
#
#   Raises:
#       None
#
#   Examples
#   --------
#   >>> is_archive("test.zip")
#   True
#   >>> is_archive("test.jpg")
#   False
#
#   """
#   return test_extension(fqfn, configdata["filetypes"]["archive_fts"])


#@silk_profile(name='utilities.return_image_object')
def return_image_obj(fs_path, memory=False):
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
    if os.path.splitext(fs_path)[1][1:].lower() == u"pdf":
        results = pdf_utilities.check_pdf(fs_path)
        if results[0] == False:
            pdf_utilities.repair_pdf(fs_path, fs_path)

        pdf_file = fitz.open(fs_path)
        pdf_page = pdf_file.loadPage(0)
        pix = pdf_page.getPixmap(alpha=True)#matrix=fitz.Identity, alpha=True)

        try:
            source_image = Image.open(BytesIO(pix.getPNGData()))
        except UserWarning:
            print("UserWarning!")
            source_image = None
    else:
        if not memory:
            source_image = Image.open(fs_path)
        else:
            try:# fs_path is a byte stream
                source_image = Image.open(BytesIO(fs_path))
            except IOError:
                print("IOError")
                log.debug("PIL was unable to identify as an image file")
            except UserWarning:
                print("UserWarning!")
                source_image = None
    return source_image

#@silk_profile(name='utilities.cr_tnail_img')
def cr_tnail_img(source_image, size, fext):
    """
    Given the PILLOW object, resize the image to <SIZE>
    and return the saved version of the file (using FEXT
    as the format to save as [eg. PNG])

    Return the binary representation of the file that
    was saved to memory
    """
    if source_image == None:
        return None

    image_data = BytesIO()
    source_image.thumbnail((size, size), Image.ANTIALIAS)
    try:
        source_image.save(fp=image_data,
                          format=configdata["filetypes"][fext][2].strip(),
                          optimize=True)
    except IOError:
        source_image = source_image.convert('RGB')
        source_image.save(fp=image_data,
                          format="JPEG",#configdata["filetypes"][fext][2].strip(),
                          optimize=True
                          )

    image_data.seek(0)
    return image_data.getvalue()


#@silk_profile(name='utilities.naturalize')
def naturalize(string):
    """
        return <STRING> as a english sortable <STRING>
    """
    def naturalize_int_match(match):
        """ reformat as a human sortable number
        """
        return '%08d' % (int(match.group(0)),)

    string = string.lower().strip()
    string = re.sub(r'^the\s+', '', string)
    string = re.sub(r'\d+', naturalize_int_match, string)
    return string


#@silk_profile(name='utilities.multiple_replace')
def multiple_replace(dict, text):#, compiled):
    # Create a regular expression  from the dictionary keys

    # For each match, look-up corresponding value in dictionary
    return constants.regex.sub(lambda mo: dict[mo.string[mo.start():mo.end()]], text)

#@silk_profile(name='utilities.return_disk_listing')
def return_disk_listing(fqpn, enable_rename=False):

    data = {}
    data_list = []
    loaded = True
    webpath = (fqpn.lower().replace(configdata["locations"]["albums_path"].lower(),
                                    "")).replace("//", "/")
    for entry in os.scandir(fqpn):
        titlecase = entry.name.title()
        unescaped = html.unescape(titlecase)
        lower_filename = entry.name.lower()
        rename = False
        animated = False
        fext = os.path.splitext(lower_filename)[1]
        if fext == "":
            fext = ".none"
        elif entry.is_dir():
            fext = ".dir"

        if fext not in ftypes.FILETYPE_DATA:
            continue
        elif (fext in configdata["filetypes"]["extensions_to_ignore"]) or\
           (lower_filename in configdata["filetypes"]["files_to_ignore"]):
            continue

        elif configdata["filetypes"]["ignore_dotfiles"] and lower_filename.startswith("."):
            continue

        if enable_rename:
            original_filename = titlecase
            if titlecase != unescaped:
                titlecase = unescaped.title()

            after_filename = multiple_replace(constants.replacements, lower_filename)#, regex)
            if after_filename != lower_filename:
                titlecase = after_filename.title()

            titlecase = sanitize_filename(titlecase)
            if titlecase != original_filename:
                rename_file(os.path.join(fqpn, original_filename),
                            os.path.join(fqpn, titlecase))
                print("rejected - %s" % titlecase)
                loaded = False

            data[titlecase] = {"filename":titlecase,
                               "lower_filename":titlecase.lower(),
                               "path":os.path.join(fqpn, titlecase),
                               'sortname':naturalize(titlecase),
                               'size':entry.stat()[stat.ST_SIZE],
                               'lastmod':entry.stat()[stat.ST_MTIME],
                               'is_dir':entry.is_dir(),#fext == ".dir",
                               'is_file':not entry.is_dir(),#fext != ".dir",
                               'is_archive':ftypes.FILETYPE_DATA[fext]["is_archive"],
                               'is_image':ftypes.FILETYPE_DATA[fext]["is_image"],
                               'is_animated':animated
                               }
    return (loaded, data)

#@silk_profile(name='utilities.read_From_disk')
def read_from_disk(dir_to_scan, skippable=True):
    """
    Pass in FQFN, and the database stores the path as the URL path.
    """

#     def recovery_from_multiple(fqpndirectory, uname):
#         """
#         eliminate any duplicates
#         """
#         dataset = index_data.objects.filter(
#             name=uname.title(), fqpndirectory=fqpndirectory.lower(),
#             ignore=False)
#         dataset.delete()

    #@silk_profile(name='utilities.link_arch_rec')
    def link_arc_rec(fs_name, webpath, uuid_entry, page=0):
        fname = os.path.basename(fs_name).title()
        try:
            db_entry = Thumbnails_Archives.objects.update_or_create(
                uuid=uuid_entry,
                FilePath=webpath,
                FileName=fname,
                page=page,
                defaults={"uuid":uuid_entry, "FilePath":webpath,
                          "FileName":fname, "page":page})[0]
        except MultipleObjectsReturned:
            check_dup_thumbs(uuid_entry, page)
            db_entry = Thumbnails_Archives.objects.update_or_create(
                uuid=uuid_entry,
                FilePath=webpath,
                FileName=fname,
                page=page,
                defaults={"uuid":uuid_entry, "FilePath":webpath,
                          "FileName":fname, "page":page})[0]
        return db_entry

    #@silk_profile(name='utilities.link_dir_rec')
    def link_dir_rec(sd_entry, webpath, uuid_entry):
        fs_name = os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               sd_entry[filename]["filename"])
        fname = os.path.basename(fs_name).title()
        db_entry = Thumbnails_Dirs.objects.update_or_create(
            uuid=uuid_entry, FilePath=webpath, DirName=fname,
            defaults={"uuid":uuid_entry,
                      "FilePath":webpath,
                      "DirName":fname})[0]
        return db_entry

    #@silk_profile(name='utilities.link_file_rec')
    def link_file_rec(sd_entry, webpath, uuid_entry):
        fs_name = os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               sd_entry[filename]["filename"])#.name)
        fname = os.path.basename(fs_name).title()

        db_entry = Thumbnails_Files.objects.update_or_create(
            uuid=uuid_entry,
            FilePath=webpath,
            FileName=fname,
            defaults={"uuid":uuid_entry,
                      "FilePath":webpath,
                      "FileName":fname,
                     })[0]
        return db_entry

###############################
    # Read_from_disk - main
    #
    # rewrite to use update_or_create? - No the logic doesn't work.

    # Get_or_create, could work for the read_from_disk main.

    # get all the filenames, and pass into update.

    # so that update can if not filename in listing, to check for deleted files.
    global CACHE
    lastmoded = ""
    dir_to_scan = dir_to_scan.strip().lower()
    fqpn = (configdata["locations"]["albums_path"] + dir_to_scan).replace("//", "/")
    if not os.path.exists(fqpn):
        print("%s does not exist" % fqpn)
        return None

    webpath = fqpn.lower().replace(
        configdata["locations"]["albums_path"].lower(),
        "")

    dirpath = os.path.normpath(fqpn.lower().strip())
#   count = 0
#   loaded = False
#   while not loaded:
#       try:
#           loaded, diskstore = return_disk_listing(fqpn, enable_rename=True)
#           disk_count = len(diskstore)
#       except StopIteration:
#           pass
#       count += 1
#       if count > 5:
#           return None
#   # existing_data is from the database
    CACHE.read_path(fqpn)
    CACHE.sanitize_filenames(dirpath, quiet=False)
    disk_count = CACHE.return_fileCount(dirpath)
    diskstore = CACHE.extended[dirpath]
    existing_data = index_data.objects.filter(fqpndirectory=dir_to_scan,
                                              ignore=False,
                                              delete_pending=False)
    existing_data_size = existing_data.count()

    if existing_data_size > disk_count:
        print("existing size %s       on disk %s" % (existing_data_size,
                                                     disk_count))
        for entry in existing_data:
            if not entry.name in diskstore:    # name is already title cased
                print("Deleting %s" % entry.name)
                entry.delete()
        skippable = False

    elif disk_count > existing_data_size:
        skippable = False

    if existing_data_size > 0:# and existing_data_size is not None:
#        try:
            lastmoded = existing_data.order_by("-lastmod")[0]
            fs_lm_name, fs_lm_value = CACHE.last_mods[dirpath]
            if not lastmoded.name == fs_lm_name:
                print("Unable to skip, due to last mod name. %s vs %s" % (fs_lm_name, lastmoded.name))
                skippable = False
            elif lastmoded.lastmod != fs_lm_value:
                print("Unable to skip, due to last mod value")
                skippable = False

    if skippable:
        #
        #   We appear to be completely up to date, without reading from disk.
        #   So skip.
        return webpath.replace(os.sep, r"/")

    bulk_db_elements = []
    count = 0
    for filename, filedata in diskstore.items():
        numdirs = 0
        numfiles = 0
        force_save = False
        disk_data = {}
        disk_data[filename] = filedata#filedata
        animated = False
        if filedata.is_dir():
            fext = ".dir"
        else:
            fext = os.path.splitext(filename)[1].lower()
            if fext == "":
                fext = ".none"
        fs_item = os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               filename)

        if (filedata.is_dir()):
            CACHE.read_path(os.path.join(fqpn, filename))
            numfiles, numdirs = CACHE.return_extended_count(os.path.join(fqpn, filename))

        new_uuid = uuid.uuid4()
        if ftypes.FILETYPE_DATA[fext]["is_image"] and fext in [".gif"]:
            try:
                animated = Image.open(os.path.join(fqpn, filename)).is_animated
                force_save = True
            except AttributeError:
                print("%s is not an animated GIF" % fext)
        try:
            #ind_data, created = index_data.objects.update_or_create(
            ind_data, created = index_data.objects.get_or_create(
                name=filename,
                fqpndirectory=webpath,
                ignore=False,
                delete_pending=False,
                defaults={'name':filename,
                          'fqpndirectory':webpath,
                          'sortname':naturalize(filename),
                          'size':filedata.stat().st_size,
                          'lastmod':filedata.stat().st_mtime,
                          'numfiles':numfiles,
                          'numdirs':numdirs,
                          #'is_dir':disk_data[filename]["is_dir"],
                          #'is_archive':disk_data[filename]["is_archive"],
                          #'is_image':ftypes.FILETYPE_DATA[fext]["is_image"],
                          #'is_pdf':ftypes.FILETYPE_DATA[fext]["is_pdf"],
                          'lastscan':time.time(),
                          'filetype':filetypes(fileext=fext),
                          'is_animated':animated
                          }
                )
        except MultipleObjectsReturned:
            print("Multiple Objects Returned")
            index_data.objects.filter(
                name=filename,
                fqpndirectory=webpath).delete()
#            ind_data, created = index_data.objects.update_or_create(
            ind_data, created = index_data.objects.get_or_create(
                name=filename,
                fqpndirectory=webpath,
                ignore=False,
                delete_pending=False,
                defaults={'name':filename,
                          'fqpndirectory':webpath,
                          'sortname':naturalize(filename),
                          'size':filedata.stat().st_size,
                          'lastmod':filedata.stat().st_mtime,
                          'numfiles':numfiles,
                          'numdirs':numdirs,
#                         'is_dir':disk_data[filename]["is_dir"],
#                         'is_archive':disk_data[filename]["is_archive"],
#                         'is_image':ftypes.FILETYPE_DATA[fext]["is_image"],
#                         'is_pdf':ftypes.FILETYPE_DATA[fext]["is_pdf"],
                          'lastscan':time.time(),
                          'filetype':filetypes(fileext=fext),
                          'is_animated':animated
                          }
                )
        if ind_data.filetype == filetypes(fileext=None):
            #print("Updating due to file_ext")
            force_save = True

        if ind_data.filetype.fileext == ".dir":
            if (ind_data.numdirs != numdirs or
                ind_data.numfiles != numfiles):
                force_save = True
                ind_data.numdirs = numdirs
                ind_data.numfiles = numfiles

        if ind_data.lastmod != filedata.stat().st_mtime:#.stat()[stat.ST_MTIME]:
            ind_data.lastmod = filedata.stat().st_mtime
            #print("LastMod update")
            force_save = True

#        print("file_tnail is %s" % disk_data.name)
#        print(fext)

        #if ind_data.archives is None and ftypes.FILETYPE_DATA[fext]["is_archive"]:
        if ind_data.archives is None and ind_data.filetype.is_archive:
            # is archive, link as archive
            ind_data.archives = link_arc_rec(fs_item, webpath, new_uuid)
            force_save = True

            ta_listings = Thumbnails_Archives.objects.filter(uuid=ind_data.uuid)
            if ta_listings.count() != ind_data.count_subfiles:
                print("Checking")
                archive_file = archives.id_cfile_by_sig(os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               filename))
                archive_file.get_listings()
                ind_data.count_subfiles = ta_listings.count()
                for zipcount, entry in enumerate(archive_file.listings):
                    if not ta_listings.filter(page = zipcount).exists():
                        Thumbnails_Archives.objects.create(uuid = ind_data.uuid,
                            FileName = filename,#.replace("#",""),
                            FilePath = webpath,
                            page = zipcount,
                            FileSize = -1)

        if created or ind_data.uuid is None:
            ind_data.uuid = new_uuid
            force_save = True


        if force_save:
#            print("Force saving")
            ind_data.save()
            #bulk_db_elements.append(ind_data)

        if ind_data.filetype.is_image and skippable:
            #if ftypes.FILETYPE_DATA[fext]["is_image"] and skippable:
            #
            # Create up to the first image record (eg. Directory thumbnail) and then
            # break.
            break
    return webpath.replace(os.sep, r"/")


if __name__ == '__main__':
    from config import configdata, load_data
    cfg_path = os.path.abspath(r"../../cfg")
    config.load_data(os.path.join(cfg_path, "paths.ini"))
    config.load_data(os.path.join(cfg_path, "settings.ini"))
    config.load_data(os.path.join(cfg_path, "filetypes.ini"))
    import doctest
    doctest.testmod()
else:
    from frontend.config import configdata
    print(sys.version)
