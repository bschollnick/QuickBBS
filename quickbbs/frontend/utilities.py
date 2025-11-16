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
from concurrent.futures import ProcessPoolExecutor, as_completed

# Third-party imports
from asgiref.sync import sync_to_async
from cachetools import LRUCache, cached
from django.conf import settings
from django.db import close_old_connections

# First-party imports
from cache_watcher.models import Cache_Storage
from frontend.file_listings import return_disk_listing
from quickbbs.common import SORT_MATRIX, get_file_sha
from quickbbs.models import DirectoryIndex

logger = logging.getLogger(__name__)

# Async-safe caches for utility functions
webpaths_cache = LRUCache(maxsize=500)
breadcrumbs_cache = LRUCache(maxsize=500)

# Batch sizes for database operations - kept simple for performance
# These values are optimized for typical directory/file counts in gallery operations
# Simplified from dynamic calculation to avoid repeated CPU detection overhead
BATCH_SIZES = {
    "db_read": 500,  # Reading file/directory records from database
    "db_write": 250,  # Writing/updating records to database
    "file_io": 100,  # File system operations (stat, hash calculation)
}


def _batch_compute_file_shas(file_paths: list[str], max_workers: int | None = None) -> dict[str, tuple[str | None, str | None]]:
    """
    Compute SHA256 hashes in parallel using multiprocessing.

    Uses ProcessPoolExecutor (NOT ThreadPoolExecutor) to avoid Django ORM issues.
    SHA256 computation is CPU-bound, so multiprocessing provides better performance
    than threading.

    ASGI-SAFE: Does not touch Django ORM - only computes file hashes.
    Safe to call from sync or async contexts.

    :Args:
        file_paths: List of fully qualified file paths to hash
        max_workers: Number of parallel workers (defaults to min(cpu_count, 8))

    Returns:
        Dictionary mapping file paths to (file_sha256, unique_sha256) tuples
    """
    if not file_paths:
        return {}

    # Default to reasonable number of workers (4-8 is optimal for most systems)
    # Too many workers can saturate disk I/O, especially on HDDs
    if max_workers is None:
        cpu_count = os.cpu_count() or 4
        max_workers = min(cpu_count, 8)

    results = {}

    # For small batches, don't bother with multiprocessing overhead
    if len(file_paths) < 5:
        for path in file_paths:
            results[path] = get_file_sha(path)
        return results

    # Use ProcessPoolExecutor for parallel SHA256 computation
    # This is safe because get_file_sha() doesn't touch the database
    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_path = {executor.submit(get_file_sha, path): path for path in file_paths}

            # Collect results as they complete
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    results[path] = future.result()
                except Exception as e:
                    logger.error(f"Error computing SHA256 for {path}: {e}")
                    results[path] = (None, None)

    except Exception as e:
        logger.error(f"Error in batch SHA256 computation: {e}")
        # Fallback to sequential processing
        for path in file_paths:
            try:
                results[path] = get_file_sha(path)
            except Exception as path_error:
                logger.error(f"Error computing SHA256 for {path}: {path_error}")
                results[path] = (None, None)

    return results


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
    found, directory_record = await sync_to_async(DirectoryIndex.search_for_directory_by_sha)(directory_sha256)

    if not found:
        found, directory_record = await sync_to_async(DirectoryIndex.add_directory)(dirpath)
        if not found:
            logger.error(f"Failed to create directory record for {dirpath}")
            return None, False
        await sync_to_async(Cache_Storage.remove_from_cache_indexdirs)(directory_record)
        return directory_record, False

    # Use the is_cached property which leverages the 1-to-1 relationship
    is_cached = directory_record.is_cached
    return directory_record, is_cached


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


async def sync_database_disk(directory_record: DirectoryIndex) -> bool | None:
    """
    Synchronize database entries with filesystem for a given directory.

    Args:
        directory_record: DirectoryIndex record for the directory to synchronize

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
        return await directory_record.handle_missing()

    # Batch process all operations
    # Both methods are sync and wrapped here for clean async/sync boundary
    await sync_to_async(directory_record.sync_subdirectories)(fs_entries)
    await sync_to_async(directory_record.sync_files)(fs_entries, bulk_size)

    # Cache the result using the directory record
    await sync_to_async(Cache_Storage.add_from_indexdirs)(directory_record)
    logger.info(f"Cached directory: {dirpath}")
    print("Elapsed Time (Sync Database Disk): ", time.perf_counter() - start_time)

    # Close stale connections after expensive operation
    close_old_connections()
    return directory_record
