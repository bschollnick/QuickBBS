from __future__ import annotations

import asyncio
import os
from pathlib import Path

import filetypes.models as filetype_models
from asgiref.sync import sync_to_async
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
        result = _filter_and_process_item(item, ext_ignore, files_ignore, ignore_dots)
        if result:
            fs_data[result[0]] = result[1]
    return fs_data


async def return_disk_listing(fqpn, use_async=True, batch_size=25, max_workers=4) -> tuple[bool, dict]:
    """
    This code obeys the following quickbbs_settings, settings:
    * EXTENSIONS_TO_IGNORE
    * FILES_TO_IGNORE
    * IGNORE_DOT_FILES

    Args:
        fqpn: The fully qualified pathname of the directory to scan
        use_async: Whether to use async tasks for large directories
        batch_size: Number of items to process per batch
        max_workers: Maximum number of concurrent tasks to use

    Returns: tuple[bool, dict] - Success status and dict of file data
    """
    try:
        # Use asyncio.to_thread for potentially blocking I/O
        path = Path(fqpn)
        items = await asyncio.to_thread(list, path.iterdir())

        # For small directories or when async disabled, use single-threaded approach
        if not use_async or len(items) < batch_size:
            return await asyncio.to_thread(_single_threaded_listing, items)

        # Pre-compute settings for async processing
        ext_ignore = settings.EXTENSIONS_TO_IGNORE
        files_ignore = settings.FILES_TO_IGNORE
        ignore_dots = settings.IGNORE_DOT_FILES

        # Split items into batches
        batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

        fs_data = {}

        # Use asyncio tasks for concurrent processing
        async_process_batch = sync_to_async(_process_items, thread_sensitive=True)

        # Process batches with limited concurrency
        for i in range(0, len(batches), max_workers):
            batch_group = batches[i : i + max_workers]
            tasks = [async_process_batch(batch, ext_ignore, files_ignore, ignore_dots) for batch in batch_group]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, dict):
                    fs_data.update(result)

        return True, fs_data

    except FileNotFoundError:
        return False, {}
    except Exception:
        # Fallback to single-threaded on any async issues
        try:
            return await asyncio.to_thread(_single_threaded_listing, list(Path(fqpn).iterdir()))
        except FileNotFoundError:
            return False, {}


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
