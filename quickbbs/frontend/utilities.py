"""
Utilities for QuickBBS, the python edition.
"""

import logging
import os
import os.path
import time
import urllib.parse

# from datetime import timedelta
from functools import lru_cache  # , wraps
from pathlib import Path
from typing import Any, Optional

import filetypes.models as filetype_models
from cache_watcher.models import Cache_Storage, get_dir_sha
from django.conf import settings
from django.db import transaction  # connection

# from django.db.models import Case, F, Value, When, BooleanField
from frontend.file_listings import return_disk_listing
from PIL import Image
from thumbnails.video_thumbnails import _get_video_info

from quickbbs.common import get_file_sha, normalize_fqpn
from quickbbs.models import IndexData, IndexDirs

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None  # Disable PILLOW DecompressionBombError errors.

MAX_THREADS = 20


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


def _get_or_create_directory(
    directory_sha256: str, dirpath: str
) -> tuple[Optional[object], bool]:
    """Get or create directory record and check cache status."""
    found, dirpath_info = IndexDirs.search_for_directory_by_sha(directory_sha256)
    if not found:
        found, dirpath_info = IndexDirs.add_directory(dirpath)
        if not found:
            logger.error(f"Failed to create directory record for {dirpath}")
            return None, False
        Cache_Storage.remove_from_cache_sha(dirpath_info.dir_fqpn_sha256)
        return dirpath_info, False

    # Check cache status
    is_cached = Cache_Storage.sha_exists_in_cache(sha256=directory_sha256)
    return dirpath_info, is_cached


def _handle_missing_directory(dirpath_info: object) -> None:
    """Handle case where directory doesn't exist on filesystem."""
    try:
        parent_dirs = dirpath_info.return_parent_directory()
        dirpath_info.delete_directory(dirpath_info.fqpndirectory)

        # Clean up parent directory cache if it exists
        if parent_dirs and parent_dirs.exists():
            parent_dir = parent_dirs.first()
            if parent_dir:
                parent_dir.delete_directory(parent_dir.fqpndirectory, cache_only=True)
    except Exception as e:
        logger.error(f"Error handling missing directory: {e}")


def _sync_directories(dirpath_info: object, fs_entries: dict) -> None:
    """Synchronize database directories with filesystem."""
    # Get all database directories in one query
    print("Synchronizing directories...")
    logger.info("Synchronizing directories...")
    records_to_update = []
    current_path = normalize_fqpn(dirpath_info.fqpndirectory)
    all_dirs_in_database = dirpath_info.dirs_in_dir()

    all_database_dir_names_set = set(
        all_dirs_in_database.values_list("fqpndirectory", flat=True)
    )

    # Get filesystem directory names
    all_filesystem_dir_names = {
        normalize_fqpn(current_path + entry.name)
        for entry in fs_entries.values()
        if entry.is_dir()
    }

    entries_that_dont_exist_in_fs = (
        all_database_dir_names_set - all_filesystem_dir_names
    )
    entries_not_in_database = all_filesystem_dir_names - all_database_dir_names_set

    existing_directories_in_database = all_dirs_in_database.filter(
        fqpndirectory__in=all_database_dir_names_set
    )
    print(f"Existing directories in database: {len(existing_directories_in_database)}")
    if existing_directories_in_database:
        updated_records = _check_directory_updates(
            fs_entries, existing_directories_in_database
        )
        print(f"Directories to Update: {len(updated_records)}")
        if updated_records:
            print(f"processing existing directory changes: {len(updated_records)}")
            with transaction.atomic():
                logger.info(f"Processing {len(updated_records)} directory updates")
                # Update existing directory records
                for db_dir_entry in updated_records:
                    db_dir_entry.save()
                    Cache_Storage.remove_from_cache_sha(db_dir_entry.dir_fqpn_sha256)

    if entries_that_dont_exist_in_fs:
        print(f"Directories to Delete: {len(entries_that_dont_exist_in_fs)}")
        logger.info(f"Directories to Delete: {len(entries_that_dont_exist_in_fs)}")
        all_dirs_in_database.filter(
            fqpndirectory__in=entries_that_dont_exist_in_fs
        ).delete()
        Cache_Storage.remove_from_cache_sha(dirpath_info.dir_fqpn_sha256)

    if entries_not_in_database:
        print(f"Directories to Add: {len(entries_not_in_database)}")
        logger.info(f"Directories to Add: {len(entries_not_in_database)}")
        with transaction.atomic():
            for dir_to_create in entries_not_in_database:
                IndexDirs.add_directory(fqpn_directory=dir_to_create)


def _check_directory_updates(
    fs_entries: dict, existing_directories_in_database: object
) -> list[object]:
    """Check for updates in existing directories based on filesystem entries."""
    records_to_update = []
    for db_dir_entry in existing_directories_in_database:
        fs_entry = fs_entries.get(db_dir_entry.fqpndirectory)
        if fs_entry:
            try:
                fs_stat = fs_entry.stat()
                update_needed = False

                # Check modification time
                if db_dir_entry.lastmod != fs_stat.st_mtime:
                    db_dir_entry.lastmod = fs_stat.st_mtime
                    update_needed = True

                # Check directory size (if applicable)
                if db_dir_entry.size != fs_stat.st_size:
                    db_dir_entry.size = fs_stat.st_size
                    update_needed = True

                if update_needed:
                    records_to_update.append(db_dir_entry)

            except (OSError, IOError) as e:
                logger.error(
                    f"Error checking directory {db_dir_entry.fqpndirectory}: {e}"
                )

    return records_to_update


def _sync_files(dirpath_info: object, fs_entries: dict, bulk_size: int) -> None:
    """Synchronize database files with filesystem."""
    # Get all database files in one optimized query
    # db_bulk_size = 1000
    fs_file_names_dict = {
        name: entry for name, entry in fs_entries.items() if not entry.is_dir()
    }
    fs_file_names = [
        name.strip().title() for name, entry in fs_entries.items() if not entry.is_dir()
    ]

    all_files_in_dir = dirpath_info.files_in_dir()
    all_db_filenames = set(all_files_in_dir.values_list("name", flat=True))
    records_to_update = []
    potential_updates = all_files_in_dir.filter(name__in=fs_file_names)
    for db_file_entry in potential_updates:  # .iterator(chunk_size=db_bulk_size):
        updated_record = _check_file_updates(
            db_file_entry, fs_file_names_dict[db_file_entry.name], dirpath_info
        )
        if updated_record:
            records_to_update.append(updated_record)

    records_to_delete = all_files_in_dir.all().exclude(name__in=fs_file_names)

    fs_file_names_for_creation = set(fs_file_names) - set(all_db_filenames)
    creation_fs_file_names_dict = {}
    for name in fs_file_names_for_creation:
        creation_fs_file_names_dict[name] = fs_file_names_dict[name]

    records_to_create = _process_new_files(dirpath_info, creation_fs_file_names_dict)
    # Execute batch operations
    _execute_batch_operations(
        records_to_update, records_to_create, records_to_delete, bulk_size
    )


def _check_file_updates(
    db_record: object, fs_entry: Path, home_directory: object
) -> Optional[object]:
    """Check if database record needs updating based on filesystem entry."""
    try:
        fs_stat = fs_entry.stat()
        update_needed = False

        # Check file hash if missing
        fext = os.path.splitext(db_record.name)[1].lower()
        if fext:  # Only process files with extensions
            filetype = filetype_models.filetypes.return_filetype(fileext=fext)

            if not db_record.file_sha256 and not filetype.is_link:
                try:
                    db_record.file_sha256, db_record.unique_sha256 = (
                        db_record.get_file_sha(fqfn=fs_entry)
                    )
                    update_needed = True
                except Exception as e:
                    logger.error(f"Error calculating SHA for {fs_entry}: {e}")

            if db_record.home_directory != home_directory:
                db_record.home_directory = home_directory
                update_needed = True

            # Check modification time
            if db_record.lastmod != fs_stat.st_mtime:
                db_record.lastmod = fs_stat.st_mtime
                update_needed = True

            # Check file size
            if db_record.size != fs_stat.st_size:
                db_record.size = fs_stat.st_size
                update_needed = True

            # Check movie duration
            if filetype.is_movie and db_record.duration is None:
                try:
                    video_details = _get_video_info(str(fs_entry))
                    db_record.duration = video_details.get("duration", None)
                    update_needed = True
                except Exception as e:
                    logger.error(f"Error getting duration for {fs_entry}: {e}")

        return db_record if update_needed else None

    except (OSError, IOError) as e:
        logger.error(f"Error checking file {fs_entry}: {e}")
        return None


def _process_new_files(dirpath_info: object, fs_file_names: dict) -> list[object]:
    """Process files that exist in filesystem but not in database."""
    records_to_create = []
    for _, fs_entry in fs_file_names.items():
        try:
            # Process new file
            filedata = process_filedata(fs_entry, directory_id=dirpath_info)
            if filedata is None:
                continue

            # Skip archives for now (as per original logic)
            filetype = filedata.get("filetype")
            if hasattr(filetype, "is_archive") and filetype.is_archive:
                logger.info(f"Archive detected: {filedata['name']}")
                continue
            # Create record using get_or_create to handle duplicates
            record = IndexData(**filedata)
            # record, created = IndexData.objects.get_or_create(
            #    unique_sha256=filedata.get("unique_sha256"), defaults=filedata
            # )
            record.home_directory = dirpath_info
            records_to_create.append(record)

        except Exception as e:
            logger.error(f"Error processing new file {fs_entry}: {e}")
            continue

    return records_to_create


def _execute_batch_operations(
    records_to_update: list,
    records_to_create: list,
    records_to_delete: list,
    bulk_size: int,
) -> None:
    """Execute all database operations in batches with proper transaction handling."""

    try:
        # Batch delete
        if records_to_delete:
            with transaction.atomic():
                IndexData.objects.filter(id__in=records_to_delete).delete()
                print(f"Deleted {len(records_to_delete)} records")
                logger.info(f"Deleted {len(records_to_delete)} records")

        # Batch update
        if records_to_update:
            with transaction.atomic():
                IndexData.objects.bulk_update(
                    records_to_update,
                    fields=[
                        "lastmod",
                        "size",
                        "duration",
                        "file_sha256",
                        "unique_sha256",
                        "home_directory",
                    ],
                    batch_size=bulk_size,
                )
                logger.info(f"Updated {len(records_to_update)} records")

        # Batch create
        if records_to_create:
            with transaction.atomic():
                IndexData.objects.bulk_create(
                    records_to_create,
                    batch_size=bulk_size,
                    ignore_conflicts=True,  # Handle duplicates gracefully
                )
                logger.info(f"Created {len(records_to_create)} records")

    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        raise


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
    files = sum(1 for entry in fs_entries.values() if entry.is_file())
    dirs = len(fs_entries) - files
    return (files, dirs)


def process_filedata(
    fs_entry: Path, directory_id: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """
    Process a file system entry and return a dictionary with file metadata.

    Args:
        fs_entry: Path object representing the file or directory
        directory_id: Optional directory identifier for the parent directory

    Returns:
        Dictionary containing file metadata or None if processing fails
    """
    try:
        # Initialize the record dictionary
        record = {
            "home_directory": directory_id,
            "name": fs_entry.name.title().strip(),  # More efficient than os.path.split
            "is_animated": False,
            "file_sha256": None,
            "unique_sha256": None,
            "duration": None,
        }

        # Get file extension and determine if it's a directory
        fileext = fs_entry.suffix.lower() if fs_entry.suffix else ".none"
        is_dir = fs_entry.is_dir()

        if is_dir:
            sync_database_disk(str(fs_entry))
            return None

        elif not fileext or fileext == ".":
            fileext = ".none"

        # Check if filetype exists (assuming this function is available)
        if not filetype_models.filetypes.filetype_exists_by_ext(fileext):
            print(f"Can't match fileext '{fileext}' with filetypes")
            return None

        # Get file stats efficiently
        try:
            fs_stat = fs_entry.stat()
            record.update(
                {
                    "size": fs_stat.st_size,
                    "lastmod": fs_stat.st_mtime,
                    "lastscan": time.time(),
                    "filetype": filetype_models.filetypes.return_filetype(
                        fileext=fileext
                    ),
                }
            )
        except (OSError, IOError) as e:
            print(f"Error getting file stats for {fs_entry}: {e}")
            return None

        # Handle link files
        filetype = record["filetype"]
        # if hasattr(filetype, "is_link") and filetype.is_link:
        if filetype.is_link:
            if filetype.fileext == ".link":
                try:
                    _, redirect = (
                        record["name"].lower().split("*", 1)
                    )  # Limit split to 1
                    redirect = (
                        redirect.replace("'", "")
                        .replace("__", "/")
                        .rsplit(".", 1)[0]  # More efficient than split + slice
                    )
                    record["fqpndirectory"] = f"/{redirect}"
                except ValueError:
                    print(f"Invalid link format in file: {record['name']}")
                    return None

            elif filetype.fileext == ".alias":
                try:
                    alias_path = (
                        resolve_alias_path(str(fs_entry)).lower().rstrip(os.sep)
                        + os.sep
                    )
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(
                        str(fs_entry)
                    )

                    # Assuming IndexDirs.search_for_directory is available
                    found, directory_linking_to = IndexDirs.search_for_directory(
                        fqpn_directory=alias_path
                    )
                    if not found:
                        print(
                            f"Directory {alias_path} not found in database, skipping link."
                        )
                        return None
                    record["virtual_directory"] = directory_linking_to

                except ValueError as e:
                    print(f"Error resolving alias: {e}")
                    return None
        else:
            # Calculate file hashes for non-link files
            try:
                # Assuming get_file_sha is a separate function now
                record["file_sha256"], record["unique_sha256"] = get_file_sha(
                    str(fs_entry)
                )
            except Exception as e:
                print(f"Error calculating SHA for {fs_entry}: {e}")
                # Continue processing even if SHA calculation fails

        # Handle animated GIF detection
        if hasattr(filetype, "is_image") and filetype.is_image and fileext == ".gif":
            try:
                with Image.open(fs_entry) as img:
                    record["is_animated"] = getattr(img, "is_animated", False)
            except (AttributeError, IOError, OSError) as e:
                print(f"Error checking animation for {fs_entry}: {e}")
                record["is_animated"] = False

        return record

    except Exception as e:
        print(f"Unexpected error processing {fs_entry}: {e}")
        return None


def sync_database_disk(directoryname: str) -> Optional[bool]:
    """
    Synchronize database entries with filesystem for a given directory.

    Args:
        directoryname: The directory path to synchronize

    Returns:
        None on completion, bool on early exit conditions
    """
    print("Starting ...  Syncing database with disk for directory:", directoryname)
    start_time = time.perf_counter()
    BULK_SIZE = 100  # Increased from 50 for better batch performance

    #    try:
    # Normalize directory path
    if directoryname in [os.sep, r"/"]:
        directoryname = settings.ALBUMS_PATH

    dirpath = normalize_fqpn(os.path.abspath(directoryname.title().strip()))
    directory_sha256 = get_dir_sha(dirpath)

    # Find or create directory record
    dirpath_info, is_cached = _get_or_create_directory(directory_sha256, dirpath)
    if dirpath_info is None:
        return False

    # Early return if cached
    if is_cached:
        print(f"Directory {dirpath} is already cached, skipping sync.")
        return None

    print(f"Rescanning directory: {dirpath}")

    # Get filesystem entries
    success, fs_entries = return_disk_listing(dirpath)
    if not success:
        print("File path doesn't exist, removing from cache and database.")
        return _handle_missing_directory(dirpath_info)

    # Batch process all operations
    _sync_directories(dirpath_info, fs_entries)
    _sync_files(dirpath_info, fs_entries, BULK_SIZE)

    # Cache the result
    Cache_Storage.add_to_cache(DirName=dirpath)
    logger.info(f"Cached directory: {dirpath}")
    print("Elapsed Time (Sync Database Disk): ", time.perf_counter() - start_time)
    return None

    # except Exception as e:
    #     print(f"Error syncing directory {directoryname}: {e}")
    #     logger.error(f"Error syncing directory {directoryname}: {e}")
    #     return False


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


from Foundation import (  # NSData,; NSError,
    NSURL,
    NSURLBookmarkResolutionWithoutMounting,
    NSURLBookmarkResolutionWithoutUI,
)


def resolve_alias_path(alias_path: str) -> str:
    """Given a path to a macOS alias file, return the resolved path to the original file"""
    options = NSURLBookmarkResolutionWithoutUI | NSURLBookmarkResolutionWithoutMounting
    alias_url = NSURL.fileURLWithPath_(alias_path)
    bookmark, error = NSURL.bookmarkDataWithContentsOfURL_error_(alias_url, None)
    if error:
        raise ValueError(f"Error creating bookmark data: {error}")

    resolved_url, is_stale, error = (
        NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(
            bookmark, options, None, None, None
        )
    )
    if error:
        raise ValueError(f"Error resolving bookmark data: {error}")

    resolved_url = str(resolved_url.path()).strip().lower()
    # album_path = f"{settings.ALBUMS_PATH}{os.sep}albums{os.sep}"
    for disk_path, replacement_path in settings.ALIAS_MAPPING.items():
        if resolved_url.startswith(disk_path.lower()):
            resolved_url = (
                resolved_url.replace(disk_path.lower(), replacement_path.lower())
                + os.sep
            )
            return resolved_url
    return resolved_url
