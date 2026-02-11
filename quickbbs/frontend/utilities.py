"""
Utilities for QuickBBS, the python edition.

ASGI Support:
- Async wrapper functions provided for database operations
- All functions with ORM queries can be wrapped with sync_to_async
"""

import atexit
import logging
import os
import os.path
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from urllib.parse import quote

# Third-party imports
from cachetools import cached
from django.conf import settings
from django.db import close_old_connections

# First-party imports
from cache_watcher.models import Cache_Storage
from frontend.file_listings import return_disk_listing_sync
from quickbbs.common import SORT_MATRIX, get_file_sha
from quickbbs.models import DirectoryIndex
from quickbbs.MonitoredCache import create_cache

logger = logging.getLogger(__name__)

# Async-safe caches for utility functions
webpaths_cache = create_cache(settings.WEBPATHS_CACHE_SIZE, "webpaths", monitored=settings.CACHE_MONITORING)
breadcrumbs_cache = create_cache(settings.BREADCRUMBS_CACHE_SIZE, "breadcrumbs", monitored=settings.CACHE_MONITORING)

# Pre-computed constant for webpath conversion (settings don't change at runtime)
_ALBUMS_PATH_LOWER = settings.ALBUMS_PATH.lower()

# Module-level singleton ProcessPoolExecutor for SHA256 computation
# Using a persistent pool avoids the overhead of spawning new processes on every call
# Thread-safe initialization and proper cleanup on exit
_sha_executor: ProcessPoolExecutor | None = None
_sha_executor_lock = threading.Lock()


def _get_sha_executor() -> ProcessPoolExecutor:
    """
    Get or create the singleton ProcessPoolExecutor for SHA256 computation.

    Thread-safe lazy initialization of a module-level process pool.
    The pool is reused across all calls to improve performance by avoiding
    repeated process spawning overhead.

    Returns:
        ProcessPoolExecutor configured for SHA256 hashing operations
    """
    global _sha_executor  # pylint: disable=global-statement

    if _sha_executor is None:
        with _sha_executor_lock:
            # Double-check locking pattern
            if _sha_executor is None:
                cpu_count = os.cpu_count() or 4
                max_workers = min(cpu_count, settings.SHA256_MAX_WORKERS)
                _sha_executor = ProcessPoolExecutor(max_workers=max_workers)
                logger.info("Initialized SHA256 ProcessPoolExecutor with %d workers", max_workers)

                # Register cleanup handler to ensure workers are terminated
                atexit.register(_cleanup_sha_executor)

    return _sha_executor


def _cleanup_sha_executor() -> None:
    """
    Clean up the SHA256 ProcessPoolExecutor on program exit.

    Ensures all worker processes are properly terminated and cleaned up.
    Called automatically via atexit registration.
    """
    global _sha_executor  # pylint: disable=global-statement

    if _sha_executor is not None:
        logger.info("Shutting down SHA256 ProcessPoolExecutor")
        try:
            # Wait for pending tasks but don't accept new ones
            # cancel_futures=True is Python 3.9+
            _sha_executor.shutdown(wait=True, cancel_futures=True)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Error shutting down SHA256 ProcessPoolExecutor: %s", e)
        finally:
            _sha_executor = None


def _batch_compute_file_shas(file_paths: list[str], max_workers: int | None = None) -> dict[str, tuple[str | None, str | None]]:
    """
    Compute SHA256 hashes in parallel using a persistent process pool.

    Uses a module-level singleton ProcessPoolExecutor (NOT ThreadPoolExecutor) to:
    - Avoid Django ORM threading issues (each process has isolated memory)
    - Improve performance by reusing worker processes across calls
    - Ensure proper cleanup via atexit handlers

    SHA256 computation is CPU-bound, so multiprocessing provides better performance
    than threading.

    DJANGO-SAFE: Does not touch Django ORM - only computes file hashes.
    The singleton pool is safe because workers are isolated processes.

    ASYNC-SAFE: This is a sync function. When called from async contexts,
    it should be wrapped with sync_to_async() (see update_database_from_disk).
    The blocking ProcessPoolExecutor calls will run in a thread pool via
    sync_to_async, preventing event loop blocking.

    :Args:
        file_paths: List of fully qualified file paths to hash
        max_workers: Ignored (kept for backward compatibility)

    Returns:
        Dictionary mapping file paths to (file_sha256, unique_sha256) tuples
    """
    # max_workers is kept for backward compatibility but ignored
    _ = max_workers
    if not file_paths:
        return {}

    results = {}

    # For small batches, don't bother with multiprocessing overhead
    if len(file_paths) < settings.SHA256_PARALLEL_THRESHOLD:
        for path in file_paths:
            results[path] = get_file_sha(path)
        return results

    # Use singleton ProcessPoolExecutor for parallel SHA256 computation
    # This is safe because get_file_sha() doesn't touch the database
    try:
        executor = _get_sha_executor()

        # Submit all tasks to the persistent pool
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
    if directory is not None:
        cutpath = _ALBUMS_PATH_LOWER + directory.lower() if directory else ""
    else:
        cutpath = _ALBUMS_PATH_LOWER

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
    # URL-encode each path component while preserving / separators
    return [{"name": part, "url": "/" + "/".join(quote(p, safe="") for p in parts[: i + 1])} for i, part in enumerate(parts)]


def update_database_from_disk(directory_record: DirectoryIndex) -> DirectoryIndex | None:
    """
    Update database entries to match filesystem state for a given directory.

    This is a sync function — all operations are direct Django ORM calls.
    Wrap with sync_to_async() when calling from async contexts.

    Args:
        directory_record: DirectoryIndex record for the directory to synchronize

    Returns:
        The directory_record on success, None on early exit (cached or missing)
    """
    dirpath = directory_record.fqpndirectory
    print("Starting ...  Syncing database with disk for directory:", dirpath)
    start_time = time.perf_counter()
    # Use simplified batch sizing
    bulk_size = settings.BATCH_SIZES.get("db_write", 100)

    # Reload from DB in case Cache_Watcher was invalidated after this object was loaded
    # (e.g., by watchdog). Clears all cached relations including reverse OneToOne.
    directory_record.refresh_from_db()

    # Check if directory is cached using the record's property
    if directory_record.is_cached:
        print(f"Directory {dirpath} is already cached, skipping sync.")
        return None

    print(f"Rescanning directory: {dirpath}")

    # Get filesystem entries using the directory path from the record
    success, fs_entries = return_disk_listing_sync(dirpath)
    if not success:
        print("File path doesn't exist, removing from cache and database.")
        directory_record.handle_missing()
        return None

    # Direct sync calls — no boundary crossings needed
    directory_record.sync_subdirectories(fs_entries)
    directory_record.sync_files(fs_entries, bulk_size)

    # Cache the result using the directory record
    Cache_Storage.add_from_indexdirs(directory_record)
    logger.info(f"Cached directory: {dirpath}")
    print("Elapsed Time (Sync Database Disk): ", time.perf_counter() - start_time)

    # Close stale connections after expensive operation
    close_old_connections()
    return directory_record
