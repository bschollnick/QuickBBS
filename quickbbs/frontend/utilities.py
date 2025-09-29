"""
Utilities for QuickBBS, the python edition.
"""

import logging
import os
import os.path
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# from datetime import timedelta
from functools import lru_cache  # , wraps
from pathlib import Path
from typing import Any

import filetypes.models as filetype_models
from cache_watcher.models import Cache_Storage, get_dir_sha
from django.conf import settings
from django.db import connections, transaction  # connection

# from django.db.models import Case, F, Value, When, BooleanField
from frontend.file_listings import return_disk_listing
from PIL import Image
from thumbnails.video_thumbnails import _get_video_info

from quickbbs.common import get_file_sha, normalize_fqpn
from quickbbs.models import IndexData, IndexDirs

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None  # Disable PILLOW DecompressionBombError errors.

# Optimize thread count dynamically based on system resources
MAX_THREADS = min(
    32, max(4, (os.cpu_count() or 1) * 2)
)  # Better scaling for modern systems

# Filesystem operation caching - use regular dict since os.stat_result objects work better with regular dict
_fs_stat_cache = {}  # Cache file stats with timestamp tuples
_path_exists_cache = {}  # Cache path existence checks
_cache_timeout = 30  # Cache timeout in seconds

# Memory pooling for object creation
_record_pool = []  # Pool of reusable record dictionaries
_max_pool_size = 100  # Maximum number of pooled objects


# Intelligent batch sizing based on system resources
def _calculate_optimal_batch_size(operation_type: str, data_size: int) -> int:
    """
    Calculate optimal batch size based on system resources and operation type.

    :Args:
        operation_type (str): Type of operation ('db_read', 'db_write', 'file_io')
        data_size (int): Total number of items to process

    :Returns:
        int: Optimal batch size for the operation
    """
    # Get available memory (simplified estimation)
    cpu_count = os.cpu_count() or 1

    # Base batch sizes optimized for different operations
    base_sizes = {
        "db_read": min(1000, max(100, cpu_count * 50)),
        "db_write": min(500, max(50, cpu_count * 25)),
        "file_io": min(200, max(20, cpu_count * 10)),
        "concurrent": min(100, max(10, cpu_count * 5)),
    }

    base_size = base_sizes.get(operation_type, 100)

    # Scale based on data size
    if data_size <= 0:
        return 1  # Minimum safe value
    elif data_size < 100:
        return max(1, min(base_size, data_size))  # Ensure minimum of 1
    elif data_size > 10000:
        return min(base_size * 2, 2000)  # Cap at reasonable maximum
    else:
        return base_size


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
) -> tuple[object | None, bool]:
    """
    Get or create directory record and check cache status.

    :param directory_sha256: SHA256 hash of the directory path
    :param dirpath: Fully qualified directory path
    :return: Tuple of (directory object, is_cached) where is_cached indicates
             if the directory is already in cache
    """
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
    """
    Handle case where directory doesn't exist on filesystem.

    Deletes the directory record and cleans up parent directory cache.

    :param dirpath_info: IndexDirs object for the missing directory
    :return: None
    """
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
    """
    Synchronize database directories with filesystem.

    Compares directories in database with filesystem entries and updates,
    creates, or deletes records as needed.

    :param dirpath_info: IndexDirs object for the parent directory
    :param fs_entries: Dictionary of filesystem entries
    :return: None
    """
    # Get all database directories in one query
    print("Synchronizing directories...")
    logger.info("Synchronizing directories...")
    current_path = normalize_fqpn(dirpath_info.fqpndirectory)
    # Optimize directory queries with better batching
    all_dirs_in_database = dirpath_info.dirs_in_dir()

    # Optimize directory field loading with values_list for maximum efficiency
    all_database_dir_names_set = set(
        all_dirs_in_database.values_list("fqpndirectory", flat=True)
    )

    # Optimize directory path construction
    all_filesystem_dir_names = set()
    current_path_len = len(current_path)

    for entry in fs_entries.values():
        if entry.is_dir():
            # More efficient path joining for known structure
            full_path = current_path + entry.name
            all_filesystem_dir_names.add(normalize_fqpn(full_path))

    entries_that_dont_exist_in_fs = (
        all_database_dir_names_set - all_filesystem_dir_names
    )
    entries_not_in_database = all_filesystem_dir_names - all_database_dir_names_set

    # Filter directories that need to be checked for updates
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
                # Use select_for_update inside transaction to avoid deadlocks
                for db_dir_entry in updated_records:
                    # Refresh from database with lock to ensure consistency
                    locked_entry = IndexDirs.objects.select_for_update(
                        skip_locked=True
                    ).get(id=db_dir_entry.id)
                    # Copy updated values to locked entry
                    locked_entry.lastmod = db_dir_entry.lastmod
                    locked_entry.size = db_dir_entry.size
                    locked_entry.save()
                    Cache_Storage.remove_from_cache_sha(locked_entry.dir_fqpn_sha256)
                logger.info(f"Processing {len(updated_records)} directory updates")

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


def _get_cached_stat(file_path: str):
    """
    Get cached file stat or fetch and cache it.

    :Args:
        file_path (str): Path to file

    :Returns:
        os.stat_result or None: File stat object or None if error
    """
    current_time = time.time()
    cache_key = file_path

    # Check if cached and not expired
    if cache_key in _fs_stat_cache:
        cached_stat, cache_time = _fs_stat_cache[cache_key]
        if current_time - cache_time < _cache_timeout:
            return cached_stat

    try:
        stat_result = os.stat(file_path)
        _fs_stat_cache[cache_key] = (stat_result, current_time)
        return stat_result
    except (OSError, IOError):
        return None


def _get_pooled_record() -> dict:
    """
    Get a record dictionary from the pool or create a new one.

    :Returns:
        dict: A clean record dictionary for use
    """
    if _record_pool:
        record = _record_pool.pop()
        record.clear()  # Reset the dictionary
        return record
    else:
        return {}


def _return_to_pool(record: dict) -> None:
    """
    Return a record dictionary to the pool for reuse.

    :Args:
        record (dict): Record dictionary to return to pool
    """
    if len(_record_pool) < _max_pool_size:
        record.clear()
        _record_pool.append(record)


def _check_single_directory_update(db_dir_entry, fs_entries: dict) -> object | None:
    """
    Check a single directory for updates. Helper function for concurrent processing.

    :param db_dir_entry: Database directory entry
    :param fs_entries: Dictionary of filesystem entries
    :return: Updated directory record or None
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


def _check_directory_updates(
    fs_entries: dict, existing_directories_in_database: object
) -> list[object]:
    """
    Check for updates in existing directories using concurrent processing.

    :param fs_entries: Dictionary of filesystem entries
    :param existing_directories_in_database: QuerySet of existing directory records
    :return: List of directory records that need updating
    """
    records_to_update = []
    directory_list = list(existing_directories_in_database)

    # Use intelligent worker sizing based on directory count and system resources
    optimal_batch_size = _calculate_optimal_batch_size(
        "concurrent", len(directory_list)
    )
    max_workers = min(
        MAX_THREADS // 2, optimal_batch_size, 10
    )  # Limit concurrent operations
    if (
        len(directory_list) > 5 and max_workers > 1
    ):  # Only use threading for larger batches
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all directory check tasks
                future_to_dir = {
                    executor.submit(
                        _check_single_directory_update, db_dir_entry, fs_entries
                    ): db_dir_entry
                    for db_dir_entry in directory_list
                }

                # Collect results as they complete
                for future in as_completed(future_to_dir):
                    try:
                        result = future.result()
                        if result:
                            records_to_update.append(result)
                    except Exception as e:
                        db_dir_entry = future_to_dir[future]
                        logger.error(
                            f"Error processing directory {db_dir_entry.fqpndirectory}: {e}"
                        )
        finally:
            # Clean up connections after concurrent operations
            connections.close_all()
    else:
        # Fall back to sequential processing for small batches
        for db_dir_entry in directory_list:
            result = _check_single_directory_update(db_dir_entry, fs_entries)
            if result:
                records_to_update.append(result)

    return records_to_update


def _sync_files(dirpath_info: object, fs_entries: dict, bulk_size: int) -> None:
    """
    Synchronize database files with filesystem.

    Compares files in database with filesystem entries and performs batch
    updates, creates, or deletes as needed.

    :param dirpath_info: IndexDirs object for the parent directory
    :param fs_entries: Dictionary of filesystem entries
    :param bulk_size: Size of batches for bulk operations
    :return: None
    """
    # Optimize file name processing - avoid redundant iterations
    fs_file_names_dict = {}
    fs_file_names = []

    for name, entry in fs_entries.items():
        if not entry.is_dir():
            fs_file_names_dict[name] = entry
            fs_file_names.append(name.strip().title())

    # Optimize file query field loading - only load essential fields
    all_files_in_dir = (
        dirpath_info.files_in_dir()
        .only(
            "id",
            "name",
            "lastmod",
            "size",
            "file_sha256",
            "unique_sha256",
            "home_directory",
            "duration",
        )
        .prefetch_related("filetype")
    )

    # Batch fetch all filenames in one query
    all_db_filenames = set(all_files_in_dir.values_list("name", flat=True))
    records_to_update = []
    # Optimize file updates query with essential fields only
    potential_updates = all_files_in_dir.filter(name__in=fs_file_names)

    # Use intelligent chunk sizing based on data size
    total_files = (
        potential_updates.count()
        if hasattr(potential_updates, "count")
        else len(potential_updates)
    )
    chunk_size = max(
        1, _calculate_optimal_batch_size("db_read", total_files)
    )  # Ensure minimum of 1
    for chunk_start in range(0, potential_updates.count(), chunk_size):
        chunk_end = chunk_start + chunk_size
        chunk_updates = potential_updates[chunk_start:chunk_end]

        # Check for movie filetypes in this chunk for smart field detection
        has_movies = any(
            hasattr(db_file_entry, "filetype")
            and hasattr(db_file_entry.filetype, "is_movie")
            and db_file_entry.filetype.is_movie
            for db_file_entry in chunk_updates
        )

        for db_file_entry in chunk_updates:
            updated_record = _check_file_updates(
                db_file_entry,
                fs_file_names_dict[db_file_entry.name],
                dirpath_info,
                has_movies,
            )
            if updated_record:
                records_to_update.append(updated_record)

    # Use values_list for memory efficiency on delete check
    files_to_delete_ids = all_files_in_dir.exclude(name__in=fs_file_names).values_list(
        "id", flat=True
    )

    fs_file_names_for_creation = set(fs_file_names) - set(all_db_filenames)
    creation_fs_file_names_dict = {
        name: fs_file_names_dict[name] for name in fs_file_names_for_creation
    }

    records_to_create = _process_new_files(dirpath_info, creation_fs_file_names_dict)
    # Execute batch operations
    _execute_batch_operations(
        records_to_update, records_to_create, files_to_delete_ids, bulk_size
    )


def _check_file_updates(
    db_record: object, fs_entry: Path, home_directory: object, has_movies: bool = False
) -> object | None:
    """
    Check if database record needs updating based on filesystem entry.

    Compares modification time, size, SHA256, and other attributes between
    database record and filesystem entry.

    :param db_record: IndexData database record
    :param fs_entry: Path object for filesystem entry
    :param home_directory: IndexDirs object for the parent directory
    :return: Updated database record if changes detected, None otherwise
    """
    try:
        fs_stat = fs_entry.stat()
        update_needed = False

        # Optimize file extension extraction
        record_name = db_record.name
        dot_index = record_name.rfind(
            "."
        )  # More efficient than splitext for just extension
        fext = record_name[dot_index:].lower() if dot_index != -1 else ""
        if fext:  # Only process files with extensions
            # Use prefetched filetype from select_related
            filetype = (
                db_record.filetype
                if hasattr(db_record, "filetype")
                else filetype_models.filetypes.return_filetype(fileext=fext)
            )

            # Only calculate hash if file changed AND hash is missing
            file_changed = (
                db_record.lastmod != fs_stat.st_mtime
                or db_record.size != fs_stat.st_size
            )

            if not db_record.file_sha256 and not filetype.is_link and file_changed:
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

            # Smart movie duration loading - only process if movies detected in batch
            if has_movies and filetype.is_movie and db_record.duration is None:
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
    have corresponding database entries. Uses memory-efficient processing.

    :param dirpath_info: IndexDirs object for the parent directory
    :param fs_file_names: Dictionary of filesystem file entries
    :return: List of new IndexData records to create
    """
    records_to_create = []

    # Use intelligent chunking for file processing
    file_items = list(fs_file_names.items())
    chunk_size = _calculate_optimal_batch_size("file_io", len(file_items))

    for i in range(0, len(file_items), chunk_size):
        chunk = file_items[i : i + chunk_size]

        for _, fs_entry in chunk:
            try:
                # Process new file
                filedata = process_filedata(fs_entry, directory_id=dirpath_info)
                if filedata is None:
                    continue

                # Early skip for archives and other excluded types
                filetype = filedata.get("filetype")
                if hasattr(filetype, "is_archive") and filetype.is_archive:
                    # logger.info(f"Archive detected: {filedata['name']}")  # Reduce logging
                    continue
                # Create record using get_or_create to handle duplicates
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

    :param records_to_update: List of records to update
    :param records_to_create: List of records to create
    :param records_to_delete_ids: List of record IDs to delete
    :param bulk_size: Size of batches for bulk operations
    :return: None
    :raises Exception: If any database operation fails
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
                    has_hashes = any(
                        hasattr(record, "file_sha256") and record.file_sha256
                        for record in chunk
                    )
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
        # Ensure connections are closed after batch operations
        connections.close_all()


@lru_cache(maxsize=2000)  # Optimize for URL parsing frequency
def break_down_urls(uri_path: str) -> list[str]:
    """
    Split URL into component parts with optimized parsing

    :Args:
        uri_path (str): The URI to break down

    :Returns:
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


@lru_cache(maxsize=5000)  # High cache size for most frequently used function
def convert_to_webpath(full_path, directory=None):
    """
    Convert a full path to a webpath - optimized for performance

    :Args:
        full_path (str): The full path to convert
        directory (str, optional): Directory component for path construction

    :Returns:
        str: The converted webpath
    """
    # Cache the albums path to avoid repeated settings access
    if not hasattr(convert_to_webpath, "_albums_path_lower"):
        convert_to_webpath._albums_path_lower = settings.ALBUMS_PATH.lower()

    if directory is not None:
        cutpath = (
            convert_to_webpath._albums_path_lower + directory.lower()
            if directory
            else ""
        )
    else:
        cutpath = convert_to_webpath._albums_path_lower

    return full_path.replace(cutpath, "")


@lru_cache(maxsize=5000)  # Very high cache for navigation breadcrumbs
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
    # Optimize breadcrumb generation with list comprehension and string builder
    data = []
    url_parts = []

    for name in uris:
        if name:  # Skip empty strings more efficiently
            url_parts.append(name)
            url = "/".join(url_parts)
            data.append([name, url, f"<a href='{url}'>{name}</a>"])

    return data


@lru_cache(maxsize=1000)  # Increase cache for directory scanning patterns
def _cached_fs_counts(entries_tuple: tuple) -> tuple[int, int]:
    """
    Cached helper for fs_counts with optimized counting.

    :Args:
        entries_tuple (tuple): Tuple of boolean values indicating file status

    :Returns:
        tuple: (file_count, directory_count)
    """
    # More efficient counting using built-in sum
    files = sum(entries_tuple)
    dirs = len(entries_tuple) - files
    return (files, dirs)


def fs_counts(fs_entries: dict) -> tuple[int, int]:
    """
    Efficiently count files vs directories with enhanced caching

    :Args:
        fs_entries (dict): Dictionary of scandir entries

    :Returns:
        tuple: (number_of_files, number_of_directories)
    """
    if not fs_entries:
        return (0, 0)

    # Create a more cache-friendly representation
    entries_tuple = tuple(entry.is_file() for entry in fs_entries.values())
    return _cached_fs_counts(entries_tuple)


def process_filedata(
    fs_entry: Path, directory_id: str | None = None
) -> dict[str, Any] | None:
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

        # Use cached filesystem stats
        try:
            fs_stat = _get_cached_stat(str(fs_entry))
            if not fs_stat:
                print(f"Error getting cached stats for {fs_entry}")
                return None

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
                    # Lazy alias resolution - defer expensive operations
                    record["_alias_path_cache"] = str(
                        fs_entry
                    )  # Store for later resolution
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(
                        str(fs_entry)
                    )

                    # Defer directory lookup until needed
                    record["virtual_directory"] = None  # Will be resolved on demand

                except ValueError as e:
                    print(f"Error with alias file: {e}")
                    return None
        else:
            # Calculate file hashes for non-link files - only if needed
            try:
                # Only calculate hash for files that will likely be accessed
                if filetype.is_image or filetype.is_pdf or filetype.is_movie:
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(
                        str(fs_entry)
                    )
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


def sync_database_disk(directoryname: str) -> bool | None:
    """
    Synchronize database entries with filesystem for a given directory.

    Args:
        directoryname: The directory path to synchronize

    Returns:
        None on completion, bool on early exit conditions
    """
    print("Starting ...  Syncing database with disk for directory:", directoryname)
    start_time = time.perf_counter()
    # Use intelligent batch sizing
    BULK_SIZE = _calculate_optimal_batch_size("db_write", 1000)

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

    # Clean up database connections after expensive operations
    connections.close_all()
    return None

    # except Exception as e:
    #     print(f"Error syncing directory {directoryname}: {e}")
    #     logger.error(f"Error syncing directory {directoryname}: {e}")
    #     return False


def read_from_disk(dir_to_scan: str, skippable: bool = True) -> None:
    """
    Bridge function to sync database with disk.

    Legacy interface that redirects to sync_database_disk for backward compatibility.

    :param dir_to_scan: Fully qualified pathname of the directory to scan
    :param skippable: Legacy parameter, deprecated and unused
    :return: None

    Note:
        This is a compatibility shim. New code should use sync_database_disk directly.
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


@lru_cache(maxsize=500)  # Increase cache for alias operations
def resolve_alias_path(alias_path: str) -> str:
    """
    Resolve a macOS alias file to its target path.

    Uses macOS Foundation framework to resolve alias files and applies
    path mappings from settings.ALIAS_MAPPING.

    :param alias_path: Path to the macOS alias file
    :return: Resolved path to the target file/directory
    :raises ValueError: If bookmark data cannot be created or resolved
    """
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
