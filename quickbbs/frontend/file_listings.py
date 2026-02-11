from __future__ import annotations

import asyncio
from pathlib import Path

import filetypes.models as filetype_models
from django.conf import settings

from quickbbs.common import normalize_string_lower, normalize_string_title


def _filter_and_process_item(item, ext_ignore, files_ignore, ignore_dots):
    """
    Filter and process a single directory item.

    ASYNC-SAFE: Pure function with no DB/IO operations (file stats only)

    Args:
        item: os.DirEntry object to process
        ext_ignore: Set of file extensions to ignore
        files_ignore: Set of filenames to ignore
        ignore_dots: Whether to ignore dot files

    Returns:
        Tuple of (title_cased_name, item) if item passes filters, None otherwise
    """
    try:
        name_lower = normalize_string_lower(item.name)

        # Skip dot files early if configured
        if ignore_dots and name_lower.startswith("."):
            return None

        # Skip ignored files early
        if name_lower in files_ignore:
            return None

        # Determine file extension
        if item.is_dir():
            fext = ".dir"
        else:
            # Use pathlib for consistent extension extraction (matches utilities.py pattern)
            path_obj = Path(name_lower)
            fext = path_obj.suffix.lower() if path_obj.suffix else ".none"

        # Skip ignored extensions and unknown filetypes
        if fext in ext_ignore or not filetype_models.filetypes.filetype_exists_by_ext(fext):
            return None

        return (normalize_string_title(item.name), item)

    except (OSError, PermissionError):
        # Skip items we can't access
        return None


def _process_items(items, ext_ignore, files_ignore, ignore_dots):
    """
    Process directory items with filtering.

    Core processing logic shared by both single-threaded and batched processing.
    Iterates through items, applies filters, and builds result dictionary.

    ASYNC-SAFE: Pure function with no DB/IO operations (file stats only)

    Args:
        items: Iterable of os.DirEntry objects to process
        ext_ignore: Set of file extensions to ignore
        files_ignore: Set of filenames to ignore
        ignore_dots: Whether to ignore dot files

    Returns:
        Dictionary mapping title-cased names to DirEntry objects
    """
    fs_data = {}
    for item in items:
        processed_item = _filter_and_process_item(item, ext_ignore, files_ignore, ignore_dots)
        if processed_item:
            fs_data[processed_item[0]] = processed_item[1]
    return fs_data


def return_disk_listing_sync(fqpn: str) -> tuple[bool, dict]:
    """
    Synchronous version of return_disk_listing for use in sync contexts.

    Scans a directory and returns filtered file/directory entries.
    Obeys EXTENSIONS_TO_IGNORE, FILES_TO_IGNORE, and IGNORE_DOT_FILES settings.

    Args:
        fqpn: The fully qualified pathname of the directory to scan

    Returns:
        Tuple of (success_status, file_data_dict)
    """
    try:
        items = list(Path(fqpn).iterdir())
        return _single_threaded_listing(items)
    except FileNotFoundError:
        return False, {}


async def return_disk_listing(fqpn, **kwargs) -> tuple[bool, dict]:
    """
    Async version of return_disk_listing. Delegates to sync version via thread.

    This code obeys the following quickbbs_settings, settings:
    * EXTENSIONS_TO_IGNORE
    * FILES_TO_IGNORE
    * IGNORE_DOT_FILES

    Args:
        fqpn: The fully qualified pathname of the directory to scan
        **kwargs: Accepted for backward compatibility (use_async, batch_size, max_workers)

    Returns:
        Tuple of (success_status, file_data_dict)
    """
    return await asyncio.to_thread(return_disk_listing_sync, fqpn)


def _single_threaded_listing(items) -> tuple[bool, dict]:
    """
    Single-threaded processing - most efficient for small directories.

    ASYNC-SAFE: Uses _process_items which is async-safe

    Args:
        items: Iterable of os.DirEntry objects to process

    Returns:
        Tuple of (success_status, file_data_dict)
    """
    # Pre-compute settings checks
    ext_ignore = settings.EXTENSIONS_TO_IGNORE
    files_ignore = settings.FILES_TO_IGNORE
    ignore_dots = settings.IGNORE_DOT_FILES

    # Use shared processing logic
    fs_data = _process_items(items, ext_ignore, files_ignore, ignore_dots)

    return True, fs_data


# Alias for backward compatibility
return_disk_listing_async = return_disk_listing
