import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from pathlib import Path

import filetypes.models as filetype_models
from django.conf import settings

# from more_itertools import chunked


def _process_item_batch(items_batch, ext_ignore, files_ignore, ignore_dots):
    """Process a batch of directory items in a separate thread"""
    batch_data = {}

    for item in items_batch:
        try:
            name_lower = item.name.lower().strip()

            # Skip dot files early if configured
            if ignore_dots and name_lower.startswith("."):
                continue

            # Skip ignored files early
            if name_lower in files_ignore:
                continue

            # Determine file extension
            if item.is_dir():
                fext = ".dir"
            else:
                fext = os.path.splitext(name_lower)[1] or ".none"

            # Skip ignored extensions and unknown filetypes
            if (
                fext in ext_ignore
                or not filetype_models.filetypes.filetype_exists_by_ext(fext)
            ):
                continue

            batch_data[name_lower.title()] = item

        except (OSError, PermissionError):
            # Skip items we can't access
            continue

    return batch_data


def return_disk_listing(
    fqpn, use_threading=True, batch_size=25, max_workers=4
) -> tuple[bool, dict]:
    """
    This code obeys the following quickbbs_settings, settings:
    * EXTENSIONS_TO_IGNORE
    * FILES_TO_IGNORE
    * IGNORE_DOT_FILES

    Parameters
    ----------
    fqpn (str): The fully qualified pathname of the directory to scan
    use_threading (bool): Whether to use threading for large directories
    batch_size (int): Number of items to process per batch
    max_workers (int): Maximum number of threads to use

    Returns
    -------
    tuple[bool, dict] - Success status and dict of file data
    """
    try:
        path = Path(fqpn)
        items = list(path.iterdir())

        # For small directories or when threading disabled, use single-threaded approach
        if not use_threading or len(items) < batch_size:
            return _single_threaded_listing(items)

        # Pre-compute settings for threading
        ext_ignore = settings.EXTENSIONS_TO_IGNORE
        files_ignore = settings.FILES_TO_IGNORE
        ignore_dots = settings.IGNORE_DOT_FILES

        # Split items into batches
        batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]

        fs_data = {}

        # Use ThreadPoolExecutor - Django-safe and good for I/O bound operations
        with ThreadPoolExecutor(max_workers=min(max_workers, len(batches))) as executor:
            # Create partial function with settings
            process_func = partial(
                _process_item_batch,
                ext_ignore=ext_ignore,
                files_ignore=files_ignore,
                ignore_dots=ignore_dots,
            )

            # Submit all batches
            future_to_batch = {
                executor.submit(process_func, batch): batch for batch in batches
            }

            # Collect results as they complete
            for future in as_completed(future_to_batch, timeout=60):
                try:
                    batch_result = future.result()
                    fs_data.update(batch_result)
                except Exception:
                    # Continue processing other batches if one fails
                    continue

        return True, fs_data

    except FileNotFoundError:
        return False, {}
    except Exception:
        # Fallback to single-threaded on any threading issues
        try:
            return _single_threaded_listing(list(Path(fqpn).iterdir()))
        except FileNotFoundError:
            return False, {}


def _single_threaded_listing(items) -> tuple[bool, dict]:
    """Single-threaded processing - most efficient for small directories"""
    fs_data = {}

    # Pre-compute settings checks
    ext_ignore = settings.EXTENSIONS_TO_IGNORE
    files_ignore = settings.FILES_TO_IGNORE
    ignore_dots = settings.IGNORE_DOT_FILES

    for item in items:
        try:
            name_lower = item.name.lower()

            # Skip dot files early if configured
            if ignore_dots and name_lower.startswith("."):
                continue

            # Skip ignored files early
            if name_lower in files_ignore:
                continue

            # Determine file extension
            if item.is_dir():
                fext = ".dir"
            else:
                fext = os.path.splitext(name_lower)[1] or ".none"

            # Skip ignored extensions and unknown filetypes
            if (
                fext in ext_ignore
                or not filetype_models.filetypes.filetype_exists_by_ext(fext)
            ):
                continue

            fs_data[item.name.title().strip()] = item

        except (OSError, PermissionError):
            # Skip items we can't access
            continue

    return True, fs_data


# Alternative: Simple async version using asyncio (also Django-safe)
import asyncio


async def _process_item_async(item, ext_ignore, files_ignore, ignore_dots):
    """Process a single item asynchronously"""
    try:
        name_lower = item.name.lower()

        if ignore_dots and name_lower.startswith("."):
            return None

        if name_lower in files_ignore:
            return None

        if item.is_dir():
            fext = ".dir"
        else:
            fext = os.path.splitext(name_lower)[1] or ".none"

        if fext in ext_ignore or not filetype_models.filetypes.filetype_exists_by_ext(
            fext
        ):
            return None

        return item.name.title().strip(), item

    except (OSError, PermissionError):
        return None


async def return_disk_listing_async(fqpn) -> tuple[bool, dict]:
    """Async version - good for integration with async Django views"""
    try:
        path = Path(fqpn)
        items = list(path.iterdir())

        ext_ignore = settings.EXTENSIONS_TO_IGNORE
        files_ignore = settings.FILES_TO_IGNORE
        ignore_dots = settings.IGNORE_DOT_FILES

        # Process items concurrently
        tasks = [
            _process_item_async(item, ext_ignore, files_ignore, ignore_dots)
            for item in items
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        fs_data = {}
        for result in results:
            if result and not isinstance(result, Exception):
                name, item = result
                fs_data[name] = item

        return True, fs_data

    except FileNotFoundError:
        return False, {}
