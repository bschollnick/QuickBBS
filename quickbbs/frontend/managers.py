"""
QuickBBS Frontend Managers.

Context building for item views, layout management with database-level
pagination, and cached query functions for gallery rendering.

All database functions are sync; async wrappers are provided for ASGI
views via sync_to_async.
"""

from __future__ import annotations

import datetime
import logging
import math
import time
from pathlib import Path

from asgiref.sync import sync_to_async
from cachetools import cached
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Q
from django.http import HttpResponseBadRequest

from frontend.utilities import (
    convert_to_webpath,
    return_breadcrumbs,
)
from quickbbs.cache_registry import (
    build_context_info_cache,
    layout_manager_cache,
)
from quickbbs.common import SORT_MATRIX
from quickbbs.fileindex import FILEINDEX_SR_FILETYPE_HOME_VIRTUAL
from quickbbs.models import (
    DirectoryIndex,  # used in docstring type annotations
    FileIndex,
)
from thumbnails.models import ThumbnailFiles


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
    entry = FileIndex.get_by_sha256(unique_file_sha256, unique=True, select_related=FILEINDEX_SR_FILETYPE_HOME_VIRTUAL)
    if entry is None:
        return HttpResponseBadRequest(content="No entry found.")

    start_time = time.perf_counter()
    webpath = entry.fqpndirectory.lower().replace("//", "/")
    directory_entry = entry.home_directory

    # Get navigation data - optimized to avoid materializing all SHAs when possible
    if show_duplicates:
        # Include duplicates - use optimized queryset operations instead of materializing all SHAs
        files_qs = (
            FileIndex.objects.filter(home_directory=directory_entry.pk, delete_pending=False)
            .order_by(*SORT_MATRIX[sort_order_value])
            .values_list("unique_sha256", flat=True)
        )

        # Get count (single aggregate query)
        all_shas_count = files_qs.count()

        # Find current position by counting items that sort before this one
        # Build filter conditions based on sort order
        sort_fields = SORT_MATRIX[sort_order_value]

        # Strip ordering prefixes for .values() call (remove '-' prefix)
        value_fields = [f.lstrip("-") for f in sort_fields]

        # Get the current entry's sort values for comparison
        current_file = FileIndex.objects.filter(unique_sha256=unique_file_sha256).values(*value_fields).first()

        if current_file:
            # Build Q object for files that come before current file in sort order
            # For multi-field sorting, we need to build a complex Q object
            q_before = Q()
            for i, field in enumerate(sort_fields):
                is_desc = field.startswith("-")
                field_name = field.lstrip("-")

                # Build cumulative condition for multi-field sort
                q_equal_so_far = Q()
                for prev_field in sort_fields[:i]:
                    prev_field_name = prev_field.lstrip("-")
                    q_equal_so_far &= Q(**{prev_field_name: current_file[prev_field_name]})

                if is_desc:
                    q_this_field = Q(**{f"{field_name}__gt": current_file[field_name]})
                else:
                    q_this_field = Q(**{f"{field_name}__lt": current_file[field_name]})

                q_before |= q_equal_so_far & q_this_field

            current_page = files_qs.filter(q_before).count() + 1
        else:
            current_page = 1

        # Get specific SHAs using queryset slicing (only fetches needed rows)
        first_sha = files_qs.first() or ""
        last_sha = files_qs.last() or ""

        # Get next/previous using efficient slicing
        if current_page < all_shas_count:
            next_result = files_qs[current_page : current_page + 1]
            next_sha = next_result[0] if next_result else ""
        else:
            next_sha = ""

        if current_page > 1:
            prev_result = files_qs[current_page - 2 : current_page - 1]
            previous_sha = prev_result[0] if prev_result else ""
        else:
            previous_sha = ""

    else:
        # Deduplicate using cached distinct SHA list.
        # get_distinct_file_shas() is backed by distinct_files_cache, keyed on
        # (directory, sort). This means all per-file build_context_info calls for the
        # same directory share one cached list instead of each running 2 DB queries.
        all_shas = directory_entry.get_distinct_file_shas(sort=sort_order_value)

        # Get pagination data inline
        try:
            current_page = all_shas.index(unique_file_sha256) + 1
        except ValueError:
            current_page = 1

        all_shas_count = len(all_shas)
        next_sha = all_shas[current_page] if current_page < all_shas_count else ""
        previous_sha = all_shas[current_page - 2] if current_page > 1 else ""
        first_sha = all_shas[0] if all_shas else ""
        last_sha = all_shas[all_shas_count - 1] if all_shas else ""

    # Single comprehensive dictionary creation
    context = {
        # Core data
        "unique_file_sha256": unique_file_sha256,
        "file_sha256": entry.file_sha256,
        "home_directory_id": directory_entry.pk,
        # Cached DirectoryIndex instance — used as a query anchor by htmx_view_item
        # for thumbnail enqueuing. Staleness is acceptable since files_in_dir()
        # issues a fresh query via the FK relationship.
        "home_directory": directory_entry,
        "sort": sort_order_value,
        "html": entry.get_content_html(webpath),
        # Navigation (inline breadcrumb processing)
        "breadcrumbs": return_breadcrumbs(webpath),
        "up_uri": convert_to_webpath(str(Path(entry.full_filepathname).parent)).rstrip("/"),
        "webpath": webpath,
        # File context (inline)
        "filetype": entry.filetype,
        "sha": entry.unique_sha256,
        "filename": entry.name,
        "gallery_name": "",  # Don't show filename in breadcrumb (already shown in title)
        "filesize": entry.size,
        "duration": entry.duration,
        "is_animated": entry.is_animated,
        "lastmod": entry.lastmod,
        "lastmod_ds": datetime.datetime.fromtimestamp(entry.lastmod).strftime("%m/%d/%y %H:%M:%S"),
        # DEPRECATED: filetype_icon_filename is unused by templates. Remove after 2026-06-01.
        # "filetype_icon_filename": entry.filetype.icon_filename,
        "download_uri": entry.get_download_url(),
        "thumbnail_uri": entry.get_thumbnail_url(size="large"),
        # Pagination (computed inline)
        "page": current_page,
        "pagecount": all_shas_count,
        "first_sha": first_sha,
        "last_sha": last_sha,
        "next_sha": next_sha,
        "previous_sha": previous_sha,
        "page_locale": (current_page - 1) // settings.GALLERY_ITEMS_PER_PAGE + 1,
        # DEPRECATED: dir_link is unused by templates. Remove after 2026-06-01.
        # "dir_link": f"{webpath}{entry.name}?sort={sort_order_value}",
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
    # Extract and validate sort order before calling cached function
    try:
        sort_order_value = int(request.GET.get("sort", 0)) if request else 0
    except (ValueError, TypeError):
        sort_order_value = 0
    if sort_order_value not in SORT_MATRIX:
        sort_order_value = 0

    return await sync_to_async(build_context_info)(
        unique_file_sha256=unique_file_sha256,
        sort_order_value=sort_order_value,
        show_duplicates=show_duplicates,
    )


def _get_files_needing_thumbnails(directory, sort_ordering: int):
    """
    Return queryset of file SHA256 hashes that don't have valid thumbnails.

    Delegates to ThumbnailFiles.get_files_needing_thumbnail_shas() which owns
    this logic as thumbnail domain knowledge.

    Args:
        directory: DirectoryIndex object
        sort_ordering: Sort order to apply

    Returns:
        QuerySet of file SHA256 hashes without thumbnails.
    """
    return ThumbnailFiles.get_files_needing_thumbnail_shas(directory, sort_ordering)


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
def layout_manager(page_number: int = 1, directory=None, sort_ordering: int = 0, show_duplicates: bool = False) -> dict:
    """
    Manage gallery layout with optimized database-level pagination.

    Uses database LIMIT/OFFSET for efficient pagination instead of loading
    all items into memory. Only fetches data for the requested page.

    Args:
        page_number: Current page number (1-indexed)
        directory: DirectoryIndex object representing the directory to layout
        sort_ordering: Sort order to apply (0-2), defaults to 0 (name)
        show_duplicates: Whether to show duplicate files
    Returns: Dictionary containing pagination data and current page items
    Raises:
        ValueError: If directory parameter is None
    """
    start_time = time.perf_counter()
    if directory is None:
        raise ValueError("Directory parameter is required")

    items_per_page = settings.GALLERY_ITEMS_PER_PAGE

    # Get base querysets first
    directories_qs = directory.dirs_in_dir(sort=sort_ordering, fields_only=("dir_fqpn_sha256",), select_related=(), prefetch_related=())
    dirs_count = directories_qs.count()

    # Handle files differently based on show_duplicates to avoid over-fetching
    if show_duplicates:
        # Include duplicates - use simple queryset (no materialization needed)
        files_qs = directory.files_in_dir(sort=sort_ordering, distinct=False, fields_only=("unique_sha256",), select_related=())
        files_count = files_qs.count()
    else:
        # Deduplicate - use cached distinct file list
        # This prevents materializing ALL files when we only need current page
        # DirectoryIndex.get_distinct_file_shas() caches results for efficient page navigation
        all_distinct_shas = directory.get_distinct_file_shas(sort=sort_ordering)
        files_count = len(all_distinct_shas)

    total_items = dirs_count + files_count

    # Calculate pagination
    total_pages = max(1, math.ceil(total_items / items_per_page))
    bounds = calculate_page_bounds(page_number, items_per_page, dirs_count)

    # Fetch ONLY current page data using database slicing
    page_data = {}

    if bounds["dirs_slice"]:
        start, end = bounds["dirs_slice"]
        page_directories = list(directories_qs[start:end].values_list("dir_fqpn_sha256", flat=True))
        page_data["directory_shas"] = page_directories
        page_data["dir_count"] = len(page_directories)
    else:
        page_data["directory_shas"] = []
        page_data["dir_count"] = 0

    if bounds["files_slice"]:
        start, end = bounds["files_slice"]
        if show_duplicates:
            # Simple queryset slicing - no distinct needed
            page_files = list(files_qs[start:end].values_list("unique_sha256", flat=True))
        else:
            # Slice the cached distinct list - cheap list slicing (no DB query)
            page_files = all_distinct_shas[start:end]
        page_data["file_shas"] = page_files
        page_data["file_count"] = len(page_files)
    else:
        page_data["file_shas"] = []
        page_data["file_count"] = 0

    page_data["total_count"] = page_data["dir_count"] + page_data["file_count"]
    page_data["page"] = page_number

    # Build optimized output structure - only current page data
    output = {
        "page_items": page_data,  # Current page items (directories and files)
        "page_number": page_number,
        "dirs_count": dirs_count,
        # DEPRECATED: chunk_size is unused by views/templates. Remove after 2026-06-01.
        # "chunk_size": items_per_page,
        "files_count": files_count,
        "total_pages": total_pages,
        # DEPRECATED: dirs_on_last_page, files_on_last_page are unused by views/templates. Remove after 2026-06-01.
        # "dirs_on_last_page": dirs_count % items_per_page,
        # "files_on_last_page": items_per_page - (dirs_count % items_per_page),
    }

    # DEPRECATED: page_shas is unused by views/templates. Remove after 2026-06-01.
    # output["page_shas"] = page_data["directory_shas"] + page_data["file_shas"]

    # NOTE: files_needing_thumbnails is intentionally NOT included here.
    # It is computed separately by the caller to avoid invalidating the
    # cached layout data when thumbnails are generated. Thumbnail creation
    # does not change pagination boundaries or file lists.

    # Calculate page_locale - which page this directory appears on in its parent
    if directory.parent_directory:
        sibling_directories = directory.parent_directory.dirs_in_dir(
            sort=sort_ordering, fields_only=("dir_fqpn_sha256",), select_related=(), prefetch_related=()
        )
        sibling_dir_shas = list(sibling_directories.values_list("dir_fqpn_sha256", flat=True))
        try:
            position = sibling_dir_shas.index(directory.dir_fqpn_sha256)
            page_locale = position // items_per_page + 1
        except ValueError:
            page_locale = 1
    else:
        page_locale = 1

    output["page_locale"] = page_locale

    build_time = time.perf_counter() - start_time
    logging.debug("Optimized layout manager completed in %.4f seconds", build_time)
    return output


# ASGI: Async wrapper for layout_manager
async def async_layout_manager(page_number: int = 1, directory=None, sort_ordering: int = 0, show_duplicates: bool = False) -> dict:
    """
    Async wrapper for layout_manager to support ASGI views.

    Args:
        page_number: Current page number (1-indexed)
        directory: DirectoryIndex object representing the directory to layout
        sort_ordering: Sort order to apply (0-2), defaults to 0 (name)
        show_duplicates: Whether to show duplicate files
    Returns: Dictionary containing pagination data and current page items
    """
    return await sync_to_async(layout_manager)(
        page_number=page_number, directory=directory, sort_ordering=sort_ordering, show_duplicates=show_duplicates
    )
