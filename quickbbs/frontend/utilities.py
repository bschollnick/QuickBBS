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

    Parameters
    ----------
    old_filename
    new_filename

    Returns
    -------

    """
    try:
        os.rename(old_filename, new_filename)
    except OSError:
        pass


def ensures_endswith(string_to_check, value):
    """
    Check the string (string_to_check) to see if value is the last character in string_to_check.
    If not, then add it to the end of the string.

    Parameters
    ----------
    string_to_check
    value

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
        # Do not repair the PDF / validate the PDF.  If it's bad, it should be repaired, not band-aided by
        # a patch from the web server.
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

        animated = False
        fext = os.path.splitext(lower_filename)[1]
        if fext == "":
            fext = ".none"
        elif entry.is_dir():
            fext = ".dir"

        if fext not in filetype_models.FILETYPE_DATA:
            # The file extension is not in FILETYPE_DATA, so ignore it.
            continue
        elif (fext in settings.EXTENSIONS_TO_IGNORE) or \
                (lower_filename in settings.FILES_TO_IGNORE):
            # file extension is in EXTENSIONS_TO_IGNORE, so skip it.
            # or the filename is in FILES_TO_IGNORE, so skip it.
            continue

        elif settings.IGNORE_DOT_FILES and lower_filename.startswith("."):
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
                           'is_audio': filetype_models.FILETYPE_DATA[fext]["is_audio"],
                           'is_text': filetype_models.FILETYPE_DATA[fext]["is_text"],
                           'is_html': filetype_models.FILETYPE_DATA[fext]["is_html"],
                           'is_markdown': filetype_models.FILETYPE_DATA[fext]["is_markdown"],
                           'is_animated': animated
                           }
    return (loaded, data)


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


def fs_counts(fs_entries):
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
    """

    if directoryname in [os.sep, r"/"]:
        directoryname = settings.ALBUMS_PATH
    webpath = ensures_endswith(directoryname.lower().replace("//", "/"), os.sep)
    dirpath = os.path.abspath(directoryname.title().strip())

    if Cache_Tracking.objects.filter(DirName=dirpath).count() == 0:
        # The path has not been seen since the Cache Tracking has been enabled
        # (eg Startup, or the entry has been nullified)
        # Add to table, and allow a rescan to occur.
        print("\n", "\nSaving, %s to cache tracking\n" % dirpath, "\n")
        new_rec = Cache_Tracking(DirName=dirpath, lastscan=time.time())
        new_rec.save()

    success, fs_entries = return_disk_listing(webpath)

    db_data = index_data.objects.filter(fqpndirectory=webpath)
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
            #            if db_entry.filetypes.fileext not in filetypes.filetype[db_entry.filetypes.fileext]:
            #                pass
            if db_entry.directory:  # or db_entry["unified_dirs"]:
                success, subdirectory = return_disk_listing(entry["path"])
                fs_file_count, fs_dir_count = fs_counts(subdirectory)
                if db_entry.numfiles != fs_file_count or db_entry.numdirs != fs_dir_count:
                    db_entry.numfiles, db_entry.numdirs = fs_file_count, fs_dir_count
                    update = True
            if update:
                print("Database record being updated: ", db_entry.name)
                db_entry.save()

    # Check for entries that are not in the database, but do exist in the file system
    db_data = index_data.objects.filter(fqpndirectory=webpath)
    # fetch an updated set of records, since we may have changed it from above.
    names = [record.name for record in db_data]
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
                    record.is_animated = Image.open(os.path.join(record.fqpndirectory, record.name)).is_animated
                except AttributeError:
                    record.is_animated = False
            print("FS contains file not in database, saving ", fs_filename)
            record.save()
        # else:
        # The record is in the database, so it's already been vetted in the database comparison
        # Skip
        # continue


def read_from_disk(dir_to_scan, skippable=True):
    if not os.path.exists(dir_to_scan):
        if dir_to_scan.startswith("/"):
            dir_to_scan = dir_to_scan[1:]
        dir_path = Path(os.path.join(settings.ALBUMS_PATH, dir_to_scan))
    else:
        dir_path = Path(ensures_endswith(dir_to_scan, os.sep))
    sync_database_disk(str(dir_path))
