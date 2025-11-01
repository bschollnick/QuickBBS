"""Common utility functions for QuickBBS application."""

import hashlib
import logging
import os
import pathlib
from typing import Any, Callable, Optional, TypeVar

from cachetools import LRUCache, cached
from django.db import models
from django.http import HttpResponseBadRequest

logger = logging.getLogger(__name__)

# Type variable for Django models
T = TypeVar("T", bound=models.Model)

# Async-safe caches for common utility functions
normalized_strings_cache = LRUCache(maxsize=500)
directory_sha_cache = LRUCache(maxsize=2500)
normalized_paths_cache = LRUCache(maxsize=1000)


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
    except (FileNotFoundError, OSError, IOError):
        print(f"Error producing SHA 256 for: {fqfn}")
        return None, None


# def safe_get_or_none(
#     model: type[T],
#     error_callback: Optional[Callable[[Exception], Any]] = None,
#     **lookup_kwargs,
# ) -> Optional[T]:
#     """
#     Safely get a database object or return None on DoesNotExist.

#     ASYNC-SAFE: Pure ORM operation, wrap with sync_to_async if needed in async contexts

#     Args:
#         model: Django model class to query
#         error_callback: Optional callback for logging/handling errors
#         **lookup_kwargs: Lookup arguments for the query (e.g., pk=123, name="foo")

#     Returns:
#         Model instance or None if not found

#     Example:
#         directory = safe_get_or_none(IndexDirs, dir_fqpn_sha256=sha256)
#         if directory:
#             directory.invalidate_thumb()
#     """
#     try:
#         return model.objects.get(**lookup_kwargs)
#     except model.DoesNotExist:
#         if error_callback:
#             error_callback(model.DoesNotExist(f"Not found: {lookup_kwargs}"))
#         return None


# def safe_get_or_error(
#     model: type[T],
#     error_message: str = "Record not found",
#     log_error: bool = True,
#     **lookup_kwargs,
# ) -> tuple[Optional[T], Optional[HttpResponseBadRequest]]:
#     """
#     Safely get a database object or return HttpResponseBadRequest.

#     ASYNC-SAFE: Pure ORM operation, wrap with sync_to_async if needed in async contexts

#     Args:
#         model: Django model class to query
#         error_message: Error message for HttpResponseBadRequest
#         log_error: Whether to log the error
#         **lookup_kwargs: Lookup arguments for the query

#     Returns:
#         Tuple of (object, None) on success or (None, error_response) on failure

#     Example:
#         entry, error = safe_get_or_error(
#             IndexData,
#             error_message="Entry not found",
#             unique_sha256=sha256
#         )
#         if error:
#             return error
#         # Use entry...
#     """
#     try:
#         obj = model.objects.get(**lookup_kwargs)
#         return obj, None
#     except model.DoesNotExist:
#         if log_error:
#             logger.error(f"{model.__name__} not found: {lookup_kwargs}")
#         return None, HttpResponseBadRequest(content=error_message)


# def safe_get_with_callback(
#     model: type[T],
#     found_callback: Optional[Callable[[T], None]] = None,
#     not_found_callback: Optional[Callable[[], None]] = None,
#     **lookup_kwargs,
# ) -> tuple[bool, Optional[T]]:
#     """
#     Get object and execute callbacks based on success/failure.

#     ASYNC-SAFE: Pure ORM operation, wrap with sync_to_async if needed in async contexts

#     Args:
#         model: Django model class to query
#         found_callback: Function to call when object is found (receives object)
#         not_found_callback: Function to call when object is not found
#         **lookup_kwargs: Lookup arguments for the query

#     Returns:
#         Tuple of (found: bool, object: Optional[T])

#     Example:
#         found, directory = safe_get_with_callback(
#             IndexDirs,
#             found_callback=lambda d: d.invalidate_thumb(),
#             dir_fqpn_sha256=sha256
#         )
#         return (found, directory if found else IndexDirs.objects.none())
#     """
#     try:
#         obj = model.objects.get(**lookup_kwargs)
#         if found_callback:
#             found_callback(obj)
#         return True, obj
#     except model.DoesNotExist:
#         if not_found_callback:
#             not_found_callback()
#         return False, None
