"""
Utilities for QuickBBS, the python edition.
"""
# from __future__ import absolute_import, print_function, unicode_literals

import html
import logging
import os
import os.path
import re
import stat
import sys
import time
import urllib.parse
import uuid
from io import BytesIO

# from moviepy.video.io import VideoFileClip
# from moviepy.editor import VideoFileClip #* # import everythings (variables, classes, methods...)
# inside moviepy.editor
import av  # Video Previews
import fitz  # PDF previews
from django.core.exceptions import MultipleObjectsReturned
from pathvalidate import sanitize_filename
from PIL import Image

import frontend.constants as constants
# import filetypes.constants as ftype_constants
import filetypes.models as filetype_models
import frontend.pdf_utilities as pdf_utilities
from frontend.database import check_dup_thumbs  # , validate_database
from quickbbs.models import (Thumbnails_Archives, filetypes, index_data)
from cache.models import fs_Cache_Tracking as Cache_Tracking
import frontend.archives3 as archives
from django.conf import settings
from cache.models import CACHE

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None
# Disable PILLOW DecompressionBombError errors.


def rename_file(old_filename, new_filename):
    try:
        os.rename(old_filename, new_filename)
    except OSError:
        pass


def ensures_endswith(string_to_check, value):
    if not string_to_check.endswith(value):
        string_to_check = f"{string_to_check}{value}"
    return string_to_check


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
    #    print(fs_path[1], type(fs_path))
    extension = os.path.splitext(fs_path)[1].lower()
    # print(fs_path[:20], extension)

    if extension in ("", b"", None):
        extension = ".none"
    if extension == ".pdf":
        results = pdf_utilities.check_pdf(fs_path)
        if results[0] == False:
            pdf_utilities.repair_pdf(fs_path, fs_path)

        pdf_file = fitz.open(fs_path)
        pdf_page = pdf_file.load_page(0)
        #        pix = pdf_page.getPixmap(alpha=True)#matrix=fitz.Identity, alpha=True)
        pix = pdf_page.get_pixmap(alpha=True)  # matrix=fitz.Identity, alpha=True)

        try:
            # source_image = Image.open(BytesIO(pix.getPNGData()))
            source_image = Image.open(BytesIO(pix.tobytes()))
        except UserWarning:
            print("UserWarning!")
            source_image = None

    if extension in filetype_models.FILETYPE_DATA:
        if filetype_models.FILETYPE_DATA[extension]["is_movie"]:
            # print(memory)
            with av.open(fs_path) as container:
                stream = container.streams.video[0]
                frame = next(container.decode(stream))
                source_image = frame.to_image()

        elif filetype_models.FILETYPE_DATA[extension]["is_image"]:
            if not memory:
                try:
                    source_image = Image.open(fs_path)
                except OSError:
                    print("Unable to load source file")

            else:
                try:  # fs_path is a byte stream
                    source_image = Image.open(BytesIO(fs_path))
                #                source_image = None
                except OSError:
                    print("IOError")
                    log.debug("PIL was unable to identify as an image file")
                #               source_image = None
                except UserWarning:
                    print("UserWarning!")
    #              source_image = None
    return source_image


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
    fext = fext.lower().strip()
    if not fext.startswith("."):
        fext = f".{fext}"
    #  if ".%s" % fext in ftype_constants._movie:
    if fext in settings.MOVIE_FILE_TYPES:
        fext = ".jpg"

    image_data = BytesIO()
    source_image.thumbnail((size, size), Image.ANTIALIAS)
    try:
        source_image.save(fp=image_data,
                          format="PNG", # Need alpha channel support for icons, etc.
                                    # configdata["filetypes"][fext][2].strip(),
                          optimize=False)
    except OSError:
        source_image = source_image.convert('RGB')
        source_image.save(fp=image_data,
                          format="JPEG",  # configdata["filetypes"][fext][2].strip(),
                          optimize=False
                          )

    image_data.seek(0)
    return image_data.getvalue()


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


def multiple_replace(repl_dict, text):  # , compiled):
    # Create a regular expression  from the dictionary keys

    # For each match, look-up corresponding value in dictionary
    return constants.regex.sub(lambda mo: repl_dict[mo.string[mo.start():mo.end()]], text)


def return_disk_listing(fqpn, enable_rename=False):
    data = {}
    # data_list = []
    loaded = True
    #    webpath = (fqpn.title().replace(settings.ALBUMS_PATH.title(),
    #                                    "")).replace("//", "/")
    for entry in os.scandir(fqpn):
        titlecase = entry.name.title()
        unescaped = html.unescape(titlecase)
        lower_filename = entry.name.lower()
        #        rename = False
        animated = False
        fext = os.path.splitext(lower_filename)[1]
        if fext == "":
            fext = ".none"
        elif entry.is_dir():
            fext = ".dir"

        if fext not in filetype_models.FILETYPE_DATA:
            continue
        elif (fext in settings.EXTENSIONS_TO_IGNORE) or \
                (lower_filename in settings.FILES_TO_IGNORE):
            continue

        elif settings.IGNORE_DOT_FILES and lower_filename.startswith("."):
            continue

        if enable_rename:
            original_filename = titlecase
            if titlecase != unescaped:
                titlecase = unescaped.title()

            after_filename = multiple_replace(constants.replacements, lower_filename)  # , regex)
            if after_filename != lower_filename:
                titlecase = after_filename.title()

            titlecase = sanitize_filename(titlecase)
            if titlecase != original_filename:
                rename_file(os.path.join(fqpn, original_filename),
                            os.path.join(fqpn, titlecase))
                print("rejected - %s" % titlecase)
                # loaded = False

        data[titlecase] = {"filename": titlecase,
                           "lower_filename": titlecase.lower(),
                           "path": os.path.join(fqpn, titlecase),
                           'sortname': naturalize(titlecase),
                           'size': entry.stat()[stat.ST_SIZE],
                           'lastmod': entry.stat()[stat.ST_MTIME],
                           'is_dir': entry.is_dir(),  # fext == ".dir",
                           'is_file': not entry.is_dir(),  # fext != ".dir",
                           'is_archive': filetype_models.FILETYPE_DATA[fext]["is_archive"],
                           'is_image': filetype_models.FILETYPE_DATA[fext]["is_image"],
                           'is_movie': filetype_models.FILETYPE_DATA[fext]["is_movie"],
                           'is_animated': animated
                           }
    return (loaded, data)


# def delete_from_cache_tracking(event):
#     global CACHE
#     if event.is_directory:
#         dirpath = os.path.normpath(event.src_path.title().strip())
#         CACHE.clear_path(path_to_clear=dirpath)
#         if Cache_Tracking.objects.filter(DirName=dirpath).exists():
#             Cache_Tracking.objects.filter(DirName=dirpath).delete()
#             print("\n\n", time.ctime(), " Deleted %s" % dirpath, "\n\n")
# #        else:
# #            print("Does not exist in Cache Tracking %s" % dirpath)

def read_from_disk(dir_to_scan, skippable=True):
    """
    Pass in FQFN, and the database stores the path as the URL path.
    """

    def link_arc_rec(fs_name, webpath, uuid_entry, page=0):
        fname = os.path.basename(fs_name).title()
        try:
            db_entry = Thumbnails_Archives.objects.update_or_create(
                uuid=uuid_entry,
                FilePath=ensures_endswith(webpath, os.sep),
                FileName=fname,
                page=page,
                defaults={"uuid": uuid_entry, "FilePath": ensures_endswith(webpath, os.sep),
                          "FileName": fname, "page": page})[0]
        except MultipleObjectsReturned:
            check_dup_thumbs(uuid_entry, page)
            db_entry = Thumbnails_Archives.objects.update_or_create(
                uuid=uuid_entry,
                FilePath=ensures_endswith(webpath, os.sep),
                FileName=fname,
                page=page,
                defaults={"uuid": uuid_entry, "FilePath": webpath,
                          "FileName": fname, "page": page})[0]
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
    dir_to_scan = ensures_endswith(dir_to_scan.strip().lower(), os.sep)
    fqpn = (settings.ALBUMS_PATH + dir_to_scan).replace("//", "/")
    if not os.path.exists(fqpn):
        print("%s does not exist" % fqpn)
        return None

    webpath = fqpn.lower().replace(
        settings.ALBUMS_PATH.lower(),
        "")

    dirpath = os.path.normpath(fqpn.title().strip())
    if Cache_Tracking.objects.filter(DirName=dirpath).count() == 0:
        # The path has not been seen since the Cache Tracking has been enabled
        # (eg Startup, or the entry has been nullified)
        # Add to table, and allow a rescan to occur.
        print("\n\n", "\nSaving, %s to cache tracking\n" % dirpath, "\n\n")
        new_rec = Cache_Tracking(DirName=dirpath, lastscan=time.time())
        new_rec.save()
    #    else:
    #        print("Skipping (%s) due to CT" % dirpath)
    #        # The entry is in the cache table
    #        return webpath.replace(os.sep, r"/")

    #    print("dp", dirpath)
    CACHE.read_path(fqpn)
    CACHE.sanitize_filenames(dirpath, allow_rename=True)  # , quiet=False)
    disk_count = CACHE.return_fileCount(dirpath)
    diskstore = CACHE.extended[dirpath]
    #    print("diskstore",diskstore)
    existing_data = index_data.objects.filter(fqpndirectory=ensures_endswith(dir_to_scan, os.sep),
                                              ignore=False,
                                              delete_pending=False)
    existing_data_size = existing_data.count()

    # Scenarios
    #
    # 1) All files and directories are the same = Nothing needs to be done
    #       - Validate all files

    # 2) More files or directories exist, need to validate existing, and add new files/dirs
    # 3) Less files or directories exist, need to validate existing, and remove non-existant

    if existing_data_size > disk_count:
        print("existing size {}       on disk {}".format(existing_data_size,
                                                     disk_count))
        for entry in existing_data:
            if not entry.name in diskstore:  # name is already title cased
                print("Deleting %s" % entry.name)
                entry.delete()
        skippable = False

    elif disk_count > existing_data_size:
        skippable = False

    if existing_data_size > 0:  # and existing_data_size is not None:
        lastmoded = existing_data.order_by("-lastmod")[0]
        fs_lm_name, fs_lm_value, fs_ls_value = CACHE.return_newest(dirpath)
        if not lastmoded.name == fs_lm_name:
            print("Unable to skip, due to last mod name. fs {} vs C {}, {} - {}".format(
                fs_lm_name, lastmoded.name, CACHE.last_mods[dirpath], lastmoded.id))
            diskstore = CACHE.extended[dirpath]
            skippable = False
        elif lastmoded.lastmod != fs_lm_value:
            print("Unable to skip, due to last mod value")
            skippable = False

    bulk_db_elements = []
    count = 0
    if filetype_models.FILETYPE_DATA == {}:
        try:
            filetype_models.reload_filetypes()
        except KeyError:
            print("Unable to validate or create FileType database table.")
            sys.exit(1)

    for filename, filedata in diskstore.items():
        numdirs = 0
        numfiles = 0
        force_save = False
        disk_data = {filename: filedata}
        animated = False
        if filedata.is_dir():
            fext = ".dir"
        else:
            fext = os.path.splitext(filename)[1].lower()
            if fext == "":
                fext = ".none"
        fs_item = os.path.join(settings.ALBUMS_PATH,
                               webpath[1:],
                               filename)

        if (filedata.is_dir()):
            CACHE.read_path(os.path.join(fqpn, filename))
            numfiles, numdirs = CACHE.return_extended_count(os.path.join(fqpn, filename))

        new_uuid = uuid.uuid4()
        if filetype_models.FILETYPE_DATA[fext]["is_image"] and fext in [".gif"]:
            try:
                animated = Image.open(os.path.join(fqpn, filename)).is_animated
                force_save = True
            except AttributeError:
                print("%s is not an animated GIF" % fext)
        try:
            ind_data, created = index_data.objects.get_or_create(
                name=filename,
                fqpndirectory=webpath,
                ignore=False,
                delete_pending=False,
                defaults={'name': filename,
                          'fqpndirectory': webpath,
                          'sortname': naturalize(filename),
                          'size': filedata.stat().st_size,
                          'lastmod': filedata.stat().st_mtime,
                          'numfiles': numfiles,
                          'numdirs': numdirs,
                          'lastscan': time.time(),
                          'filetype': filetypes(fileext=fext),
                          'is_animated': animated
                          }
            )
        except MultipleObjectsReturned:
            print("Multiple Objects Returned")
            index_data.objects.filter(
                name=filename,
                fqpndirectory=webpath).delete()
            ind_data, created = index_data.objects.get_or_create(
                name=filename,
                fqpndirectory=webpath,
                ignore=False,
                delete_pending=False,
                defaults={'name': filename,
                          'fqpndirectory': webpath,
                          'sortname': naturalize(filename),
                          'size': filedata.stat().st_size,
                          'lastmod': filedata.stat().st_mtime,
                          'numfiles': numfiles,
                          'numdirs': numdirs,
                          'lastscan': time.time(),
                          'filetype': filetypes(fileext=fext),
                          'is_animated': animated
                          }
            )
        if ind_data.filetype == filetypes(fileext=None):
            # print("Updating due to file_ext")
            force_save = True

        #        print(ind_data.filetype.fileext, webpath, filename)
        #        print ("Numdir ", ind_data.numdirs, numdirs)
        #        print("numfiles ", ind_data.numfiles, numfiles)
        if ind_data.filetype.fileext == ".dir":
            subdir_path = os.path.join(webpath, filename)
            if (ind_data.numdirs != numdirs or
                    ind_data.numfiles != numfiles):
                force_save = True
                ind_data.numdirs = numdirs
                ind_data.numfiles = numfiles
                print("Mismatch for subdir - ", webpath, filename)
            if numdirs == -1 and index_data.objects.filter(fqpndirectory=subdir_path,
                                                           filetype__fileext='.dir').exists():  # count() >= 1:
                print("Attempting to delete, dirs from ", subdir_path)
                # index_data.objects.filter(fqpndirectory=subdir_path).filter(ind_data.filetype.fileext=='.dir').delete()

        if ind_data.lastmod != filedata.stat().st_mtime:  # .stat()[stat.ST_MTIME]:
            print(filename, ind_data.lastmod, filedata.stat().st_mtime)
            ind_data.lastmod = filedata.stat().st_mtime
            print("LastMod update", filedata.name)
            force_save = True

        if ind_data.archives is None and ind_data.filetype.is_archive:
            # is archive, link as archive
            ind_data.archives = link_arc_rec(fs_item, webpath, new_uuid)
            force_save = True

            ta_listings = Thumbnails_Archives.objects.filter(uuid=ind_data.uuid)
            if ta_listings.count() != ind_data.count_subfiles:
                archive_file = archives.id_cfile_by_sig(os.path.join(settings.ALBUMS_PATH,
                                                                     webpath[1:],
                                                                     filename))
                archive_file.get_listings()
                ind_data.count_subfiles = ta_listings.count()
                for zipcount, entry in enumerate(archive_file.listings):
                    if not ta_listings.filter(page=zipcount).exists():
                        Thumbnails_Archives.objects.create(uuid=ind_data.uuid,
                                                           FileName=filename,  # .replace("#",""),
                                                           FilePath=webpath,
                                                           page=zipcount,
                                                           FileSize=-1)

        if created or ind_data.uuid is None:
            ind_data.uuid = new_uuid
            force_save = True

        if force_save:
            #            print("Force saving")
            ind_data.save()
            # bulk_db_elements.append(ind_data)

        if ind_data.filetype.is_image and skippable:
            # if ftypes.FILETYPE_DATA[fext]["is_image"] and skippable:
            #
            # Create up to the first image record (eg. Directory thumbnail) and then
            # break.
            print("Skippable, Image Break")
            break
    return webpath.replace(os.sep, r"/")


def break_down_urls(uri_path):
    path = urllib.parse.urlsplit(uri_path).path
    return path.split('/')


def return_breadcrumbs(uri_path=""):  # , crumbsize=3):
    uris = break_down_urls(uri_path)
    data = []
    for count in range(1, len(uris)):
        name = uris[count].split("/")[-1]
        url = "/".join(uris[0:count + 1])
        if name == "":
            continue
        data.append([name, url, f"<a href='{url}'>{name}</a>"])
    return data


#     from frontend.config import configdata, load_data
#     cfg_path = os.path.abspath(r"../../cfg")
#     config.load_data(os.path.join(cfg_path, "paths.ini"))
#     config.load_data(os.path.join(cfg_path, "settings.ini"))
#     config.load_data(os.path.join(cfg_path, "filetypes.ini"))
#     import doctest
#     doctest.testmod()
#from frontend.config import configdata

