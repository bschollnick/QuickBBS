"""
Utilities for QuickBBS, the python edition.
"""
import logging
import os
import os.path
import stat
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Union  # , List  # , Iterator, Optional, TypeVar, Generic

import django.db.utils
from PIL import Image
from django.conf import settings
from quickbbs.quickbbs.models import filetypes, index_data
from quickbbs.quickbbs.models import *
import quickbbs.filetypes.models as filetype_models
#  import frontend.archives3 as archives
import frontend.constants as constants
from quickbbs.cache.models import Cache_Storage

log = logging.getLogger(__name__)

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

        if (fext in settings.EXTENSIONS_TO_IGNORE) or \
                (item.name.lower() in settings.FILES_TO_IGNORE):
            # file extension is in EXTENSIONS_TO_IGNORE, so skip it.
            # or the filename is in FILES_TO_IGNORE, so skip it.
            continue

        if settings.IGNORE_DOT_FILES and item.name.lower().startswith("."):
            # IGNORE_DOT_FLES is enabled, *and* the filename startswith an ., skip it.
            continue

        fs_data[item.name.title().strip()] = item
    return (True, fs_data)




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
    # files = sum(map(os.DirEntry.is_file, fs_entries.values()))
    files = 0
    for fs_item in fs_entries.values():
        files += fs_item.is_file()
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


def process_filedata(fs_entry, db_record, v3=False) -> index_data:
    """
    The process_filedata function takes a file system entry and returns an index_data object.
    The index_data object contains the following attributes:
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
    db_record.fqpndirectory = ensures_endswith(db_record.fqpndirectory.lower().replace("//", "/"), os.sep)
    db_record.name = db_record.name.title().replace("//", "/").strip()
    db_record.fileext = fs_entry.suffix.lower()
    db_record.is_dir = fs_entry.is_dir()
    if db_record.is_dir:
        db_record.fileext = ".dir"
    if db_record.fileext in [".", ""]:
        db_record.fileext = ".none"
    if db_record.fileext in filetype_models.FILETYPE_DATA:
        db_record.filetype = filetypes(fileext=db_record.fileext)
    else:
        return None
    #    webpath = ensures_endswith(fs_entry.resolve().lower().replace("//", "/"), os.sep)
    db_record.uuid = uuid.uuid4()
    # db_record.fqpndirectory = ensures_endswith(os.path.split(fs_entry["path"])[0].lower(), os.sep)
    db_record.sortname = naturalize(db_record.name)
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
        _, subdirectory = return_disk_listing(os.path.join(db_record.fqpndirectory, db_record.name))
        fs_file_count, fs_dir_count = fs_counts(subdirectory)
        db_record.numfiles, db_record.numdirs = fs_file_count, fs_dir_count

    if filetype_models.FILETYPE_DATA[db_record.fileext]["is_image"] and \
            db_record.fileext in [".gif"]:
        try:
            db_record.is_animated = Image.open(os.path.join(db_record.fqpndirectory,
                                                            db_record.name)).is_animated
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
    dirpath = os.path.abspath(directoryname.title().strip())

    records_to_update = []
    cached = Cache_Storage.name_exists_in_cache(DirName=dirpath) is True

    if not cached:
        # If the directory is not found in the Cache_Tracking table, then it needs to be rescanned.
        # Remember, directory is placed in there, when it is scanned.
        # If changed, then watchdog should have removed it from the path.
        print(f"{dirpath=} not in Cache_Tracking")
        _, fs_entries = return_disk_listing(dirpath)

        db_data = index_data.objects.select_related("filetype", "directory").filter(
            fqpndirectory=webpath, delete_pending=False, ignore=False)
        # db_data = index_data.search_for_directory(fqpn_directory=webpath)
        for db_entry in db_data:
            if db_entry.name.strip() not in fs_entries:
                print("Database contains a file not in the fs: ", db_entry.name)
                # The entry just is not in the file system.  Delete it.
                db_entry.ignore = True
                db_entry.delete_pending = True
                records_to_update.append(db_entry)
    #            db_entry.save()
            else:
                # The db_entry does exist in the file system.
                # Does the lastmod match?
                # Does size match?
                # If directory, does the numfiles, numdirs, count_subfiles match?

                update = False
                entry = fs_entries[db_entry.name.title()]
                if db_entry.lastmod != entry.stat()[stat.ST_MTIME]:
                    # print("LastMod mismatch")
                    db_entry.lastmod = entry.stat()[stat.ST_MTIME]
                    update = True
                if db_entry.size != entry.stat()[stat.ST_SIZE]:
                    # print("Size mismatch")
                    db_entry.size = entry.stat()[stat.ST_SIZE]
                    update = True
                if db_entry.directory:  # or db_entry["unified_dirs"]:
                    _, subdirectory = return_disk_listing(str(entry.absolute()))
                    # fs_file_count, fs_dir_count = fs_counts(subdirectory)
                    fs_file_count, fs_dir_count = fs_counts(subdirectory)
                    if db_entry.numfiles != fs_file_count or db_entry.numdirs != fs_dir_count:
                        db_entry.numfiles, db_entry.numdirs = fs_file_count, fs_dir_count
                        update = True
                if update:
                    records_to_update.append(db_entry)
                    print("Database record being updated: ", db_entry.name)
#                    db_entry.save()
                    update = False

        # Check for entries that are not in the database, but do exist in the file system
        names = index_data.objects.filter(fqpndirectory=webpath).only("name").values_list("name", flat=True)
        # fetch an updated set of records, since we may have changed it from above.
        records_to_create = []
        for name, entry in fs_entries.items():
            test_name = entry.name.title().replace("//", "/").strip()
            if test_name not in names:
                # The record has not been found
                # add it.
                record = index_data()
                record = process_filedata(entry, record, v3=False)
                if record is None:
                    continue
                if record.filetype.is_archive:
                    print("Archive detected ", record.name)
                records_to_create.append(record)
        if records_to_update:
            try:
                index_data.objects.bulk_update(records_to_update, ["ignore", "lastmod", "delete_pending", "size", "numfiles", "numdirs"], 50)
            except django.db.utils.IntegrityError:
                return None
        else:
            print("No records to update")
        # The record is in the database, so it's already been vetted in the database comparison
        if records_to_create:
            print("Creating records")
            try:
                index_data.objects.bulk_create(records_to_create, 50)
            except django.db.utils.IntegrityError:
                return None
            # The record is in the database, so it's already been vetted in the database comparison
        else:
            print("No records to create")
        if bootstrap:
            index_data.objects.filter(delete_pending=True).delete()

        #        if not Cache_Tracking.objects.filter(DirName=dirpath).exists():
        # The path has not been seen since the Cache Tracking has been enabled
        # (eg Startup, or the entry has been nullified)
        # Add to table, and allow a rescan to occur.
        print(f"\nSaving, {dirpath} to cache tracking\n")
        Cache_Storage.add_to_cache(DirName=dirpath)
        # new_rec = Cache_Tracking(DirName=dirpath, lastscan=time.time())
        # new_rec.save()

#        index_data.objects.filter(delete_pending=True).delete()
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
