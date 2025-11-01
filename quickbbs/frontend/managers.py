"""
QuickBBS Frontend Managers Module.

This module provides optimized management functions for the QuickBBS gallery application,
including context building, layout management, and file processing utilities.

Key Components:
- Context building for item views with optimized single-pass dictionary creation
- Layout management with database-level pagination for efficient gallery rendering
- Text file processing with encoding detection and size limits
- Path normalization utilities for consistent file system operations
- Cached query functions for improved performance

Performance Features:
- LRU caching for expensive operations (directory queries, context building)
- Streamlined data flow with minimal memory allocations
- Database query optimization with queryset reuse
- Cached Markdown processor for text file rendering

Architecture:
- Follows Django ORM best practices with efficient query patterns
- Uses in-place dictionary population to minimize memory overhead
- Implements proper separation between database operations and file I/O
- Provides reusable pagination utilities for list-based navigation

ASGI Support:
- All functions with database queries can be wrapped with sync_to_async
- Async wrapper functions provided for core operations
"""

import datetime
import logging
import math
import os
import time

# from functools import lru_cache
# from itertools import chain
from pathlib import Path

import charset_normalizer
import markdown2

# from cache_watcher.models import Cache_Storage
from asgiref.sync import sync_to_async
from cachetools import LRUCache, cached
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import (  # HttpResponse,; Http404,; HttpRequest,; HttpResponseNotFound,; JsonResponse,
    HttpResponseBadRequest,
)

# from filetypes.models import load_filetypes
from frontend.utilities import (  # SORT_MATRIX,
    convert_to_webpath,
    return_breadcrumbs,
)
from quickbbs.models import IndexData

layout_manager_cache = LRUCache(maxsize=500)

build_context_info_cache = LRUCache(maxsize=500)

# File size limit for text file processing (1MB)
MAX_TEXT_FILE_SIZE = 1024 * 1024

# Cached Markdown processor instance
_markdown_processor = markdown2.Markdown()


def get_file_text_encoding(filename: str) -> str:
    """
    Detect the text encoding of a file.

    Reads only the first 4KB for efficient encoding detection.
    Uses charset_normalizer for robust encoding detection.

    ASYNC-SAFE: Pure file I/O, no Django ORM operations.
    For async contexts, wrap with: await asyncio.to_thread(get_file_text_encoding, filename)

    Args:
        filename: Path to the file to analyze

    Returns:
        Detected encoding string, defaults to 'utf-8' if detection fails
    """
    try:
        with open(filename, "rb") as f:
            raw_data = f.read(4096)  # Read only first 4KB

            # Detect encoding using charset_normalizer
            result = charset_normalizer.from_bytes(raw_data)
            best_match = result.best()
            if best_match is None:
                return "utf-8"
            encoding = best_match.encoding
            return encoding if encoding else "utf-8"
    except (OSError, IOError):
        return "utf-8"


@cached(LRUCache(maxsize=1000))
def get_file_text_encoding_cached(filename: str) -> str:
    """
    Cache text encoding detection based on filename.

    Args:
        filename: Path to the file to analyze

    Returns:
        Detected encoding string, defaults to 'utf-8' if detection fails
    """
    return get_file_text_encoding(filename)


def _process_text_file(filename: str, is_markdown: bool = False) -> str:
    """
    Process text or HTML files with size limits and encoding detection.

    ASYNC-SAFE: Pure file I/O, no Django ORM operations.
    For async contexts, wrap with: await asyncio.to_thread(_process_text_file, filename, is_markdown)

    Args:
        filename: Path to the file to process
        is_markdown: Whether to process as markdown (True) or HTML (False)

    Returns:
        Processed HTML content or error message
    """
    try:
        # Use single stat call for both size and mtime
        file_path = Path(filename)
        stat_info = file_path.stat()

        # Check file size limit
        if stat_info.st_size > MAX_TEXT_FILE_SIZE:
            return f"<p><em>File too large to display ({stat_info.st_size:,} bytes). " f"Maximum size: {MAX_TEXT_FILE_SIZE:,} bytes.</em></p>"

        encoding = get_file_text_encoding_cached(filename)

        with open(filename, "r", encoding=encoding) as f:
            content = f.read()

            # Process content based on type
            if is_markdown:
                return _markdown_processor.convert(content)
            return content.replace("\n", "<br>")

    except UnicodeDecodeError:
        return "<p><em>We are unable to view this file.</em></p>"
    except (OSError, IOError) as e:
        return f"<p><em>Error reading file: {str(e)}</em></p>"


@cached(build_context_info_cache)
def build_context_info(unique_file_sha256: str, sort_order_value: int = 0, show_duplicates: bool = False) -> dict | HttpResponseBadRequest:
    """
    Build context information for item view using optimized single-pass dictionary creation.

    All item view requests use this function to gather file metadata,
    navigation information, and rendering context. This function uses an optimized
    approach that builds the entire context dictionary in a single operation,
    eliminating multiple dictionary updates and function call overhead.

    IMPORTANT: Cache key now uses (unique_file_sha256, sort_order_value, show_duplicates)
    instead of request object, enabling proper caching across requests.

    Args:
        unique_file_sha256: The unique SHA256 hash of the item
        sort_order_value: Sort order to apply (0=name, 1=date, 2=name only)
        show_duplicates: Whether to show duplicate files (affects navigation list)
    Returns: Dictionary containing context data or HttpResponseBadRequest on error
    """
    if not unique_file_sha256:
        return HttpResponseBadRequest(content="No SHA256 provided.")

    unique_file_sha256 = unique_file_sha256.strip().lower()
    entry = IndexData.get_by_sha256(unique_file_sha256, unique=True)
    if entry is None:
        return HttpResponseBadRequest(content="No entry found.")

    start_time = time.perf_counter()
    webpath = entry.fqpndirectory.lower().replace("//", "/")
    directory_entry = entry.home_directory

    # Build entire context in single operation for optimal performance
    pathmaster = Path(entry.full_filepathname)
    lastmod_timestamp = entry.lastmod

    # Get all file SHAs from directory - handle both list and QuerySet return types
    # files_in_dir returns list when distinct=True, QuerySet when distinct=False
    files_result = directory_entry.files_in_dir(sort=sort_order_value, distinct=not show_duplicates)
    if isinstance(files_result, list):
        # distinct=True case - files_in_dir returned list of objects (already deduplicated)
        all_shas = [f.unique_sha256 for f in files_result]
    else:
        # distinct=False case - files_in_dir returned QuerySet (includes duplicates)
        all_shas = list(files_result.values_list("unique_sha256", flat=True))

    # Get pagination data inline
    try:
        current_page = all_shas.index(unique_file_sha256) + 1
    except ValueError:
        current_page = 1

    all_shas_count = len(all_shas)
    next_sha = all_shas[current_page] if current_page < all_shas_count else ""
    previous_sha = all_shas[current_page - 2] if current_page > 1 else ""

    # Single comprehensive dictionary creation
    context = {
        # Core data
        "unique_file_sha256": unique_file_sha256,
        "file_sha256": entry.file_sha256,
        "sort": sort_order_value,
        "html": _process_file_content(entry, webpath),
        # Navigation (inline breadcrumb processing)
        "breadcrumbs": return_breadcrumbs(webpath),
        "up_uri": convert_to_webpath(str(pathmaster.parent)).rstrip("/"),
        "webpath": webpath,
        # File context (inline)
        "filetype": entry.filetype.__dict__,
        "sha": entry.unique_sha256,
        "filename": entry.name,
        "gallery_name": entry.name,  # For template breadcrumb display
        "filesize": entry.size,
        "duration": entry.duration,
        "is_animated": entry.is_animated,
        "lastmod": lastmod_timestamp,
        "lastmod_ds": datetime.datetime.fromtimestamp(lastmod_timestamp).strftime("%m/%d/%y %H:%M:%S"),
        "ft_filename": entry.filetype.icon_filename,
        "download_uri": entry.get_download_url(),
        "thumbnail_uri": entry.get_thumbnail_url(size="large"),
        # Pagination (computed inline)
        "page": current_page,
        "pagecount": all_shas_count,
        "first_sha": all_shas[0] if all_shas else "",
        "last_sha": all_shas[all_shas_count - 1] if all_shas else "",
        "next_sha": next_sha,
        "previous_sha": previous_sha,
        "page_locale": int(current_page / settings.GALLERY_ITEMS_PER_PAGE) + 1,
        "dir_link": f"{webpath}{entry.name}?sort={sort_order_value}",
    }

    build_time = time.perf_counter() - start_time
    logging.debug("Context built in %.4f seconds", build_time)
    return context


# ASGI: Async wrapper for build_context_info
async def async_build_context_info(request: WSGIRequest, unique_file_sha256: str, show_duplicates: bool = False) -> dict | HttpResponseBadRequest:
    """
    Async wrapper for build_context_info to support ASGI views.

    All database operations are wrapped to run in thread pool.
    Extracts request-specific data (sort order) before calling cached function.

    Args:
        request: Django WSGIRequest object
        unique_file_sha256: The unique SHA256 hash of the item
        show_duplicates: Whether to show duplicate files (affects navigation list)
    Returns: Dictionary containing context data or HttpResponseBadRequest on error
    """
    # Extract request-specific data before calling cached function
    sort_order_value = int(request.GET.get("sort", default=0)) if request else 0

    return await sync_to_async(build_context_info)(
        unique_file_sha256=unique_file_sha256,
        sort_order_value=sort_order_value,
        show_duplicates=show_duplicates,
    )


def _process_file_content(entry: IndexData, webpath: str) -> str:
    """
    Process file content based on file type.

    ASYNC-SAFE: File I/O only (entry object already loaded from DB).
    For async contexts, wrap with: await asyncio.to_thread(_process_file_content, entry, webpath)

    Args:
        entry: IndexData object for the current file (pre-loaded with filetype)
        webpath: Web path for constructing file path

    Returns:
        Processed HTML content or empty string
    """
    if not (entry.filetype.is_text or entry.filetype.is_markdown or entry.filetype.is_html):
        return ""

    # Construct filesystem path from webpath
    filename = os.path.join(webpath.replace("/", os.sep), entry.name)

    if entry.filetype.is_text or entry.filetype.is_markdown:
        return _process_text_file(filename, is_markdown=True)
    if entry.filetype.is_html:
        return _process_text_file(filename, is_markdown=False)

    return ""


# def _get_directory_counts(directory) -> dict:
#     """
#     Get directory and file counts efficiently using optimized queries.

#     Args:
#         directory: IndexDirs object
#     Returns: Dictionary with dirs_count and files_count
#     """
#     # Use values() with count to reduce query overhead
#     dirs_count = directory.dirs_in_dir().values("pk").count()
#     files_count = directory.files_in_dir().values("pk").count()

#     return {"dirs_count": dirs_count, "files_count": files_count}


def _get_no_thumbnails(directory, sort_ordering: int) -> list[str]:
    """
    Get list of file SHA256s that don't have thumbnails.

    Args:
        directory: IndexDirs object
        sort_ordering: Sort order to apply
    Returns: List of file SHA256 hashes without thumbnails
    """
    return list(directory.files_in_dir(sort=sort_ordering, additional_filters={"new_ftnail__isnull": True}).values_list("file_sha256", flat=True))


def calculate_page_bounds(page_number: int, chunk_size: int, dirs_count: int) -> dict:
    """
    Calculate what directories and files belong on this page.

    Args:
        page_number: Current page number (1-indexed)
        chunk_size: Items per page
        dirs_count: Total directory count
    Returns: Dictionary with slice boundaries for directories and files
    """
    start_idx = (page_number - 1) * chunk_size
    end_idx = start_idx + chunk_size

    if start_idx < dirs_count:
        # Page starts with directories
        dirs_start = start_idx
        dirs_end = min(end_idx, dirs_count)
        dirs_on_page = dirs_end - dirs_start

        # Remaining space for files
        files_space = chunk_size - dirs_on_page
        files_start = 0
        files_end = files_space
    else:
        # Page is all files
        dirs_start = dirs_end = 0
        dirs_on_page = 0

        files_start = start_idx - dirs_count
        files_end = files_start + chunk_size

    return {
        "dirs_slice": (dirs_start, dirs_end) if dirs_on_page > 0 else None,
        "files_slice": (files_start, files_end) if files_end > files_start else None,
        "dirs_on_page": dirs_on_page,
    }


@cached(layout_manager_cache)
def layout_manager(page_number: int = 1, directory=None, sort_ordering: int | None = None, show_duplicates: bool = False) -> dict:
    """
    Manage gallery layout with optimized database-level pagination.

    Uses database LIMIT/OFFSET for efficient pagination instead of loading
    all items into memory. Only fetches data for the requested page.
    Optimized to reuse querysets for both counting and data fetching.

    Args:
        page_number: Current page number (1-indexed)
        directory: IndexDirs object representing the directory to layout
        sort_ordering: Sort order to apply (0-2)
    Returns: Dictionary containing pagination data and current page items
    :raises: ValueError if directory parameter is None
    """
    start_time = time.perf_counter()
    if directory is None:
        raise ValueError("Directory parameter is required")

    chunk_size = settings.GALLERY_ITEMS_PER_PAGE

    # Get base querysets first (more efficient for subsequent operations)
    directories_qs = directory.dirs_in_dir(sort=sort_ordering)
    files_result = directory.files_in_dir(sort=sort_ordering, distinct=not show_duplicates)

    # Get counts - handle both QuerySet and list return types
    dirs_count = directories_qs.count()
    # files_in_dir returns list when distinct=True, QuerySet when distinct=False
    files_count = len(files_result) if isinstance(files_result, list) else files_result.count()
    total_items = dirs_count + files_count

    # Calculate pagination
    total_pages = max(1, math.ceil(total_items / chunk_size))
    bounds = calculate_page_bounds(page_number, chunk_size, dirs_count)

    # Fetch ONLY current page data using database slicing
    page_data = {}

    if bounds["dirs_slice"]:
        start, end = bounds["dirs_slice"]
        page_directories = list(directories_qs[start:end].values_list("dir_fqpn_sha256", flat=True))
        page_data["directories"] = page_directories
        page_data["cnt_dirs"] = len(page_directories)
    else:
        page_data["directories"] = []
        page_data["cnt_dirs"] = 0

    if bounds["files_slice"]:
        start, end = bounds["files_slice"]
        # Handle both list and QuerySet return types from files_in_dir
        if isinstance(files_result, list):
            # files_in_dir returned a list (distinct=True case)
            page_files = [f.unique_sha256 for f in files_result[start:end]]
        else:
            # files_in_dir returned a QuerySet (distinct=False case)
            page_files = list(files_result[start:end].values_list("unique_sha256", flat=True))
        page_data["files"] = page_files
        page_data["cnt_files"] = len(page_files)
    else:
        page_data["files"] = []
        page_data["cnt_files"] = 0

    page_data["total_cnt"] = page_data["cnt_dirs"] + page_data["cnt_files"]
    page_data["page"] = page_number

    # Build optimized output structure - only current page data
    output = {
        "data": page_data,  # Single page data instead of all pages
        "page_number": page_number,
        "dirs_count": dirs_count,
        "chunk_size": chunk_size,
        "files_count": files_count,
        "total_pages": total_pages,
        "numb_of_dirs_on_dir_lastpage": dirs_count % chunk_size,
        "numb_of_files_on_dir_lastpage": chunk_size - (dirs_count % chunk_size),
    }

    # Generate all_shas for current page only (much smaller)
    output["all_shas"] = page_data["directories"] + page_data["files"]

    # Get no_thumbnails data efficiently
    output["no_thumbnails"] = _get_no_thumbnails(directory, sort_ordering)

    build_time = time.perf_counter() - start_time
    logging.debug("Optimized layout manager completed in %.4f seconds", build_time)
    return output


# ASGI: Async wrapper for layout_manager
async def async_layout_manager(page_number: int = 1, directory=None, sort_ordering: int | None = None, show_duplicates: bool = False) -> dict:
    """
    Async wrapper for layout_manager to support ASGI views.

    All database operations are wrapped to run in thread pool.

    Args:
        page_number: Current page number (1-indexed)
        directory: IndexDirs object representing the directory to layout
        sort_ordering: Sort order to apply (0-2)
    Returns: Dictionary containing pagination data and current page items
    """
    return await sync_to_async(layout_manager)(
        page_number=page_number, directory=directory, sort_ordering=sort_ordering, show_duplicates=show_duplicates
    )
