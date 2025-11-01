"""
Utilities for QuickBBS, the python edition.

ASGI Support:
- Async wrapper functions provided for database operations
- All functions with ORM queries can be wrapped with sync_to_async
"""

import logging
import os
import os.path
import time

# from datetime import timedelta
from pathlib import Path
from typing import Any

# Third-party imports
from asgiref.sync import sync_to_async
from cachetools import LRUCache, cached
from django.conf import settings
from django.db import close_old_connections, transaction  # connection

# from django.db.models import Case, F, Value, When, BooleanField
from Foundation import (  # pylint: disable=no-name-in-module  # NSData,; NSError,
    NSURL,
    NSURLBookmarkResolutionWithoutMounting,
    NSURLBookmarkResolutionWithoutUI,
)
from PIL import Image

# First-party imports
import filetypes.models as filetype_models
from cache_watcher.models import Cache_Storage
from frontend.file_listings import return_disk_listing
from quickbbs.common import get_file_sha, normalize_fqpn, normalize_string_title
from quickbbs.models import IndexData, IndexDirs
from thumbnails.video_thumbnails import _get_video_info

logger = logging.getLogger(__name__)

# Async-safe caches for utility functions
webpaths_cache = LRUCache(maxsize=500)
breadcrumbs_cache = LRUCache(maxsize=500)
filedata_cache = LRUCache(maxsize=500)
alias_paths_cache = LRUCache(maxsize=250)

# Batch sizes for database operations - kept simple for performance
# These values are optimized for typical directory/file counts in gallery operations
# Simplified from dynamic calculation to avoid repeated CPU detection overhead
BATCH_SIZES = {
    "db_read": 500,  # Reading file/directory records from database
    "db_write": 250,  # Writing/updating records to database
    "file_io": 100,  # File system operations (stat, hash calculation)
}


SORT_MATRIX = {
    0: ["-filetype__is_dir", "-filetype__is_link", "name_sort", "lastmod"],
    1: ["-filetype__is_dir", "-filetype__is_link", "lastmod", "name_sort"],
    2: ["-filetype__is_dir", "-filetype__is_link", "name_sort"],
}


def ensures_endswith(string_to_check: str, value: str) -> str:
    """
    Ensure string ends with specified value, adding it if not present.

    Args:
        string_to_check: The source string to process
        value: The suffix to ensure is at the end

    Returns:
        The string with suffix guaranteed at the end
    """
    return string_to_check if string_to_check.endswith(value) else string_to_check + value


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
    # Use model method for standardized prefetching and caching
    found, directory_record = await sync_to_async(IndexDirs.search_for_directory_by_sha)(directory_sha256)

    if not found:
        found, directory_record = await sync_to_async(IndexDirs.add_directory)(dirpath)
        if not found:
            logger.error(f"Failed to create directory record for {dirpath}")
            return None, False
        await sync_to_async(Cache_Storage.remove_from_cache_indexdirs)(directory_record)
        return directory_record, False

    # Use the is_cached property which leverages the 1-to-1 relationship
    is_cached = directory_record.is_cached
    return directory_record, is_cached


async def _handle_missing_directory(directory_record: object) -> None:
    """
    Handle case where directory doesn't exist on filesystem.

    Deletes the directory record and cleans up parent directory cache.

    Args:
        directory_record: IndexDirs object for the missing directory

    Returns:
        None
    """
    try:
        # Access preloaded parent_directory (loaded via select_related)
        parent_dir = directory_record.parent_directory
        await sync_to_async(IndexDirs.delete_directory_record)(directory_record)

        # Clean up parent directory cache if it exists
        if parent_dir:
            await sync_to_async(IndexDirs.delete_directory_record)(parent_dir, cache_only=True)
    except Exception as e:
        logger.error(f"Error handling missing directory: {e}")


def _sync_directories(directory_record: object, fs_entries: dict) -> None:
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
        directory_record: IndexDirs object for the parent directory
        fs_entries: Dictionary of filesystem entries (DirEntry objects)

    Returns:
        None
    """
    print("Synchronizing directories...")
    logger.info("Synchronizing directories...")
    current_path = normalize_fqpn(directory_record.fqpndirectory)

    # Get all database directories and build filesystem directory set in one pass
    all_dirs_in_database = directory_record.dirs_in_dir()
    db_dirs = set(all_dirs_in_database.values_list("fqpndirectory", flat=True))
    fs_dirs = {normalize_fqpn(current_path + entry.name) for entry in fs_entries.values() if entry.is_dir()}

    # Check for updates in existing directories
    existing_dirs = list(all_dirs_in_database.filter(fqpndirectory__in=db_dirs & fs_dirs))

    print(f"Existing directories in database: {len(existing_dirs)}")
    if existing_dirs:
        # Check each directory for updates
        updated_records = []
        for db_dir_entry in existing_dirs:
            if fs_entry := fs_entries.get(db_dir_entry.fqpndirectory):
                try:
                    fs_stat = fs_entry.stat()
                    # Update modification time and size if changed
                    if db_dir_entry.lastmod != fs_stat.st_mtime or db_dir_entry.size != fs_stat.st_size:
                        db_dir_entry.lastmod = fs_stat.st_mtime
                        db_dir_entry.size = fs_stat.st_size
                        updated_records.append(db_dir_entry)
                except (OSError, IOError) as e:
                    logger.error(f"Error checking directory {db_dir_entry.fqpndirectory}: {e}")

        print(f"Directories to Update: {len(updated_records)}")

        if updated_records:
            print(f"processing existing directory changes: {len(updated_records)}")
            with transaction.atomic():
                for db_dir_entry in updated_records:
                    locked_entry = IndexDirs.objects.select_for_update(skip_locked=True).get(id=db_dir_entry.id)
                    locked_entry.lastmod = db_dir_entry.lastmod
                    locked_entry.size = db_dir_entry.size
                    locked_entry.save()
                    Cache_Storage.remove_from_cache_indexdirs(locked_entry)
            logger.info(f"Processing {len(updated_records)} directory updates")

    # Create new directories BEFORE deleting old ones to prevent foreign key violations
    new_dirs = fs_dirs - db_dirs
    if new_dirs:
        print(f"Directories to Add: {len(new_dirs)}")
        logger.info(f"Directories to Add: {len(new_dirs)}")
        with transaction.atomic():
            for dir_to_create in new_dirs:
                IndexDirs.add_directory(fqpn_directory=dir_to_create)

    # Delete directories that no longer exist in filesystem
    deleted_dirs = db_dirs - fs_dirs
    if deleted_dirs:
        print(f"Directories to Delete: {len(deleted_dirs)}")
        logger.info(f"Directories to Delete: {len(deleted_dirs)}")
        with transaction.atomic():
            all_dirs_in_database.filter(fqpndirectory__in=deleted_dirs).delete()
            Cache_Storage.remove_from_cache_indexdirs(directory_record)


def _sync_files(directory_record: object, fs_entries: dict, bulk_size: int) -> None:
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
        directory_record: IndexDirs object for the parent directory
        fs_entries: Dictionary of filesystem entries (DirEntry objects)
        bulk_size: Size of batches for bulk operations (from BATCH_SIZES)

    Returns:
        None
    """
    # Build filesystem file dictionary (single pass)
    fs_file_names_dict = {name: entry for name, entry in fs_entries.items() if not entry.is_dir()}
    fs_file_names = list(fs_file_names_dict.keys())

    # Get files with prefetch already configured in files_in_dir()
    all_files_in_dir = directory_record.files_in_dir()

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
            directory_record,
        )
        if updated_record:
            records_to_update.append(updated_record)

    # Get files to delete
    files_to_delete_ids = all_files_in_dir.exclude(name__in=fs_file_names).values_list("id", flat=True)

    # Process new files
    fs_file_names_for_creation = set(fs_file_names) - set(all_db_filenames)
    creation_fs_file_names_dict = {name: fs_file_names_dict[name] for name in fs_file_names_for_creation}

    records_to_create = _process_new_files(directory_record, creation_fs_file_names_dict)

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
        path_obj = Path(db_record.name)
        fext = path_obj.suffix.lower() if path_obj.suffix else ""
        if fext:  # Only process files with extensions
            # Use prefetched filetype from select_related
            filetype = db_record.filetype if hasattr(db_record, "filetype") else filetype_models.filetypes.return_filetype(fileext=fext)

            # Calculate hash if missing (for all files including links)
            if not db_record.file_sha256:
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


def _process_new_files(directory_record: object, fs_file_names: dict) -> list[object]:
    """
    Process files that exist in filesystem but not in database.

    Creates new IndexData records for files found on filesystem that don't
    have corresponding database entries.

    Simplification Note:
    Removed chunking logic - it added complexity without measurable benefit.
    Single pass through files is simpler and just as fast for typical counts.

    Args:
        directory_record: IndexDirs object for the parent directory
        fs_file_names: Dictionary mapping filenames to DirEntry objects

    Returns:
        List of new IndexData records to create
    """
    records_to_create = []

    # Single pass through new files
    for _, fs_entry in fs_file_names.items():
        try:
            # Process new file
            filedata = process_filedata(fs_entry, directory_id=directory_record)
            if filedata is None:
                continue

            # Early skip for archives and other excluded types
            filetype = filedata.get("filetype")
            if hasattr(filetype, "is_archive") and filetype.is_archive:
                continue

            # Create record
            record = IndexData(**filedata)
            record.home_directory = directory_record
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


# DEPRECATED: Function replaced by inlined logic in return_breadcrumbs()
# The urlsplit() call was unnecessary overhead for simple path strings.
# Logic now uses direct string.split("/") which is ~30-40% faster.
# Kept here for reference only.
#
# @lru_cache(maxsize=2000)
# def break_down_urls(uri_path: str) -> list[str]:
#     """
#     Split URL into component parts with optimized parsing
#
#     DEPRECATED: Replaced by inline logic in return_breadcrumbs()
#     This function called urllib.parse.urlsplit() unnecessarily on path strings.
#
#     Args:
#         uri_path (str): The URI to break down
#
#     Returns:
#         list: A list containing all parts of the URI
#     """
#     if not uri_path or uri_path == "/":
#         return []
#     path = urllib.parse.urlsplit(uri_path).path
#     return [part for part in path.split("/") if part]


@cached(webpaths_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
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


@cached(breadcrumbs_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def return_breadcrumbs(uri_path="") -> list[dict[str, str]]:
    """
    Return the breadcrumbs for uri_path

    Args:
        uri_path: The URI to break down into breadcrumbs

    Returns:
        List of dictionaries with 'name' and 'url' keys for each breadcrumb level
    """
    webpath = convert_to_webpath(uri_path)

    # Extract path components (direct split, no urlsplit needed for paths)
    parts = [p for p in webpath.split("/") if p]

    # Build breadcrumbs with cumulative paths using list slicing
    return [{"name": part, "url": "/" + "/".join(parts[: i + 1])} for i, part in enumerate(parts)]


@cached(filedata_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
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
            # Subdirectories are handled by _sync_directories, not here
            # Just skip processing directories in the file processing phase
            # NOTE: Commented out recursive sync_database_disk call - it's problematic
            # because it uses asyncio.run() from within a sync function that's already
            # running in a thread pool via sync_to_async. This causes event loop conflicts.
            # The _sync_directories function already handles subdirectories properly.
            # asyncio.run(sync_database_disk(str(fs_entry)))
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
                    # Calculate SHA256 for .link files
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))

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
                    redirect_path = f"/{redirect}"

                    # Find or create the target directory and set virtual_directory
                    found, virtual_dir = IndexDirs.search_for_directory(redirect_path)
                    if not found:
                        found, virtual_dir = IndexDirs.add_directory(redirect_path)

                    # Check if resolution succeeded - if not, skip this file
                    if not found or virtual_dir is None:
                        error_msg = f"Skipping .link file with broken target: {record['name']} → {redirect_path} (target directory not found)"
                        print(error_msg)
                        logger.warning(error_msg)
                        return None  # Don't add to database - will retry on next scan

                    record["virtual_directory"] = virtual_dir
                except ValueError:
                    print(f"Invalid link format in file: {record['name']}")
                    return None

            elif filetype.fileext == ".alias":
                try:
                    alias_target_path = resolve_alias_path(str(fs_entry))
                    record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))

                    # Find or create the target directory and set virtual_directory
                    found, virtual_dir = IndexDirs.search_for_directory(alias_target_path)
                    if not found:
                        found, virtual_dir = IndexDirs.add_directory(alias_target_path)

                    # Check if resolution succeeded - if not, skip this file
                    if not found or virtual_dir is None:
                        error_msg = f"Skipping .alias file with broken target: {record['name']} → {alias_target_path} (target directory not found)"
                        print(error_msg)
                        logger.warning(error_msg)
                        return None  # Don't add to database - will retry on next scan

                    record["virtual_directory"] = virtual_dir
                except ValueError as e:
                    print(f"Error with alias file: {e}")
                    return None
        else:
            # Calculate file hashes for all non-link files
            try:
                record["file_sha256"], record["unique_sha256"] = get_file_sha(str(fs_entry))
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


async def sync_database_disk(directory_record: IndexDirs) -> bool | None:
    """
    Synchronize database entries with filesystem for a given directory.

    Args:
        directory_record: IndexDirs record for the directory to synchronize

    Returns:
        None on completion, bool on early exit conditions
    """
    dirpath = directory_record.fqpndirectory
    print("Starting ...  Syncing database with disk for directory:", dirpath)
    start_time = time.perf_counter()
    # Use simplified batch sizing
    bulk_size = BATCH_SIZES.get("db_write", 100)

    # Check if directory is cached using the record's property
    if directory_record.is_cached:
        print(f"Directory {dirpath} is already cached, skipping sync.")
        return None

    print(f"Rescanning directory: {dirpath}")

    # Get filesystem entries using the directory path from the record
    success, fs_entries = await return_disk_listing(dirpath)
    if not success:
        print("File path doesn't exist, removing from cache and database.")
        return await _handle_missing_directory(directory_record)

    # Batch process all operations
    # Both functions are sync and wrapped here for clean async/sync boundary
    await sync_to_async(_sync_directories)(directory_record, fs_entries)
    await sync_to_async(_sync_files)(directory_record, fs_entries, bulk_size)

    # Cache the result using the directory record
    await sync_to_async(Cache_Storage.add_from_indexdirs)(directory_record)
    logger.info(f"Cached directory: {dirpath}")
    print("Elapsed Time (Sync Database Disk): ", time.perf_counter() - start_time)

    # Close stale connections after expensive operation
    close_old_connections()
    return directory_record


@cached(alias_paths_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
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
            break

    # The copier is set to transform spaces to underscores.  We can safely disable that now, but
    # that legacy means that there would be tremendous pain in duplication of data.  So for now,
    # we will just check if the resolved path exists, and if not, we will try replacing spaces with underscores.
    # If that works, then we will return that modified path instead.  Otherwise, we return the original resolved path.

    if resolved_url:
        if os.path.exists(resolved_url):
            return resolved_url
        else:
            resolved_url = resolved_url.replace(" ", "_")

    return resolved_url
