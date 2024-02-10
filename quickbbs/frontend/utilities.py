"""
Utilities for QuickBBS, the python edition.
"""

import logging
import os
import os.path
import re
import stat
import time
import urllib.parse
import uuid
from io import BytesIO
from pathlib import Path
from typing import Union  # , List  # , Iterator, Optional, TypeVar, Generic

# from moviepy.video.io import VideoFileClip
# from moviepy.editor import VideoFileClip #* # import everythings (variables, classes, methods...)
# inside moviepy.editor
import av  # Video Previews
import django.db.utils
import filetypes.models as filetype_models
import fitz  # PDF previews

# from cache.models import fs_Cache_Tracking as Cache_Tracking
from cache.models import Cache_Storage
from django.conf import settings
from PIL import Image
from quickbbs.models import IndexDirs, filetypes, IndexData

import frontend.archives3 as archives
import frontend.constants as constants


log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None  # Disable PILLOW DecompressionBombError errors.


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


def ensures_endswith(string_to_check, value) -> str:
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


def sort_order(request) -> int:
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


def is_valid_uuid(uuid_to_test, version=4) -> bool:
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


def test_extension(name, ext_list) -> bool:
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


def load_pdf(fspath):
    """
    The load_pdf function loads a PDF file from the filesystem and returns an image.

    :param fspath: Load the file
    :return: A pil
    :doc-author: Trelent
    """
    #    if filetype_models.FILETYPE_DATA[os.path.splitext(fspath).lower()]["is_pdf"]:
    # Do not repair the PDF / validate the PDF.  If it's bad,
    # it should be repaired, not band-aided by a patch from the web server.
    # results = pdf_utilities.check_pdf(fs_path)
    with fitz.open(fspath) as pdf_file:
        pdf_page = pdf_file.load_page(0)
        # matrix=fitz.Identity, alpha=True)
        pix = pdf_page.get_pixmap(alpha=True)
        try:
            source_image = Image.open(BytesIO(pix.tobytes()))
        except UserWarning:
            print("UserWarning!")
            source_image = None
    return source_image


def load_movie(fspath, offset_from=30):
    """
    The load_movie function loads a movie from the file system and returns an image.

        Updated - 2022/12/21 - It will now search for the next
    :param fspath: Specify the path to the video file
    :param offset_from: The number of frames to advance *after* detecting a non-solid
        black or white frame.
    :return: A pillow image object

    References:
        * https://stackoverflow.com/questions/14041562/
            python-pil-detect-if-an-image-is-completely-black-or-white
    """
    with av.open(fspath) as container:
        stream = container.streams.video[0]
        duration_sec = stream.frames / 30
        container.seek(container.duration // 2)
        frame = container.decode(stream)
        image = next(frame).to_image()
    # endcount = None
    # for count, frame in enumerate(container.decode(stream)):
    #     image = frame.to_image()
    #     extrema = image.convert("L").getextrema()
    #     if extrema not in [(0, 0), (255, 255)]:
    #         if endcount is None:
    #             endcount = count + offset_from
    #     if endcount is not None and count >= endcount:
    #         break
    return image


# def load_movie_alt(fspath):
#     """
#     The load_movie_av function loads a movie from the filesystem and returns an image of the first frame.
#
#     :param fspath: Specify the path of the file
#     :return: An Pillow image object
#     """
#     with av.open(fspath) as container:
#         stream = container.streams.video[0]
#         frame = next(container.decode(stream))
#         return frame.to_image()


def load_image(fspath, mem=False):
    """
    The load_image function loads an image from a file path or byte stream.
    It returns the source_image object, which is a PIL Image object.

    :param fspath: Pass the path of the image file
    :param mem: Determine if the source file is a local file or a byte stream, if true, byte stream
    :return: A pil / Image object
    """
    source_image = None
    if not mem:
        try:
            source_image = Image.open(fspath)
        except OSError:
            print("Unable to load source file")
    else:
        try:  # fs_path is a byte stream
            source_image = Image.open(BytesIO(fspath))
        except OSError:
            print("IOError")
            log.debug("PIL was unable to identify as an image file")
        except UserWarning:
            print("UserWarning!")
    return source_image


def return_image_obj(fs_path, memory=False) -> Image:
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
        source_image = load_pdf(fs_path)

    elif filetype_models.FILETYPE_DATA[extension]["is_movie"]:
        source_image = load_movie(fs_path)

    elif filetype_models.FILETYPE_DATA[extension]["is_image"]:
        source_image = load_image(fs_path, mem=memory)

    return source_image


def cr_tnail_img(source_image, size, fext) -> Image:
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

    if fext in settings.MOVIE_FILE_TYPES:
        fext = ".jpg"

    with BytesIO() as image_data:  # = BytesIO()
        source_image.thumbnail((size, size), Image.Resampling.LANCZOS)
        try:
            source_image.save(
                fp=image_data,
                format="PNG",  # Need alpha channel support for icons, etc.
                optimize=False,
            )
        except OSError:
            source_image = source_image.convert("RGB")
            source_image.save(fp=image_data, format="JPEG", optimize=False)
        image_data.seek(0)
        return image_data.getvalue()


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
    return constants.regex.sub(
        lambda mo: repl_dict[mo.string[mo.start() : mo.end()]], text
    )


def return_disk_listing(fqpn, enable_rename=False) -> (bool, dict):
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
    fs_data = {}
    for item in Path(fqpn).iterdir():
        fext = os.path.splitext(item.name.lower())[1]
        if fext == "":
            fext = ".none"
        elif item.is_dir():
            fext = ".dir"

        if fext not in filetype_models.FILETYPE_DATA:
            # The file extension is not in FILETYPE_DATA, so ignore it.
            continue

        if (fext in settings.EXTENSIONS_TO_IGNORE) or (
            item.name.lower() in settings.FILES_TO_IGNORE
        ):
            # file extension is in EXTENSIONS_TO_IGNORE, so skip it.
            # or the filename is in FILES_TO_IGNORE, so skip it.
            continue

        if settings.IGNORE_DOT_FILES and item.name.lower().startswith("."):
            # IGNORE_DOT_FLES is enabled, *and* the filename startswith an ., skip it.
            continue

        fs_data[item.name.title().strip()] = item
    return (True, fs_data)


def break_down_urls(uri_path) -> Union[list[bytes], list[str]]:
    """
    Split URL into it's component parts

    Parameters
    ----------
    uri_path (str): The URI to break down

    Returns
    -------
        list : A list containing all of the parts of the URI

    >>> break_down_urls("https://www.google.com")
    """
    path = urllib.parse.urlsplit(uri_path).path
    return path.split("/")


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
        url = "/".join(uris[0 : count + 1])
        if name == "":
            continue
        data.append([name, url, f"<a href='{url}'>{name}</a>"])
    return data


def fs_counts(fs_entries) -> (int, int):
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

    def isfile(entry):
        return entry.is_file()

    files = len(list(filter(isfile, fs_entries.values())))
    dirs = len(fs_entries) - files

    return (files, dirs)


def add_archive(fqpn, new_uuid):
    """
    The add_archive function adds a new archive to the database.

    :param fqpn: Specify the fully qualified path name of the file to be added
    :param new_uuid: Create a new uuid for the archive
    :return: A list of the files that were added to the archive
    :doc-author: Trelent
    """
    print("Add Archive triggered", fqpn)
    compressed = archives.id_cfile_by_sig(fqpn)
    compressed.get_listings()
    for name, offset, filecount in compressed.listings:
        fileext = os.path.splitext(name).lower()
        if fileext in settings.IMAGE_SAFE_FILES:
            pass


def process_filedata(fs_entry, db_record, v3=False) -> IndexData:
    """
    The process_filedata function takes a file system entry and returns an IndexData object.
    The IndexData object contains the following attributes:
        fqpndirectory - The fully qualified path to the directory containing the file or folder.
        name - The name of the file or folder (without any parent directories).
        sortname - A normalized version of 'name' with all capital letters replaced by lower case letters,
            spaces replaced by underscores, and punctuation removed. This is used for sorting purposes only;
            it does not need to be unique nor must it match 'name'. It is recommended that
    :param fs_entry: Get the absolute path of the file
    :param db_record: Store the data in the database
    :param v3: Force the old version of process_filedata to be used, if True use v3 structures
        (Not yet ready)
    :return: A dictionary of values that can be
    :doc-author: Trelent
    """
    db_record.fqpndirectory, db_record.name = os.path.split(fs_entry.absolute())
    db_record.fqpndirectory = ensures_endswith(
        db_record.fqpndirectory.lower().replace("//", "/"), os.sep
    )
    db_record.name = db_record.name.title().replace("//", "/").strip()
    db_record.fileext = fs_entry.suffix.lower()
    db_record.is_dir = fs_entry.is_dir()
    if db_record.is_dir:
        db_record.fileext = ".dir"
    if db_record.fileext in [".", ""]:
        db_record.fileext = ".none"
    if db_record.fileext not in filetype_models.FILETYPE_DATA:
        return None

    db_record.filetype = filetypes(fileext=db_record.fileext)
    db_record.uuid = uuid.uuid4()
    db_record.size = fs_entry.stat()[stat.ST_SIZE]
    db_record.lastmod = fs_entry.stat()[stat.ST_MTIME]
    db_record.lastscan = time.time()

    db_record.is_file = fs_entry.is_file  # ["is_file"]
    db_record.is_archive = db_record.filetype.is_archive
    db_record.is_image = db_record.filetype.is_image
    db_record.is_movie = db_record.filetype.is_movie
    db_record.is_audio = db_record.filetype.is_audio
    db_record.is_animated = False

    if db_record.is_dir:  # or db_entry["unified_dirs"]:
        SubDirFqpn = os.path.join(db_record.fqpndirectory, db_record.name)
        sync_database_disk(SubDirFqpn)
        return None
        # _, subdirectory = return_disk_listing(SubDirFqpn)
        # fs_file_count, fs_dir_count = fs_counts(subdirectory)
        # db_record.numfiles, db_record.numdirs = fs_file_count, fs_dir_count

    if filetype_models.FILETYPE_DATA[db_record.fileext][
        "is_image"
    ] and db_record.fileext in [".gif"]:
        try:
            db_record.is_animated = Image.open(
                os.path.join(db_record.fqpndirectory, db_record.name)
            ).is_animated
        except AttributeError:
            db_record.is_animated = False

    return db_record


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
    dirpath = IndexDirs.normalize_fqpn(os.path.abspath(directoryname.title().strip()))
    found, dirpath_id = IndexDirs.search_for_directory(fqpn_directory=dirpath)
    if found is False:
        dirpath_id = IndexDirs.add_directory(dirpath)
        print("\tAdding ", dirpath)

    #    print(dirpath, dirpath_id)

    records_to_update = []
    cached = Cache_Storage.name_exists_in_cache(DirName=dirpath) is True

    if not cached:
        # If the directory is not found in the Cache_Tracking table, then it needs to be rescanned.
        # Remember, directory is placed in there, when it is scanned.
        # If changed, then watchdog should have removed it from the path.
        print(f"{dirpath=} not in Cache_Tracking")
        _, fs_entries = return_disk_listing(dirpath)

        success, IDirs = IndexDirs.search_for_directory(dirpath)
        count, db_data = IDirs.files_in_dir()
        if count in [0, None]:
            db_data = IndexData.objects.select_related("filetype", "directory").filter(
                fqpndirectory=webpath, delete_pending=False, ignore=False
            )

        #        print(count, db_data)
        # db_data = IndexData.search_for_directory(fqpn_directory=webpath)
        update = False
        for db_entry in db_data:
            if db_entry.name.strip() not in fs_entries:
                print("Database contains a file not in the fs: ", db_entry.name)
                # The entry just is not in the file system.  Delete it.
                db_entry.ignore = True
                db_entry.delete_pending = True
                db_entry.parent_dir = dirpath_id
                #                db_entry.fqpndirectory = db_entry.name.strip()
                records_to_update.append(db_entry)

            #            db_entry.save()
            else:
                # The db_entry does exist in the file system.
                # Does the lastmod match?
                # Does size match?
                # If directory, does the numfiles, numdirs, count_subfiles match?
                # update = False, unncessary, moved to above the for loop.
                # if db_entry.parent_dir is None:
                #     db_entry.parent_dir = dirpath_id
                #     update = True
                entry = fs_entries[db_entry.name.title()]
                #                if db_entry.directory:  # or db_entry["unified_dirs"]:
                #                    _, subdirectory = return_disk_listing(str(entry.absolute()))
                #                    continue
                if db_entry.lastmod != entry.stat()[stat.ST_MTIME]:
                    # print("LastMod mismatch")
                    db_entry.lastmod = entry.stat()[stat.ST_MTIME]
                    update = True
                if db_entry.size != entry.stat()[stat.ST_SIZE]:
                    # print("Size mismatch")
                    db_entry.size = entry.stat()[stat.ST_SIZE]
                    update = True
                    # print(" sync - ",str(entry.absolute))
                    # sync_database_disk(str(entry.absolute()))
                    # fs_file_count, fs_dir_count = fs_counts(subdirectory)
                    # fs_file_count, fs_dir_count = fs_counts(subdirectory)
                    # if db_entry.numfiles != fs_file_count or db_entry.numdirs != fs_dir_count:
                    #     db_entry.numfiles, db_entry.numdirs = fs_file_count, fs_dir_count
                    #     update = True
                if update:
                    records_to_update.append(db_entry)
                    print("Database record being updated: ", db_entry.name)
                    #                    db_entry.save()
                    update = False

        # Check for entries that are not in the database, but do exist in the file system
        names = (
            IndexData.objects.filter(fqpndirectory=webpath)
            .only("name")
            .values_list("name", flat=True)
        )
        # fetch an updated set of records, since we may have changed it from above.
        records_to_create = []
        for name, entry in fs_entries.items():
            test_name = entry.name.title().replace("//", "/").strip()
            if test_name not in names:
                # The record has not been found
                # add it.
                record = IndexData()
                record = process_filedata(entry, record, v3=False)
                if record is None:
                    continue
                record.parent_dir = dirpath_id
                if record.filetype.is_archive:
                    print("Archive detected ", record.name)
                records_to_create.append(record)
        if records_to_update:
            try:
                IndexData.objects.bulk_update(
                    records_to_update,
                    [
                        "ignore",
                        "lastmod",
                        "delete_pending",
                        "size",
                        "numfiles",
                        "numdirs",
                        "parent_dir_id",
                    ],
                    50,
                )
            except django.db.utils.IntegrityError:
                return None
        else:
            print("No records to update")
        # The record is in the database, so it's already been vetted in the database comparison
        if records_to_create:
            print("Creating records")
            try:
                IndexData.objects.bulk_create(records_to_create, 50)
            except django.db.utils.IntegrityError:
                return None
            # The record is in the database, so it's already been vetted in the database comparison
        else:
            print("No records to create")
        if bootstrap:
            IndexData.objects.filter(delete_pending=True).delete()

        #        if not Cache_Tracking.objects.filter(DirName=dirpath).exists():
        # The path has not been seen since the Cache Tracking has been enabled
        # (eg Startup, or the entry has been nullified)
        # Add to table, and allow a rescan to occur.
        print(f"\nSaving, {dirpath} to cache tracking\n")
        Cache_Storage.add_to_cache(DirName=dirpath)
        # new_rec = Cache_Tracking(DirName=dirpath, lastscan=time.time())
        # new_rec.save()


#        IndexData.objects.filter(delete_pending=True).delete()
# scan_lock.release_scan(webpath)


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

    # if not scan_lock.scan_in_progress(dir_path):
    #     scan_lock.start_scan(dir_path)
    sync_database_disk(str(dir_path))
    #     scan_lock.release_scan(dir_path)
