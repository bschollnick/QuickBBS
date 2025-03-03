"""
Utilities for QuickBBS, the python edition.
"""

import os
import os.path
import stat
import time
import urllib.parse
import uuid
from datetime import timedelta
from functools import lru_cache, wraps
from pathlib import Path

# from moviepy.video.io import VideoFileClip
# from moviepy.editor import VideoFileClip #* # import everythings (variables, classes, methods...)
# inside moviepy.editor
# import av  # Video Previews
import django.db.utils
import filetypes.models as filetype_models
from cache_watcher.models import Cache_Storage
from django.conf import settings
from django.db.utils import IntegrityError
from django.utils.html import format_html
from django_thread import ThreadPoolExecutor
from PIL import Image
from thumbnails.image_utils import movie_duration

# from quickbbs.logger import log
from quickbbs.models import IndexData, IndexDirs

Image.MAX_IMAGE_PIXELS = None  # Disable PILLOW DecompressionBombError errors.

MAX_THREADS = 20

# executor = ThreadPoolExecutor(max_workers=MAX_THREADS)
from django.db import connection


class DjangoConnectionThreadPoolExecutor(ThreadPoolExecutor):
    """
    When a function is passed into the ThreadPoolExecutor via either submit() or map(),
    this will wrap the function, and make sure that close_django_db_connection() is called
    inside the thread when it's finished so Django doesn't leak DB connections.

    Since map() calls submit(), only submit() needs to be overwritten.

    Attempting to fix what appears to be a starvation of connections?
    https://stackoverflow.com/questions/57211476/django-orm-leaks-connections-when-using-threadpoolexecutor

    Not positive that this is the issue, but worth the attempt to resolve it.
    """

    def close_django_db_connection(self):
        connection.close()

    def generate_thread_closing_wrapper(self, fn):
        @wraps(fn)
        def new_func(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            finally:
                self.close_django_db_connection()

        return new_func

    def submit(*args, **kwargs):
        """
        I took the args filtering/unpacking logic from

        https://github.com/python/cpython/blob/3.7/Lib/concurrent/futures/thread.py

        so I can properly get the function object the same way it was done there.
        """
        if len(args) >= 2:
            self, fn, *args = args
            fn = self.generate_thread_closing_wrapper(fn=fn)
        elif not args:
            raise TypeError(
                "descriptor 'submit' of 'ThreadPoolExecutor' object "
                "needs an argument"
            )
        elif "fn" in kwargs:
            fn = self.generate_thread_closing_wrapper(fn=kwargs.pop("fn"))
            self, *args = args

        return super(self.__class__, self).submit(fn, *args, **kwargs)


# executor = DjangoConnectionThreadPoolExecutor(max_workers=MAX_THREADS)


SORT_MATRIX = {
    0: ["-filetype__is_dir", "-filetype__is_link", "name_sort", "lastmod"],
    1: ["-filetype__is_dir", "-filetype__is_link", "lastmod", "name_sort"],
    2: ["-filetype__is_dir", "-filetype__is_link", "name_sort"],
}


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

    """
    return int(request.GET.get("sort", default=0))


def return_disk_listing(fqpn) -> tuple[bool, dict]:
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

    Returns
    -------
        dict of dicts - See above

    """
    fs_data = {}
    try:
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
    except FileNotFoundError:
        return False, {}
    return (True, fs_data)


def break_down_urls(uri_path) -> list[str]:
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


@lru_cache(maxsize=250)
def convert_to_webpath(full_path, directory=None):
    """
    Convert a full path to a webpath

    Parameters
    ----------
    full_path (str): The full path to convert

    Returns
    -------
        str : The converted webpath

    """
    if directory is not None:
        cutpath = settings.ALBUMS_PATH.lower() + directory.lower() if directory else ""
    else:
        cutpath = settings.ALBUMS_PATH.lower()

    return full_path.replace(cutpath, "")


@lru_cache(maxsize=250)
def return_breadcrumbs(uri_path="") -> list[str]:
    """
    Return the breadcrumps for uri_path

    Parameters
    ----------
    uri_path (str): The URI to break down into breadcrumbs

    Returns
    -------
        list of tuples - consisting of [name, url, html url link]


    breadcrumbs = return_breadcrumbs(context["webpath"])
    for bcrumb in breadcrumbs:
        context["breadcrumbs"] += f"<li>{bcrumb[2]}</li>"
        context["breadcrumbs_list"].append(bcrumb[2])
    """
    uris = break_down_urls(convert_to_webpath(uri_path))
    data = []
    for count, name in enumerate(uris):
        if name == "":
            continue
        url = "/".join(uris[0 : count + 1])
        data.append([name, url, f"<a href='{url}'>{name}</a>"])
    return data


def fs_counts(fs_entries) -> tuple[int, int]:
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


def process_filedata(fs_entry, db_record) -> IndexData:
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
    fileext = fs_entry.suffix.lower()
    is_dir = fs_entry.is_dir()
    if is_dir:
        fileext = ".dir"
    if fileext in [".", ""]:
        fileext = ".none"

    if fileext not in filetype_models.FILETYPE_DATA:
        print("Can't match fileext w/filetypes")
        return None

    # db_record.filetype = filetypes(fileext=db_record.fileext)
    fs_stat = fs_entry.stat()
    db_record.filetype = filetype_models.filetypes(fileext=fileext)
    db_record.uuid = uuid.uuid4()
    db_record.size = fs_stat[stat.ST_SIZE]
    db_record.lastmod = fs_stat[stat.ST_MTIME]
    db_record.lastscan = time.time()
    db_record.is_animated = False
    if is_dir:
        sub_dir_fqpn = os.path.join(db_record.fqpndirectory, db_record.name)
        sync_database_disk(sub_dir_fqpn)
        return None
        # _, subdirectory = return_disk_listing(sub_dir_fqpn)
        # fs_file_count, fs_dir_count = fs_counts(subdirectory)
        # db_record.numfiles, db_record.numdirs = fs_file_count, fs_dir_count

    if filetype_models.FILETYPE_DATA[fileext].is_link:
        _, redirect = db_record.name.lower().split("*")
        redirect = (
            redirect.replace("'", "")
            .replace("__", "/")
            .replace(redirect.split(".")[-1], "")[:-1]
        )
        db_record.fqpndirectory = f"/{redirect}"
    else:
        db_record.file_sha256 = db_record.get_file_sha(fqfn=fs_entry.absolute())

    # if filetype_models.FILETYPE_DATA[fileext]["is_movie"]:
    #     duration =  (
    #         os.path.join(db_record.fqpndirectory, db_record.name)
    #     )
    #     if duration is not None:
    #         db_record.duration = duration
    if filetype_models.FILETYPE_DATA[fileext].is_image and fileext in [".gif"]:
        try:
            with Image.open(
                os.path.join(db_record.fqpndirectory, db_record.name)
            ) as test_animation:
                # db_record.is_animated = Image.open(os.path.join(db_record.fqpndirectory, db_record.name)).is_animated
                db_record.is_animated = test_animation.is_animated
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
    None

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
    bulk_size = 15
    if directoryname in [os.sep, r"/"]:
        directoryname = settings.ALBUMS_PATH
    webpath = ensures_endswith(directoryname.lower().replace("//", "/"), os.sep)
    dirpath = IndexDirs.normalize_fqpn(os.path.abspath(directoryname.title().strip()))
    found, dirpath_id = IndexDirs.search_for_directory(fqpn_directory=dirpath)
    if found is False:
        dirpath_id = IndexDirs.add_directory(dirpath)
        # print("\tAdding ", dirpath)

    records_to_update = []
    cached = Cache_Storage.name_exists_in_cache(DirName=dirpath) is True
    if cached:
        return None

    # It's not cached
    # if not cached:
    print("Not Cached! Rescanning directory")
    # If the directory is not found in the Cache_Tracking table, then it needs to be rescanned.
    # Remember, directory is placed in there, when it is scanned.
    # If changed, then watchdog should have removed it from the path.
    success, fs_entries = return_disk_listing(dirpath)
    if not success:
        # File path doesn't exist
        # remove file path from cache
        # remove parent from cache
        # remove file path from Database
        success, dirpath_id = IndexDirs.search_for_directory(dirpath)
        parent_dir = dirpath_id.return_parent_directory()
        dirpath_id.delete_directory(dirpath)
        if parent_dir.exists():
            parent_dir = parent_dir[0]
            dirpath_id.delete_directory(parent_dir, cache_only=True)

    # retrieve IndexDirs entry for dirpath
    success, dirpath_id = IndexDirs.search_for_directory(dirpath)
    if not success:
        return None

    # Compare the database entries to see if they exist in the file system
    # If they don't, remove from cache, and delete the directory
    db_directories = dirpath_id.dirs_in_dir()
    for fqpn in db_directories.values_list("fqpndirectory", flat=True):
        if str(Path(fqpn).name).strip().title() not in fs_entries:
            # print("Database contains a **directory** not in the fs: ", fqpn)
            IndexDirs.delete_directory(fqpn_directory=fqpn)

    update = False
    db_data = dirpath_id.files_in_dir()

    for db_entry in db_data:
        fext = os.path.splitext(db_entry.name.strip())[1].lower()
        if db_entry.name.strip() not in fs_entries:
            # print("Database contains a file not in the fs: ", db_entry.name)
            # The entry just is not in the file system.  Delete it.
            # db_entry.ignore = True
            db_entry.delete()
            continue
        else:
            # The db_entry does exist in the file system.
            # Does the lastmod match?
            # Does size match?
            # If directory, does the numfiles, numdirs, count_subfiles match?
            # update = False, unncessary, moved to above the for loop.
            entry = fs_entries[db_entry.name.title()]
            fs_stat = entry.stat()
            if (
                db_entry.file_sha256 in ["", None]
                and fext != ""
                and not filetype_models.FILETYPE_DATA[fext].is_link
            ):
                db_entry.file_sha256 = db_entry.get_file_sha(
                    fqfn=os.path.join(db_entry.fqpndirectory, db_entry.name)
                )
                update = True
            if db_entry.lastmod != fs_stat[stat.ST_MTIME]:
                # print("LastMod mismatch")
                db_entry.lastmod = fs_stat[stat.ST_MTIME]
                update = True
            if db_entry.size != fs_stat[stat.ST_SIZE]:
                # print("Size mismatch")
                db_entry.size = fs_stat[stat.ST_SIZE]
                update = True
            if fext not in [""]:
                if (
                    filetype_models.FILETYPE_DATA[fext].is_movie
                    and db_entry.duration is None
                ):
                    duration = movie_duration(
                        os.path.join(db_entry.fqpndirectory, db_entry.name)
                    )
                    if duration is not None:
                        db_entry.duration = timedelta(duration)
                        update = True
            if update:
                records_to_update.append(db_entry)
                # print("Database record being updated: ", db_entry.name)
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
    # print("names:",names)
    for _, entry in fs_entries.items():
        test_name = entry.name.title().replace("//", "/").strip()
        # print(test_name, test_name in names )
        if test_name not in names:
            # The record has not been found
            # add it.
            record = IndexData()
            record = process_filedata(entry, record)
            if record is None:
                continue
            record.parent_dir = dirpath_id
            if record.filetype.is_archive:
                print("Archive detected ", record.name)
            try:
                record.save()
            except IntegrityError:
                print("Integrity Error")
                continue  # Need to rethink the link records, if a directory is deleted, and it
                # contains a link record, that link record may not be deleted, thus causing
                # an integrity error if it's attempted to be recreated
    if records_to_update:
        try:
            IndexData.objects.bulk_update(
                records_to_update,
                [
                    #                    "ignore",
                    "lastmod",
                    "delete_pending",
                    "size",
                    "duration",
                    "file_sha256",
                    #                        "numfiles",
                    #                        "numdirs",
                    "parent_dir_id",
                ],
                bulk_size,
            )
            records_to_update = []
        except django.db.utils.IntegrityError:
            return None
    else:
        pass
        # print("No records to update")
    # The record is in the database, so it's already been vetted in the database comparison
    if records_to_create:
        try:
            IndexData.objects.bulk_create(records_to_create, bulk_size)
            records_to_create = []
        except django.db.utils.IntegrityError:
            print("Integrity Error")
            return None
        # The record is in the database, so it's already been vetted in the database comparison
    else:
        pass

    # The path has not been seen since the Cache Tracking has been enabled
    # (eg Startup, or the entry has been nullified)
    # Add to table, and allow a rescan to occur.
    print(f"\nSaving, {dirpath} to cache tracking\n")
    Cache_Storage.add_to_cache(DirName=dirpath)
    # new_rec = Cache_Tracking(DirName=dirpath, lastscan=time.time())
    # new_rec.save()

    #
    #   Testing - TODO: Remove.  Only testing to see if the rescan memory leak is due to
    #   old connections?  But Django doesn't appear to be running out of connections to
    #   postgres?  So probably a red herring.
    #
    # from django.db import connection, close_old_connections
    # close_old_connections()
    # connection.connect()
    return None


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


# import os.path
# from Foundation import *
# from cocoa import NSURL

# def target_of_alias(path):
#     url = NSURL.fileURLWithPath_(path)
#     bookmarkData, error = NSURL.bookmarkDataWithContentsOfURL_error_(url, None)
#     if bookmarkData is None:
#         return None
#     opts = NSURLBookmarkResolutionWithoutUI | NSURLBookmarkResolutionWithoutMounting
#     resolved, stale, error = NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(bookmarkData, opts, None, None, None)
#     return resolved.path()

# def resolve_links_and_aliases(path):
#     while True:
#         alias_target = target_of_alias(path)
#         if alias_target:
#             path = alias_target
#             continue
#         if os.path.islink(path):
#             path = os.path.realpath(path)
#             continue
#         return path
