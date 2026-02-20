"""Common utility functions for QuickBBS application."""

import atexit
import hashlib
import logging
import os
import pathlib
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import TypeVar

from cachetools import cached
from django.conf import settings
from django.db import models

from quickbbs.MonitoredCache import create_cache

logger = logging.getLogger(__name__)

# Type variable for Django models
T = TypeVar("T", bound=models.Model)

# Async-safe caches for common utility functions
normalized_strings_cache = create_cache(settings.NORMALIZED_STRINGS_CACHE_SIZE, "normalized_strings", monitored=settings.CACHE_MONITORING)
directory_sha_cache = create_cache(settings.DIRECTORY_SHA_CACHE_SIZE, "directory_sha", monitored=settings.CACHE_MONITORING)
normalized_paths_cache = create_cache(settings.NORMALIZED_PATHS_CACHE_SIZE, "normalized_paths", monitored=settings.CACHE_MONITORING)

# Sort matrix for file/directory listings
# Defines ordering for different sort modes:
#   0: Name (default) - directories first, then by name with modification time tiebreaker
#   1: Date - directories first, then by modification time with name tiebreaker
#   2: Name only - directories first, then by name (no secondary sort)
SORT_MATRIX = {
    0: ["-filetype__is_dir", "-filetype__is_link", "name_sort", "lastmod"],
    1: ["-filetype__is_dir", "-filetype__is_link", "lastmod", "name_sort"],
    2: ["-filetype__is_dir", "-filetype__is_link", "name_sort"],
}

# Sort matrix for directory-only queries (used by dirs_in_dir).
# Omits -filetype__is_dir and -filetype__is_link since all directories have
# filetype=".dir", making those sort fields constant. This avoids an
# unnecessary JOIN to the filetypes table.
DIR_SORT_MATRIX = {
    0: ["name_sort", "lastmod"],
    1: ["lastmod", "name_sort"],
    2: ["name_sort"],
}


@cached(normalized_strings_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def normalize_string_lower(s: str) -> str:
    """
    Normalize string to lowercase and strip whitespace.

    Args:
        s: String to normalize

    Returns:
        Lowercase, stripped string
    """
    return s.lower().strip()


@cached(normalized_strings_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def normalize_string_title(s: str) -> str:
    """
    Normalize string to title case and strip whitespace.

    Args:
        s: String to normalize

    Returns:
        Title-cased, stripped string
    """
    return s.title().strip()


@cached(directory_sha_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def get_dir_sha(fqpn_directory: str) -> str:
    """
    Return the SHA256 hash of the normalized directory path.

        fqpn_directory: Fully qualified pathname of the directory
    Returns: SHA256 hash of the normalized directory path as hexdigest string
    """
    fqpn_directory = normalize_fqpn(fqpn_directory)
    return hashlib.sha256(fqpn_directory.encode("utf-8")).hexdigest()


@cached(normalized_paths_cache)  # ASYNC-SAFE: Pure function (no DB/IO, deterministic computation)
def normalize_fqpn(fqpn_directory: str) -> str:
    """
    Normalize the directory structure fully qualified pathname.

    Converts path to lowercase, resolves to absolute path, and ensures
    trailing separator.

        fqpn_directory: Directory path to normalize
    Returns: Normalized directory path with trailing separator
    """
    # Use cached property of Path object if possible
    fqpn = str(pathlib.Path(fqpn_directory).resolve()).lower().strip()

    # Add trailing separator only if needed
    if not fqpn.endswith(os.sep):
        fqpn += os.sep

    return fqpn


def get_file_sha(fqfn: str) -> tuple[str | None, str | None]:
    """
    Return the SHA256 hashes of the file as hexdigest strings.

    Generates both a file-content hash and a unique hash that includes
    the file path. Uses hashlib.file_digest() for optimal performance
    (Python 3.11+).

    Args:
        fqfn: The fully qualified filename of the file to be hashed

    Returns:
        Tuple of (file_sha256, unique_sha256) where:
        - file_sha256: SHA256 hash of file contents only
        - unique_sha256: SHA256 hash of file contents + title-cased filepath
                        (makes hash unique to both content and location)
    """
    try:
        with open(fqfn, "rb") as filehandle:
            # Use file_digest for better performance (Python 3.11+)
            digest = hashlib.file_digest(filehandle, "sha256")
            file_sha256 = digest.hexdigest()
            # Create unique hash by adding filepath to content hash
            digest.update(str(fqfn).title().encode("utf-8"))
            unique_sha256 = digest.hexdigest()
        return file_sha256, unique_sha256
    except (FileNotFoundError, OSError, IOError) as exc:
        logger.error("Error producing SHA 256 for: %s - %s", fqfn, exc)
        return None, None


# Module-level singleton ProcessPoolExecutor for SHA256 computation.
# Using a persistent pool avoids the overhead of spawning new processes on every call.
# Thread-safe initialization and proper cleanup on exit.
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
            except (OSError, IOError, ValueError) as e:
                logger.error("Error computing SHA256 for %s: %s", path, e)
                results[path] = (None, None)

    except (OSError, RuntimeError) as e:
        logger.error("Error in batch SHA256 computation: %s", e)
        # Fallback to sequential processing
        for path in file_paths:
            try:
                results[path] = get_file_sha(path)
            except (OSError, IOError, ValueError) as path_error:
                logger.error("Error computing SHA256 for %s: %s", path, path_error)
                results[path] = (None, None)

    return results
