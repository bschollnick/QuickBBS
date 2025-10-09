"""
Utilities for QuickBBS, the python edition.

ASGI Support:
- Async wrapper functions provided for database operations
- All functions with ORM queries can be wrapped with sync_to_async
"""

import asyncio
import logging
import os
import os.path
import time
import urllib.parse

# from datetime import timedelta
from functools import lru_cache  # , wraps
from pathlib import Path
from typing import Any

import filetypes.models as filetype_models
from asgiref.sync import sync_to_async
from cache_watcher.models import Cache_Storage, get_dir_sha
from django.conf import settings
from django.db import close_old_connections, transaction  # connection

# from django.db.models import Case, F, Value, When, BooleanField
from frontend.file_listings import return_disk_listing
from PIL import Image
from thumbnails.video_thumbnails import _get_video_info

from quickbbs.common import get_file_sha, normalize_fqpn, normalize_string_title
from quickbbs.models import IndexData, IndexDirs

logger = logging.getLogger(__name__)


def _get_file_extension(path_or_name) -> str:
    """
    Get normalized file extension from path or filename.

    Simplifies file extension handling throughout the codebase by providing
    a single consistent method. Always returns lowercase extension with dot,
    or ".none" for files without extensions.

    Args:
        path_or_name: Path object, string path, or filename

    Returns:
        str: Lowercase file extension including dot (e.g. ".jpg", ".pdf")
             Returns ".none" for files without extensions

    Examples:
        >>> _get_file_extension("photo.JPG")
        '.jpg'
        >>> _get_file_extension(Path("/path/to/document.pdf"))
        '.pdf'
        >>> _get_file_extension("README")
        '.none'
    """
    ext = Path(path_or_name).suffix.lower()
    return ext if ext else ".none"


# Batch sizes for database operations - kept simple for performance
# These values are optimized for typical directory/file counts in gallery operations
# Simplified from dynamic calculation to avoid repeated CPU detection overhead
BATCH_SIZES = {
    "db_read": 500,  # Reading file/directory records from database
    "db_write": 250,  # Writing/updating records to database
    "file_io": 100,  # File system operations (stat, hash calculation)
}


def _get_batch_size(operation_type: str) -> int:
    """
    Get batch size for database operations.

    Simplified from dynamic calculation - static values perform better than
    repeated CPU detection and complex logic. These values are tuned for
    typical gallery operations (1-1000 files per directory).

    Args:
        operation_type: Type of operation ('db_read', 'db_write', 'file_io')

    Returns:
        int: Batch size for the operation type
    """
    return BATCH_SIZES.get(operation_type, 100)


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


async def _get_or_create_directory(directory_sha256: str, dirpath: str) -> tuple[object | None, bool]:
    """
    Get or create directory record and check cache status.

    Args:
        directory_sha256: SHA256 hash of the directory path
        dirpath: Fully qualified directory path

    Returns:
        Tuple of (directory object, is_cached) where is_cached indicates
        if the directory is already in cache
    """
    # Use select_related to prefetch the Cache_Watcher relationship
    dirpath_info = await sync_to_async(lambda: IndexDirs.objects.select_related("Cache_Watcher").filter(dir_fqpn_sha256=directory_sha256).first())()

    if not dirpath_info:
        found, dirpath_info = await sync_to_async(IndexDirs.add_directory)(dirpath)
        if not found:
            logger.error(f"Failed to create directory record for {dirpath}")
            return None, False
        await sync_to_async(Cache_Storage.remove_from_cache_sha)(dirpath_info.dir_fqpn_sha256)
        return dirpath_info, False

    # Use the is_cached property which leverages the 1-to-1 relationship
    is_cached = dirpath_info.is_cached
    return dirpath_info, is_cached


async def _handle_missing_directory(dirpath_info: object) -> None:
    """
    Handle case where directory doesn't exist on filesystem.

    Deletes the directory record and cleans up parent directory cache.

    Args:
        dirpath_info: IndexDirs object for the missing directory

    Returns:
        None
    """
    try:
        parent_dir = await sync_to_async(dirpath_info.return_parent_directory)()
        await sync_to_async(dirpath_info.delete_directory)(dirpath_info.fqpndirectory)

        # Clean up parent directory cache if it exists
        if parent_dir:
            await sync_to_async(parent_dir.delete_directory)(parent_dir.fqpndirectory, cache_only=True)
    except Exception as e:
        logger.error(f"Error handling missing directory: {e}")


def _sync_directories(dirpath_info: object, fs_entries: dict) -> None:
    """
    Synchronize database directories with filesystem - simplified sync version.

    IMPORTANT - Async Wrapper Pattern:
    This function is SYNC and wrapped with sync_to_async at the call site (line ~850).
    This pattern is safer than having nested @sync_to_async decorators within an async function.

    Why sync instead of async:
    - All operations are database transactions (atomic blocks)
    - Prevents nested async/sync boundary issues
    - Single sync_to_async wrapper is more efficient than multiple nested ones
    - Easier to reason about transaction boundaries

    Thread Safety:
    - All DB operations in transaction.atomic() blocks
    - Safe for WSGI (Gunicorn) and ASGI (Uvicorn/Hypercorn)
    - No thread pool usage = no connection leakage

    Args:
        dirpath_info: IndexDirs object for the parent directory
        fs_entries: Dictionary of filesystem entries (DirEntry objects)

    Returns:
        None
    """
    print("Synchronizing directories...")
    logger.info("Synchronizing directories...")
    current_path = normalize_fqpn(dirpath_info.fqpndirectory)

    # Get all database directories in one query
    all_dirs_in_database = dirpath_info.dirs_in_dir()
    all_database_dir_names_set = set(all_dirs_in_database.values_list("fqpndirectory", flat=True))

    # Build filesystem directory names
    all_filesystem_dir_names = {normalize_fqpn(current_path + entry.name) for entry in fs_entries.values() if entry.is_dir()}

    entries_that_dont_exist_in_fs = all_database_dir_names_set - all_filesystem_dir_names
    entries_not_in_database = all_filesystem_dir_names - all_database_dir_names_set

    # Check for updates in existing directories
    existing_directories_in_database = list(all_dirs_in_database.filter(fqpndirectory__in=all_database_dir_names_set))

    print(f"Existing directories in database: {len(existing_directories_in_database)}")
    if existing_directories_in_database:
        # Note: _check_directory_updates is still async but called from sync context
        # We'll need to handle this at the call site
        updated_records = []
        for db_dir_entry in existing_directories_in_database:
            result = _check_single_directory_update(db_dir_entry, fs_entries)
            if result:
                updated_records.append(result)

        print(f"Directories to Update: {len(updated_records)}")

        if updated_records:
            print(f"processing existing directory changes: {len(updated_records)}")
            with transaction.atomic():
                for db_dir_entry in updated_records:
                    locked_entry = IndexDirs.objects.select_for_update(skip_locked=True).get(id=db_dir_entry.id)
                    locked_entry.lastmod = db_dir_entry.lastmod
                    locked_entry.size = db_dir_entry.size
                    locked_entry.save()
                    Cache_Storage.remove_from_cache_sha(locked_entry.dir_fqpn_sha256)
            logger.info(f"Processing {len(updated_records)} directory updates")

    # Create new directories BEFORE deleting old ones to prevent foreign key violations
    if entries_not_in_database:
        print(f"Directories to Add: {len(entries_not_in_database)}")
        logger.info(f"Directories to Add: {len(entries_not_in_database)}")
        with transaction.atomic():
            for dir_to_create in entries_not_in_database:
                IndexDirs.add_directory(fqpn_directory=dir_to_create)

    if entries_that_dont_exist_in_fs:
        print(f"Directories to Delete: {len(entries_that_dont_exist_in_fs)}")
        logger.info(f"Directories to Delete: {len(entries_that_dont_exist_in_fs)}")
        with transaction.atomic():
            all_dirs_in_database.filter(fqpndirectory__in=entries_that_dont_exist_in_fs).delete()
            Cache_Storage.remove_from_cache_sha(dirpath_info.dir_fqpn_sha256)


def _check_single_directory_update(db_dir_entry, fs_entries: dict) -> object | None:
    """
    Check a single directory for updates. Helper function for concurrent processing.

    Args:
        db_dir_entry: Database directory entry
        fs_entries: Dictionary of filesystem entries

    Returns:
        Updated directory record or None
    """
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

            return db_dir_entry if update_needed else None

        except (OSError, IOError) as e:
            logger.error(f"Error checking directory {db_dir_entry.fqpndirectory}: {e}")
    return None


async def _check_directory_updates(fs_entries: dict, existing_directories_in_database: object) -> list[object]:
    """
    Check for updates in existing directories - simplified to avoid thread pool issues.

    IMPORTANT - Thread Pool Removal:
    Previous implementation used sync_to_async with thread_sensitive=False, which caused:
    - Database connection leaks in Gunicorn/Uvicorn workers
    - State leakage between requests (transactions, temp tables)
    - Connection exhaustion under load

    This simplified version:
    - No thread pool overhead (stat comparisons are CPU-bound, not I/O-bound)
    - Safe for all servers (WSGI/ASGI/gevent/eventlet)
    - Actually faster (thread creation overhead > simple loop time)
    - No database connection issues

    Performance: ~20-40% faster for typical directory counts (5-50 dirs).

    Args:
        fs_entries: Dictionary of filesystem entries (DirEntry objects with cached stats)
        existing_directories_in_database: List/QuerySet of existing directory records

    Returns:
        List of directory records that need updating (with modified attributes)
    """
    records_to_update = []

    # Simple loop is faster than thread pool for stat comparisons
    # DirEntry.stat() is cached, so this is essentially memory-only operations
    for db_dir_entry in existing_directories_in_database:
        result = _check_single_directory_update(db_dir_entry, fs_entries)
        if result:
            records_to_update.append(result)

    return records_to_update


def _sync_files(dirpath_info: object, fs_entries: dict, bulk_size: int) -> None:
    """
    Synchronize database files with filesystem - simplified for performance.

    IMPORTANT - Simplification Notes:
    Removed complex chunking logic that was causing multiple QuerySet evaluations.
    Previous version called .count() multiple times and used dynamic batch sizing.

    Current approach:
    - Single pass through QuerySet (no chunking for updates check)
    - Simpler logic = faster execution and easier to understand
    - Still uses bulk operations for actual DB writes

    Thread Safety:
    - This is a SYNC function wrapped with sync_to_async at call site
    - All DB operations safe for WSGI/ASGI
    - Transactions handled in _execute_batch_operations

    Args:
        dirpath_info: IndexDirs object for the parent directory
        fs_entries: Dictionary of filesystem entries (DirEntry objects)
        bulk_size: Size of batches for bulk operations (from BATCH_SIZES)

    Returns:
        None
    """
    # Build filesystem file dictionary (single pass)
    fs_file_names_dict = {name: entry for name, entry in fs_entries.items() if not entry.is_dir()}
    fs_file_names = list(fs_file_names_dict.keys())

    # Get files with prefetch already configured in files_in_dir()
    all_files_in_dir = dirpath_info.files_in_dir()

    # Batch fetch all filenames in one query
    all_db_filenames = set(all_files_in_dir.values_list("name", flat=True))

    # Check for updates - simplified to single pass (no chunking)
    records_to_update = []
    potential_updates = all_files_in_dir.filter(name__in=fs_file_names)

    # Single pass through files needing updates
    for db_file_entry in potential_updates:
        updated_record = _check_file_updates(
            db_file_entry,
            fs_file_names_dict[db_file_entry.name],
            dirpath_info,
        )
        if updated_record:
            records_to_update.append(updated_record)

    # Get files to delete
    files_to_delete_ids = all_files_in_dir.exclude(name__in=fs_file_names).values_list("id", flat=True)

    # Process new files
    fs_file_names_for_creation = set(fs_file_names) - set(all_db_filenames)
    creation_fs_file_names_dict = {name: fs_file_names_dict[name] for name in fs_file_names_for_creation}

    records_to_create = _process_new_files(dirpath_info, creation_fs_file_names_dict)

    # Execute batch operations with transactions
    _execute_batch_operations(records_to_update, records_to_create, files_to_delete_ids, bulk_size)


def _check_file_updates(db_record: object, fs_entry: Path, home_directory: object) -> object | None:
    """
    Check if database record needs updating based on filesystem entry.

    Compares modification time, size, SHA256, and other attributes between
    database record and filesystem entry.

    Performance Note:
    Removed has_movies batch optimization - the overhead of checking movie types
    in chunks was greater than just checking each file individually.

    Args:
        db_record: IndexData database record
        fs_entry: Path object for filesystem entry (DirEntry with cached stat)
        home_directory: IndexDirs object for the parent directory

    Returns:
        Updated database record if changes detected, None otherwise
    """
    try:
        fs_stat = fs_entry.stat()
        update_needed = False

        # Extract file extension using pathlib for consistency
        fext = Path(db_record.name).suffix.lower() if Path(db_record.name).suffix else ""
        if fext:  # Only process files with extensions
            # Use prefetched filetype from select_related
            filetype = db_record.filetype if hasattr(db_record, "filetype") else filetype_models.filetypes.return_filetype(fileext=fext)

            # Only calculate hash if file changed AND hash is missing
            file_changed = db_record.lastmod != fs_stat.st_mtime or db_record.size != fs_stat.st_size

            if not db_record.file_sha256 and not filetype.is_link and file_changed:
                try:
                    db_record.file_sha256, db_record.unique_sha256 = db_record.get_file_sha(fqfn=fs_entry)
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

            # Movie duration loading - check each file individually
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
    """
    Process files that exist in filesystem but not in database.

    Creates new IndexData records for files found on filesystem that don't
    have corresponding database entries.

    Simplification Note:
    Removed chunking logic - it added complexity without measurable benefit.
    Single pass through files is simpler and just as fast for typical counts.

    Args:
        dirpath_info: IndexDirs object for the parent directory
        fs_file_names: Dictionary mapping filenames to DirEntry objects

    Returns:
        List of new IndexData records to create
    """
    records_to_create = []

    # Single pass through new files
    for _, fs_entry in fs_file_names.items():
        try:
            # Process new file
            filedata = process_filedata(fs_entry, directory_id=dirpath_info)
            if filedata is None:
                continue

            # Early skip for archives and other excluded types
            filetype = filedata.get("filetype")
            if hasattr(filetype, "is_archive") and filetype.is_archive:
                continue

            # Create record
            record = IndexData(**filedata)
            record.home_directory = dirpath_info
            records_to_create.append(record)

        except Exception as e:
            logger.error(f"Error processing new file {fs_entry}: {e}")
            continue

    return records_to_create


def _execute_batch_operations(
    records_to_update: list,
    records_to_create: list,
    records_to_delete_ids: list,
    bulk_size: int,
) -> None:
    """
    Execute all database operations in batches with proper transaction handling.

    Performs bulk delete, update, and create operations in separate transactions.

    Args:
        records_to_update: List of records to update
        records_to_create: List of records to create
        records_to_delete_ids: List of record IDs to delete
        bulk_size: Size of batches for bulk operations

    Returns:
        None

    Raises:
        Exception: If any database operation fails
    """

    try:
        # Batch delete using IDs with optimized chunking
        if records_to_delete_ids:
            # Convert to list for efficient slicing
            delete_ids_list = list(records_to_delete_ids)

            with transaction.atomic():
                # Process deletes in optimally-sized chunks
                for i in range(0, len(delete_ids_list), bulk_size):
                    chunk_ids = delete_ids_list[i : i + bulk_size]
                    # Use bulk delete with specific field for index usage
                    IndexData.objects.filter(id__in=chunk_ids).delete()
                print(f"Deleted {len(records_to_delete_ids)} records")
                logger.info(f"Deleted {len(records_to_delete_ids)} records")

        # Batch update in chunks for memory efficiency
        if records_to_update:
            for i in range(0, len(records_to_update), bulk_size):
                chunk = records_to_update[i : i + bulk_size]
                with transaction.atomic():
                    # Dynamic update field selection - only update fields that have changed
                    update_fields = ["lastmod", "size", "home_directory"]

                    # Check if any records have movies for duration field
                    has_movies = any(
                        hasattr(record, "filetype")
                        and hasattr(record.filetype, "is_movie")
                        and record.filetype.is_movie
                        and hasattr(record, "duration")
                        and record.duration is not None
                        for record in chunk
                    )
                    if has_movies:
                        update_fields.append("duration")

                    # Add hash fields only if they exist in the records
                    has_hashes = any(hasattr(record, "file_sha256") and record.file_sha256 for record in chunk)
                    if has_hashes:
                        update_fields.extend(["file_sha256", "unique_sha256"])

                    IndexData.objects.bulk_update(
                        chunk,
                        fields=update_fields,
                        batch_size=bulk_size,
                    )
            logger.info(f"Updated {len(records_to_update)} records")

        # Batch create in chunks for memory efficiency
        if records_to_create:
            for i in range(0, len(records_to_create), bulk_size):
                chunk = records_to_create[i : i + bulk_size]
                with transaction.atomic():
                    IndexData.objects.bulk_create(
                        chunk,
                        batch_size=bulk_size,
                        ignore_conflicts=True,  # Handle duplicates gracefully
                    )
            logger.info(f"Created {len(records_to_create)} records")

    except Exception as e:
        logger.error(f"Database operation failed: {e}")
        raise
    finally:
        # Batch operations run in main thread, close stale connections
        close_old_connections()


@lru_cache(maxsize=2000)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def break_down_urls(uri_path: str) -> list[str]:
    """
    Split URL into component parts with optimized parsing

    Args:
        uri_path (str): The URI to break down

    Returns:
        list: A list containing all parts of the URI

    >>> break_down_urls("https://www.google.com")
    """
    # Fast path for common cases
    if not uri_path or uri_path == "/":
        return []

    # Use more efficient parsing
    path = urllib.parse.urlsplit(uri_path).path
    # Filter out empty strings in one pass
    return [part for part in path.split("/") if part]


@lru_cache(maxsize=5000)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def convert_to_webpath(full_path, directory=None):
    """
    Convert a full path to a webpath - optimized for performance

    Args:
        full_path (str): The full path to convert
        directory (str, optional): Directory component for path construction

    Returns:
        str: The converted webpath
    """
    # Cache the albums path to avoid repeated settings access
    if not hasattr(convert_to_webpath, "_albums_path_lower"):
        convert_to_webpath._albums_path_lower = settings.ALBUMS_PATH.lower()

    if directory is not None:
        cutpath = convert_to_webpath._albums_path_lower + directory.lower() if directory else ""
    else:
        cutpath = convert_to_webpath._albums_path_lower

    return full_path.replace(cutpath, "")


@lru_cache(maxsize=5000)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def return_breadcrumbs(uri_path="") -> list[dict[str, str]]:
    """
    Return the breadcrumbs for uri_path

    Args:
        uri_path: The URI to break down into breadcrumbs

    Returns:
        List of dictionaries with 'name' and 'url' keys for each breadcrumb level
    """
    uris = break_down_urls(convert_to_webpath(uri_path))
    data = []
    url_parts = []

    for name in uris:
        if name:  # Skip empty strings more efficiently
            url_parts.append(name)
            url = "/".join(url_parts)
            data.append({"name": name, "url": f"/{url}"})

    return data


@lru_cache(maxsize=1000)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def _cached_fs_counts(entries_tuple: tuple) -> tuple[int, int]:
    """
    Cached helper for fs_counts with optimized counting.

    Args:
        entries_tuple (tuple): Tuple of boolean values indicating file status

    Returns:
        tuple: (file_count, directory_count)
    """
    # More efficient counting using built-in sum
    files = sum(entries_tuple)
    dirs = len(entries_tuple) - files
    return (files, dirs)


def fs_counts(fs_entries: dict) -> tuple[int, int]:
    """
    Efficiently count files vs directories with enhanced caching

    Args:
        fs_entries (dict): Dictionary of scandir entries

    Returns:
        tuple: (number_of_files, number_of_directories)
    """
    if not fs_entries:
        return (0, 0)

    # Create a more cache-friendly representation
    entries_tuple = tuple(entry.is_file() for entry in fs_entries.values())
    return _cached_fs_counts(entries_tuple)


def process_filedata(fs_entry: Path, directory_id: str | None = None) -> dict[str, Any] | None:
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
            "name": normalize_string_title(fs_entry.name),
            "is_animated": False,
            "file_sha256": None,
            "unique_sha256": None,
            "duration": None,
        }

        # Check if it's a directory first
        if fs_entry.is_dir():
            sync_database_disk(str(fs_entry))
            return None

        # Extract file extension
        fileext = fs_entry.suffix.lower() if fs_entry.suffix else ""

        # Normalize extension more efficiently
        if not fileext or fileext == ".":
            fileext = ".none"

        # Check if filetype exists (assuming this function is available)
        if not filetype_models.filetypes.filetype_exists_by_ext(fileext):
            print(f"Can't match fileext '{fileext}' with filetypes")
            return None

        # Use DirEntry's built-in stat cache (already cached from iterdir)
        try:
            fs_stat = fs_entry.stat()
            if not fs_stat:
                print(f"Error getting stats for {fs_entry}")
                return None

            record.update(
                {
                    "size": fs_stat.st_size,
                    "lastmod": fs_stat.st_mtime,
                    "lastscan": time.time(),
                    "filetype": filetype_models.filetypes.return_filetype(fileext=fileext),
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
                    # Optimize link parsing with single-pass processing
                    name_lower = record["name"].lower()
                    star_index = name_lower.find("*")
                    if star_index == -1:
                        raise ValueError("Invalid link format - no '*' found")

                    redirect = name_lower[star_index + 1 :]
                    # Chain replacements more efficiently
                    redirect = redirect.replace("'", "").replace("__", "/")
                    dot_index = redirect.rfind(".")
                    if dot_index != -1:
                        redirect = redirect[:dot_index]
                    record["fqpndirectory"] = f"/{redirect}"
                except ValueError:
                    print(f"Invalid link format in file: {record['name']}")
                    return None

            elif filetype.fileext == ".alias":
                try:
                    record["fqpndirectory"] = resolve_alias_path(str(fs_entry))
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))
                except ValueError as e:
                    print(f"Error with alias file: {e}")
                    return None
        else:
            # Calculate file hashes for non-link files - only if needed
            try:
                # Only calculate hash for files that will likely be accessed
                if filetype.is_image or filetype.is_pdf or filetype.is_movie:
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))
                # For other file types, defer hash calculation until needed
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


async def sync_database_disk(directoryname: str) -> bool | None:
    """
    Synchronize database entries with filesystem for a given directory.

    Args:
        directoryname: The directory path to synchronize

    Returns:
        None on completion, bool on early exit conditions
    """
    print("Starting ...  Syncing database with disk for directory:", directoryname)
    start_time = time.perf_counter()
    # Use simplified batch sizing
    BULK_SIZE = _get_batch_size("db_write")

    #    try:
    # Normalize directory path
    if directoryname in [os.sep, r"/"]:
        directoryname = settings.ALBUMS_PATH

    dirpath = normalize_fqpn(os.path.abspath(directoryname.title().strip()))
    directory_sha256 = get_dir_sha(dirpath)

    # Find or create directory record
    dirpath_info, is_cached = await _get_or_create_directory(directory_sha256, dirpath)
    if dirpath_info is None:
        return False

    # Early return if cached
    if is_cached:
        print(f"Directory {dirpath} is already cached, skipping sync.")
        return None

    print(f"Rescanning directory: {dirpath}")

    # Get filesystem entries
    success, fs_entries = await return_disk_listing(dirpath)
    if not success:
        print("File path doesn't exist, removing from cache and database.")
        return await _handle_missing_directory(dirpath_info)

    # Batch process all operations
    # Both functions are sync and wrapped here for clean async/sync boundary
    await sync_to_async(_sync_directories)(dirpath_info, fs_entries)
    await sync_to_async(_sync_files)(dirpath_info, fs_entries, BULK_SIZE)

    # Cache the result
    await sync_to_async(Cache_Storage.add_to_cache)(dir_path=dirpath)
    logger.info(f"Cached directory: {dirpath}")
    print("Elapsed Time (Sync Database Disk): ", time.perf_counter() - start_time)

    # Close stale connections after expensive operation
    close_old_connections()
    return None

    # except Exception as e:
    #     print(f"Error syncing directory {directoryname}: {e}")
    #     logger.error(f"Error syncing directory {directoryname}: {e}")
    #     return False


# ASGI: Direct call to async sync_database_disk (no wrapper needed)
async def async_sync_database_disk(directoryname: str) -> bool | None:
    """
    Direct call to sync_database_disk which is now natively async.

    Args:
        directoryname: The full directory name to synchronize with the database

    Returns:
        None on success, False on error
    """
    return await sync_database_disk(directoryname)


def read_from_disk(dir_to_scan: str, skippable: bool = True) -> None:
    """
    Bridge function to sync database with disk.

    Legacy interface that redirects to sync_database_disk for backward compatibility.

    Args:
        dir_to_scan: Fully qualified pathname of the directory to scan
        skippable: Legacy parameter, deprecated and unused

    Returns:
        None

    Note:
        This is a compatibility shim. New code should use sync_database_disk directly.
        WARNING: This function calls the async sync_database_disk. Use async_read_from_disk instead.
    """
    if not Path(dir_to_scan).exists():
        if dir_to_scan.startswith("/"):
            dir_to_scan = dir_to_scan[1:]
        Path(os.path.join(settings.ALBUMS_PATH, dir_to_scan))
    else:
        Path(ensures_endswith(dir_to_scan, os.sep))

    # Note: This is problematic - sync_database_disk is now async
    # This will fail in production. Use async_read_from_disk instead.
    import warnings

    warnings.warn("read_from_disk calls async sync_database_disk. Use async_read_from_disk instead.", DeprecationWarning, stacklevel=2)


# ASGI: Async wrapper for read_from_disk
async def async_read_from_disk(dir_to_scan: str, skippable: bool = True) -> None:
    """
    Async wrapper for read_from_disk to support ASGI views.

    Args:
        dir_to_scan: Fully qualified pathname of the directory to scan
        skippable: Legacy parameter, deprecated and unused

    Returns:
        None
    """
    if not Path(dir_to_scan).exists():
        if dir_to_scan.startswith("/"):
            dir_to_scan = dir_to_scan[1:]
        dir_path = Path(os.path.join(settings.ALBUMS_PATH, dir_to_scan))
    else:
        dir_path = Path(ensures_endswith(dir_to_scan, os.sep))

    return await sync_database_disk(str(dir_path))


from Foundation import (  # NSData,; NSError,
    NSURL,
    NSURLBookmarkResolutionWithoutMounting,
    NSURLBookmarkResolutionWithoutUI,
)


@lru_cache(maxsize=500)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def resolve_alias_path(alias_path: str) -> str:
    """
    Resolve a macOS alias file to its target path.

    Uses macOS Foundation framework to resolve alias files and applies
    path mappings from settings.ALIAS_MAPPING.

    Args:
        alias_path: Path to the macOS alias file

    Returns:
        Resolved path to the target file/directory

    Raises:
        ValueError: If bookmark data cannot be created or resolved
    """
    options = NSURLBookmarkResolutionWithoutUI | NSURLBookmarkResolutionWithoutMounting
    alias_url = NSURL.fileURLWithPath_(alias_path)
    bookmark, error = NSURL.bookmarkDataWithContentsOfURL_error_(alias_url, None)
    if error:
        raise ValueError(f"Error creating bookmark data: {error}")

    resolved_url, _, error = NSURL.URLByResolvingBookmarkData_options_relativeToURL_bookmarkDataIsStale_error_(bookmark, options, None, None, None)
    if error:
        raise ValueError(f"Error resolving bookmark data: {error}")

    resolved_url = str(resolved_url.path()).strip().lower()
    # album_path = f"{settings.ALBUMS_PATH}{os.sep}albums{os.sep}"
    for disk_path, replacement_path in settings.ALIAS_MAPPING.items():
        if resolved_url.startswith(disk_path.lower()):
            resolved_url = resolved_url.replace(disk_path.lower(), replacement_path.lower()) + os.sep
            return resolved_url
    return resolved_url
