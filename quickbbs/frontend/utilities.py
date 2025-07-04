"""
Utilities for QuickBBS, the python edition.
"""

import logging

# import multiprocessing
import os
import os.path

# import stat
import time
import urllib.parse

# from datetime import timedelta
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import filetypes.models as filetype_models
from cache_watcher.models import Cache_Storage, get_dir_sha
from django.conf import settings
from django.db import transaction
from django.db import connection


# from django.db.models import Count, F, OuterRef, Subquery, Value
# from django.db.utils import IntegrityError
# from django.utils.html import format_html
from frontend.file_listings import return_disk_listing
from PIL import Image
from thumbnails.video_thumbnails import _get_video_info

from quickbbs.common import get_file_sha, normalize_fqpn

# from quickbbs.logger import log
from quickbbs.models import IndexData, IndexDirs

# from thumbnails.image_utils import movie_duration
# from thumbnails.models import ThumbnailFiles


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
) -> Tuple[Optional[object], bool]:
    """Get or create directory record and check cache status."""
    found, dirpath_info = IndexDirs.search_for_directory_by_sha(directory_sha256)
    print("Directory found:", found, dirpath_info)
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


def _handle_missing_directory(directory_sha256: str, dirpath_info: object) -> None:
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
    return None


def _sync_directories(dirpath_info: object, fs_entries: Dict) -> None:
    """Synchronize database directories with filesystem."""
    # Get all database directories in one query
    print("Synchronizing directories...")
    logger.info("Synchronizing directories...")
    current_path = dirpath_info.fqpndirectory
    db_directories = set(
        dirpath_info.dirs_in_dir().values_list("fqpndirectory", flat=True)
    )
    # Get filesystem directory names
    fs_directory_names = {
        entry.name.strip().lower() for entry in fs_entries.values() if entry.is_dir()
    }

    # Find directories to delete (in DB but not in filesystem)
    directories_to_delete = []
    for fqpn in db_directories:
        dir_name = str(Path(fqpn).name).strip().lower()
        if dir_name not in fs_directory_names:
            directories_to_delete.append(fqpn)

    # Process new directories (in filesystem but not in DB)
    directories_to_create = []
    for dir_name in fs_directory_names:
        dir_name = os.path.join(current_path, dir_name) + os.sep
        if dir_name not in db_directories:
            directories_to_create.append(dir_name)

    # Batch delete directories
    if directories_to_delete:
        print(f"Directories to delete: {len(directories_to_delete)}")
        logger.info(f"Directories to delete: {len(directories_to_delete)}")
        for fqpn in directories_to_delete:
            try:
                IndexDirs.delete_directory(fqpn_directory=fqpn)
            except Exception as e:
                logger.error(f"Error deleting directory {fqpn}: {e}")

    # Batch create directories
    if directories_to_create:
        print(f"Directories to create: {len(directories_to_create)}")
        logger.info(f"Directories to create: {len(directories_to_create)}")
        for dir_name in directories_to_create:
            try:
                IndexDirs.add_directory(fqpn_directory=dir_name)
            except Exception as e:
                logger.error(f"Error creating directory {dir_name}: {e}")


def _sync_files(dirpath_info: object, fs_entries: Dict, bulk_size: int) -> None:
    """Synchronize database files with filesystem."""
    # Get all database files in one optimized query
    db_files = {
        file_record.name: file_record
        for file_record in dirpath_info.files_in_dir()
        .select_related("filetype")
        .only(
            "name",
            "lastmod",
            "size",
            "file_sha256",
            "unique_sha256",
            "duration",
            "filetype",
        )
    }

    fs_file_names = {
        name: entry for name, entry in fs_entries.items() if not entry.is_dir()
    }

    # Process updates and deletions
    records_to_update = []
    records_to_delete = []

    for db_name, db_record in db_files.items():
        if db_name not in fs_file_names:
            # File exists in DB but not in filesystem
            print("Deleting ",db_record.name)
            records_to_delete.append(db_record.id)
        else:
            # File exists in both - check for updates
            updated_record = _check_file_updates(db_record, fs_file_names[db_name])
            if updated_record:
                records_to_update.append(updated_record)

    # Process new files
    records_to_create = _process_new_files(dirpath_info, fs_file_names, db_files)

    # Execute batch operations
    _execute_batch_operations(
        records_to_update, records_to_create, records_to_delete, bulk_size
    )


def _check_file_updates(db_record: object, fs_entry: Path) -> Optional[object]:
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


def _process_new_files(
    dirpath_info: object, fs_file_names: Dict, db_files: Dict
) -> List[object]:
    """Process files that exist in filesystem but not in database."""
    records_to_create = []

    for fs_name, fs_entry in fs_file_names.items():
        test_name = fs_entry.name.title().replace("//", "/").strip()

        if test_name not in db_files:
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
                record, created = IndexData.objects.get_or_create(
                    unique_sha256=filedata.get("unique_sha256"), defaults=filedata
                )

                if created:
                    record.home_directory = dirpath_info
                    records_to_create.append(record)

            except Exception as e:
                logger.error(f"Error processing new file {fs_entry}: {e}")
                continue

    return records_to_create


def _execute_batch_operations(
    records_to_update: List,
    records_to_create: List,
    records_to_delete: List,
    bulk_size: int,
) -> None:
    """Execute all database operations in batches with proper transaction handling."""

    try:
        with transaction.atomic():
            # Batch delete
            if records_to_delete:
                IndexData.objects.filter(id__in=records_to_delete).delete()
                print(f"Deleted {len(records_to_delete)} records")
                logger.info(f"Deleted {len(records_to_delete)} records")

            # Batch update
            if records_to_update:
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
                # Process in chunks to avoid memory issues
                # for i in range(0, len(records_to_create), bulk_size):
                #     chunk = records_to_create[i : i + bulk_size]
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

    def isfile(entry):
        return entry.is_file()

    files = len(list(filter(isfile, fs_entries.values())))
    dirs = len(fs_entries) - files
    return (files, dirs)


def process_filedata(
    fs_entry: Path, directory_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
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
            fileext = ".dir"
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

        # Handle directories
        if is_dir:
            # Assuming sync_database_disk is defined elsewhere
            sync_database_disk(str(fs_entry))
            return None

        # Handle link files
        filetype = record["filetype"]
        #if hasattr(filetype, "is_link") and filetype.is_link:
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
                print("Alias File Found - ", fs_entry.name)
                try:
                    alias_path = (
                        resolve_alias_path(str(fs_entry)).lower().rstrip(os.sep)
                        + os.sep
                    )
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(
                    str(fs_entry)
                )
                    print(f"Resolved alias path: {alias_path}")

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
    BULK_SIZE = 100  # Increased from 50 for better batch performance

    try:
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
            return _handle_missing_directory(directory_sha256, dirpath_info)

        # Batch process all operations
        _sync_directories(dirpath_info, fs_entries)
        _sync_files(dirpath_info, fs_entries, BULK_SIZE)

        # Cache the result
        Cache_Storage.add_to_cache(DirName=dirpath)
        logger.info(f"Cached directory: {dirpath}")

        return None

    except Exception as e:
        print(f"Error syncing directory {directoryname}: {e}")
        logger.error(f"Error syncing directory {directoryname}: {e}")
        return False
    print("End Sync")


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
    album_path = f"{settings.ALBUMS_PATH}{os.sep}albums{os.sep}"
    for disk_path, replacement_path in settings.ALIAS_MAPPING.items():
        if resolved_url.startswith(disk_path.lower()):
            resolved_url = resolved_url.replace(disk_path.lower(), replacement_path.lower()) + os.sep
            return resolved_url
    return resolved_url
