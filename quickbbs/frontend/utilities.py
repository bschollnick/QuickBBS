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
from pathlib import Path

# from moviepy.video.io import VideoFileClip
# from moviepy.editor import VideoFileClip #* # import everythings (variables, classes, methods...)
# inside moviepy.editor
import av  # Video Previews
import fitz  # PDF previews
from django.conf import settings
from pathvalidate import sanitize_filename
from PIL import Image
import filetypes.models as filetype_models
from cache.models import fs_Cache_Tracking as Cache_Tracking
from quickbbs.models import Thumbnails_Archives, filetypes, index_data

import frontend.archives3 as archives
import frontend.constants as constants

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None


# Disable PILLOW DecompressionBombError errors.


def rename_file(old_filename, new_filename):
    """
    Wrapper function for renaming files.

    Args
        old_filename (str) : The original filename
        new_filename (str) : The new filename to rename

    """
    try:
        os.rename(old_filename, new_filename)
    except OSError:
        pass


def ensures_endswith(string_to_check, value):
    """
    Check the string (string_to_check) to see if value is the last character in string_to_check.
    If not, then add it to the end of the string.

    Args:
        string_to_check (str): The source string to process
        value (str): The string to check against, and to add to the end of the string
            if it doesn't already exist.

    Returns
    -------
        str : the potentially changed string
    """
    if not string_to_check.endswith(value):
        string_to_check = f"{string_to_check}{value}"
    return string_to_check


def sort_order(request):
    """
    Grab the sort order from the request (cookie)
    and apply it to the session, and to the context for the web page.

    Args:
        request (obj) - The request object

    Returns:
        int::
            The sort value from the request, or 0 if not supplied in the request.

    Raises:
        None

    Examples
    --------
    """
    return int(request.GET.get("sort", default=0))


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
        uuid_obj = str(uuid.UUID(uuid_to_test, version=version))
    except ValueError:
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
    extension = os.path.splitext(fs_path)[1].lower()

    if extension in ("", b"", None):
        # There is currently no concept of a "None" in filetypes
        extension = ".none"
    if filetype_models.FILETYPE_DATA[extension]["is_pdf"]:
        # Do not repair the PDF / validate the PDF.  If it's bad,
        # it should be repaired, not band-aided by a patch from the web server.
        # results = pdf_utilities.check_pdf(fs_path)
        # if results[0] is False:
        #    pdf_utilities.repair_pdf(fs_path, fs_path)
        with fitz.open(fs_path) as pdf_file:
            # pdf_file = fitz.open(fs_path)
            pdf_page = pdf_file.load_page(0)
            pix = pdf_page.get_pixmap(alpha=True)  # matrix=fitz.Identity, alpha=True)

            try:
                source_image = Image.open(BytesIO(pix.tobytes()))
            except UserWarning:
                print("UserWarning!")
                source_image = None

    elif filetype_models.FILETYPE_DATA[extension]["is_movie"]:
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
    if filetype_models.FILETYPE_DATA[extension]["is_movie"]:
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
    #  if ".%s" % fext in ftype_constants._movie:
    if fext in settings.MOVIE_FILE_TYPES:
        fext = ".jpg"

    image_data = BytesIO()
    source_image.thumbnail((size, size), Image.ANTIALIAS)
    try:
        source_image.save(fp=image_data,
                          format="PNG",  # Need alpha channel support for icons, etc.
                          optimize=False)
    except OSError:
        source_image = source_image.convert('RGB')
        source_image.save(fp=image_data,
                          format="JPEG",
                          optimize=False
                          )
    image_data.seek(0)
    return image_data.getvalue()


def naturalize(string):
    """
        return <STRING> as a english sortable <STRING>

        args:
            str: String

        returns:
            str: The now english sortable string
    """

    def naturalize_int_match(match):
        """ reformat as a human sortable number
        """
        return '%08d' % (int(match.group(0)),)

    string = string.lower().strip()
    string = re.sub(r'^the\s+', '', string)
    string = re.sub(r'\d+', naturalize_int_match, string)
    return string


def multiple_replace(repl_dict, text):
    """
    Regex to quickly replace multiple entries at the same time.

    Parameters
    ----------
    repl_dict (dict): Dictionary containing the pairs of values to replace
    text (str): The string to be modifying

    Returns
    -------
        Str : The potentially modified string
    """
    # Create a regular expression  from the dictionary keys
    # For each match, look-up corresponding value in dictionary
    return constants.regex.sub(lambda mo: repl_dict[mo.string[mo.start():mo.end()]], text)


def return_disk_listing(fqpn, enable_rename=False):
    """
    Return a dictionary that contains the scandir data (& some extra data) for the directory.

    each entry will be in this vein:

    data[<filename in titlecase>] = {"filename": the filename in titlecase,
                                       "lower_filename": the filename in lowercase (depreciated?),
                                            # Most likely depreciated in v3
                                       "path": The fully qualified pathname and filename
                                       'sortname': A naturalized sort ready filename
                                       'size': FileSize
                                       'lastmod': Last modified timestamp
                                       'is_dir': Is this entry a directory?
                                       'is_file': Is this entry a file?
                                       'is_archive': is this entry an archive
                                       'is_image': is this entry an image
                                       'is_movie': is this entry a movie file (not animated gif)
                                       'is_audio': is this entry an audio file
                                       'is_text': is this entry a text file
                                       'is_html': is this entry a html file
                                       'is_markdown': is this entry a markdown file
                                       'is_animated': Is this an animated file (e.g. animated GIF),
                                            not a movie file
                                       }
    This code obeys the following quickbbs_settings, settings:

    * EXTENSIONS_TO_IGNORE
    * FILES_TO_IGNORE
    * IGNORE_DOT_FILES

    Parameters
    ----------
    fqpn (str): The fully qualified pathname of the directory to scan
    enable_rename (bool): Do we rename files that could cause issues
        (e.g. filesname that have special characters (!?::, etc)).  True for rename,
        false to skip renaming.

    Returns
    -------
        dict of dicts - See above

    """
    data = {}
    # data_list = []
    loaded = True
    #    webpath = (fqpn.title().replace(settings.ALBUMS_PATH.title(),
    #                                    "")).replace("//", "/")
    for entry in os.scandir(fqpn):
        titlecase = entry.name.title()
        unescaped = html.unescape(titlecase)
        lower_filename = entry.name.lower()

        animated = False
        fext = os.path.splitext(lower_filename)[1]
        if fext == "":
            fext = ".none"
        elif entry.is_dir():
            fext = ".dir"

        if fext not in filetype_models.FILETYPE_DATA:
            # The file extension is not in FILETYPE_DATA, so ignore it.
            continue

        if (fext in settings.EXTENSIONS_TO_IGNORE) or \
                (lower_filename in settings.FILES_TO_IGNORE):
            # file extension is in EXTENSIONS_TO_IGNORE, so skip it.
            # or the filename is in FILES_TO_IGNORE, so skip it.
            continue

        if settings.IGNORE_DOT_FILES and lower_filename.startswith("."):
            # IGNORE_DOT_FLES is enabled, *and* the filename startswith an ., skip it.
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
                print(f"rejected - {titlecase}")
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
                           'is_audio': filetype_models.FILETYPE_DATA[fext]["is_audio"],
                           'is_text': filetype_models.FILETYPE_DATA[fext]["is_text"],
                           'is_html': filetype_models.FILETYPE_DATA[fext]["is_html"],
                           'is_markdown': filetype_models.FILETYPE_DATA[fext]["is_markdown"],
                           'is_animated': animated
                           }
    return (loaded, data)


def break_down_urls(uri_path):
    """
    Split URL into it's component parts

    Parameters
    ----------
    uri_path (str): The URI to break down

    Returns
    -------
        list : A list containing all of the parts of the URI

    >>> break_down_urls("http://www.google.com")
    """
    path = urllib.parse.urlsplit(uri_path).path
    return path.split('/')


def return_breadcrumbs(uri_path=""):
    """
    Return the breadcrumps for uri_path

    Parameters
    ----------
    uri_path (str): The URI to break down into breadcrumbs

    Returns
    -------
        list of tuples - consisting of [name, url, html url link]

    """
    uris = break_down_urls(uri_path.lower().replace(settings.ALBUMS_PATH.lower(), ""))
    data = []
    for count in range(1, len(uris)):
        name = uris[count].split("/")[-1]
        url = "/".join(uris[0:count + 1])
        if name == "":
            continue
        data.append([name, url, f"<a href='{url}'>{name}</a>"])
    return data


def fs_counts(fs_entries):
    """
    Quickly count the files vs directories in a list of scandir entries
    Used primary by sync_database_disk to count a path's files & directories

    Parameters
    ----------
    fs_entries (list) - list of scandir entries

    Returns
    -------
    tuple - (# of files, # of dirs)

    """
    files = 0
    dirs = 0
    for fs_item in fs_entries:
        is_file = fs_entries[fs_item]["is_file"]
        files += is_file
        dirs += not is_file
    return (files, dirs)


def sync_database_disk(directoryname):
    """

    Parameters
    ----------
    directoryname : The "webpath", the fragment of the directory name to load, lowercased, and
        double '//' is replaced with '/'

    Returns
    -------
    dictionary : That contains *only* the updated entries (e.g. deleted entries will be flagged
        with ignore and deleted.)  Otherwise, the dictionary will contain the updated records that
        need to be pushed to the database.

    Example
    -------
    success, diskstore = return_disk_listing("/albums")
    updated_recs = compare_db_to_fs("/albums", diskstore)
    for updated in updated_recs:
        ... push updated to database ...

    Note:
           * This does not currently contend with Archives.
           * Archive logic will need to be built-out or broken out elsewhere
           * This is still currently using the v2 data structures.  First test is
                to ensure that the logic works as expected.  Second is to then update
                to use new data structures for v3.
           * There's little path work done here, but look to rewrite to pass in Path from Pathlib?

    * Logic Update
        * If there are no database entries for the directory, the fs comparing to the database
    """
    bootstrap = False
    if directoryname in [os.sep, r"/"]:
        directoryname = settings.ALBUMS_PATH
    webpath = ensures_endswith(directoryname.lower().replace("//", "/"), os.sep)
    dirpath = os.path.abspath(directoryname.title().strip())

    success, fs_entries = return_disk_listing(webpath)
    #index_data.objects.prefetch_related('filetypes')
    #index_data.objects.select_related('filetypes')
    #index_data.objects.select_related('file_tnail')
    #index_data.objects.prefetch_related('directory')
    db_data = index_data.objects.select_related("filetype").select_related("directory").filter(fqpndirectory=webpath)
    # if db_data.count() == 0:
    #     record = index_data()
    #     record.uuid = uuid.uuid4()
    #     record.name = "DeleteMe"
    #     record.ignore = True
    #     record.delete_pending = True
    #     record.lastmod = time.time()
    #     record.lastscan = time.time()
    #     record.filetype = filetypes(fileext=".txt")
    #     record.save()
    #     bootstrap = True
    # db_data = index_data.objects.filter(fqpndirectory=webpath)

    for db_entry in db_data:
        if db_entry.name not in fs_entries:
            print("Database contains a file not in the fs: ", db_entry.name)
            # The entry just is not in the file system.  Delete it.
            db_entry.ignore = True
            db_entry.delete_pending = True
            db_entry.save()
        else:
            # The db_entry does exist in the file system.
            # Does the lastmod match?
            # Does size match?
            # If directory, does the numfiles, numdirs, count_subfiles match?

            update = False
            entry = fs_entries[db_entry.name]
            if db_entry.lastmod != entry["lastmod"]:
                # print("LastMod mismatch")
                db_entry.lastmod = entry["lastmod"]
                update = True
            if db_entry.size != entry['size']:
                # print("Size mismatch")
                db_entry.size = entry["size"]
                update = True
            if db_entry.directory:  # or db_entry["unified_dirs"]:
                success, subdirectory = return_disk_listing(entry["path"])
                fs_file_count, fs_dir_count = fs_counts(subdirectory)
                if db_entry.numfiles != fs_file_count or db_entry.numdirs != fs_dir_count:
                    db_entry.numfiles, db_entry.numdirs = fs_file_count, fs_dir_count
                    update = True
            if update:
                print("Database record being updated: ", db_entry.name)
                db_entry.save()
                update = False

    # Check for entries that are not in the database, but do exist in the file system
    names = index_data.objects.filter(fqpndirectory=webpath).values_list("name", flat=True)
    # fetch an updated set of records, since we may have changed it from above.
    records_to_create = []
    for fs_filename in fs_entries:
        entry = fs_entries[fs_filename]
        # iterate through the file system entries.
        test_name = entry["filename"].title().replace("//", "/")
        if test_name not in names:
            # The record has not been found
            # add it.

            record = index_data()
            record.uuid = uuid.uuid4()
            record.fqpndirectory = ensures_endswith(os.path.split(entry["path"])[0].lower(), os.sep)
            record.name = test_name
            record.sortname = naturalize(test_name)
            record.size = entry["size"]
            record.lastmod = entry["lastmod"]
            record.lastscan = time.time()
            record.is_dir = entry["is_dir"]
            record.is_file = entry["is_file"]
            record.is_archive = entry["is_archive"]
            record.is_image = entry["is_image"]
            record.is_movie = entry["is_movie"]
            record.is_audio = entry["is_audio"]
            fext = os.path.splitext(test_name)[1].lower()
            if not fext.startswith("."):
                fext = f".{fext}"
            if record.is_dir:
                fext = ".dir"
            if fext in [".", ""]:
                fext = ".none"
            if record.is_dir and record.name not in ["", "/"]:
                success, fs_subdirectory = return_disk_listing(os.path.join(webpath, test_name))
                record.numfiles, record.numdirs = fs_counts(fs_subdirectory)
            record.filetype = filetypes(fileext=fext)

            record.is_animated = False
            if filetype_models.FILETYPE_DATA[fext]["is_image"] and fext in [".gif"]:
                try:
                    record.is_animated = Image.open(os.path.join(record.fqpndirectory,
                                                                 record.name)).is_animated
                except AttributeError:
                    record.is_animated = False
            # print("FS contains file not in database, saving ", fs_filename)
            # record.save()
            records_to_create.append(record)
    if records_to_create:
        index_data.objects.bulk_create(records_to_create, 100)
        # else:
        # The record is in the database, so it's already been vetted in the database comparison
        # Skip
        # continue
    if bootstrap:
        index_data.objects.filter(delete_pending=True).delete()

    if Cache_Tracking.objects.filter(DirName=dirpath).count() == 0:
        # The path has not been seen since the Cache Tracking has been enabled
        # (eg Startup, or the entry has been nullified)
        # Add to table, and allow a rescan to occur.
        print(f"\nSaving, {dirpath} to cache tracking\n")
        new_rec = Cache_Tracking(DirName=dirpath, lastscan=time.time())
        new_rec.save()


def read_from_disk(dir_to_scan, skippable=True):
    """
    Stub function to bridge between v2 and v3 mechanisms.
    This is just a temporary bridge to prevent the need for a rewrite on
    functions that read_from_disk.

    This just redirects the read_from_disk call -> sync_database_disk.

    Parameters
    ----------
    dir_to_scan (str): The Fully Qualified pathname of the directory to scan
    skippable (bool): Is this allowed to skip, depreciated for v3.

    """
    if not os.path.exists(dir_to_scan):
        if dir_to_scan.startswith("/"):
            dir_to_scan = dir_to_scan[1:]
        dir_path = Path(os.path.join(settings.ALBUMS_PATH, dir_to_scan))
    else:
        dir_path = Path(ensures_endswith(dir_to_scan, os.sep))
    sync_database_disk(str(dir_path))
