"""Common utility functions for QuickBBS application."""

import hashlib
import logging
import os
import pathlib
from typing import TypeVar

from cachetools import LRUCache, cached
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)

# Type variable for Django models
T = TypeVar("T", bound=models.Model)

# Async-safe caches for common utility functions
normalized_strings_cache = LRUCache(maxsize=settings.NORMALIZED_STRINGS_CACHE_SIZE)
directory_sha_cache = LRUCache(maxsize=settings.DIRECTORY_SHA_CACHE_SIZE)
normalized_paths_cache = LRUCache(maxsize=settings.NORMALIZED_PATHS_CACHE_SIZE)

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
