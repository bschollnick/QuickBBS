"""
QuickBBS Frontend Managers.

Context building for item views, layout management with database-level
pagination, and cached query functions for gallery rendering.
"""

from __future__ import annotations

import datetime
import logging
import math
import time
from typing import TYPE_CHECKING

from cachetools import cached
from cachetools.keys import hashkey
from django.conf import settings
from django.http import HttpResponseBadRequest

if TYPE_CHECKING:
    from django.contrib.auth.base_user import AbstractBaseUser
    from django.contrib.auth.models import AnonymousUser

from frontend.utilities import (
    convert_to_webpath,
    return_breadcrumbs,
)
from interactive_fiction.models import Story
from quickbbs.cache_registry import layout_manager_cache
from quickbbs.common import normalize_sha_input
from quickbbs.directoryindex import get_ordered_sibling_dirs
from quickbbs.fileindex import FILEINDEX_SR_FILETYPE_HOME_VIRTUAL
from quickbbs.models import FileIndex
from thumbnails.models import ThumbnailFiles


def build_context_info(
    unique_file_sha256: str,
    sort_order_value: int = 0,
    show_duplicates: bool = False,
    user: "AbstractBaseUser | AnonymousUser | None" = None,
) -> dict | HttpResponseBadRequest:
    """
    Build context information for item view using optimized single-pass dictionary creation.

    All item view requests use this function to gather file metadata,
    navigation information, and rendering context. This function uses an optimized
    approach that builds the entire context dictionary in a single operation,
    eliminating multiple dictionary updates and function call overhead.

    This function is not itself cached, but its heavy lookups read through
    per-object caches: FileIndex.get_by_sha256 (fileindex_cache),
    get_distinct_file_shas (distinct_files_cache), get_all_file_shas
    (all_files_shas_cache), and get_dir_counts (dir_counts_cache), so repeat
    item views for the same directory issue few or no queries.

    Args:
        unique_file_sha256: The unique SHA256 hash of the item
        sort_order_value: Sort order to apply (0=name, 1=date, 2=name only)
        show_duplicates: Whether to show duplicate files (affects navigation list)
        user: Requesting user for favorite-first ordering (SORT_MATRIX's
            leading -is_favorited key). None (default) omits favorites from
            the ordering, matching layout_manager's anonymous-user behavior.
    Returns: Dictionary containing context data or HttpResponseBadRequest on error
    """
    if not unique_file_sha256:
        return HttpResponseBadRequest(content="No SHA256 provided.")

    unique_file_sha256 = normalize_sha_input(unique_file_sha256)
    entry = FileIndex.get_by_sha256(unique_file_sha256, unique=True, select_related=FILEINDEX_SR_FILETYPE_HOME_VIRTUAL)
    if entry is None:
        return HttpResponseBadRequest(content="No entry found.")

    start_time = time.perf_counter()
    webpath = convert_to_webpath(entry.fqpndirectory.replace("//", "/"))
    directory_entry = entry.home_directory

    # Get navigation data from the directory's cached ordered SHA list.
    # Both branches share the same shape: fetch the (directory, sort)-keyed
    # cached list once, then resolve position/prev/next with list arithmetic.
    # layout_manager reads the same lists, so item-view navigation and gallery
    # page order agree even for rows with tied sort keys.
    if show_duplicates:
        # Include duplicates - cached full SHA list (all_files_shas_cache)
        all_shas = directory_entry.get_all_file_shas(sort=sort_order_value, user=user)
    else:
        # Deduplicate - cached distinct SHA list (distinct_files_cache)
        all_shas = directory_entry.get_distinct_file_shas(sort=sort_order_value, user=user)

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

    # Subdirectory count needed to compute the correct gallery page for the "up" link.
    # Gallery pages interleave dirs then files, so file at position N among files is at
    # overall position (dirs_count + N - 1), which determines which gallery page it appears on.
    dirs_count = directory_entry.get_dir_counts()

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
        "up_uri": webpath.rstrip("/"),  # webpath is already web-relative after convert_to_webpath()
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
        "page_locale": (dirs_count + current_page - 1) // settings.GALLERY_ITEMS_PER_PAGE + 1,
        # DEPRECATED: dir_link is unused by templates. Remove after 2026-06-01.
        # "dir_link": f"{webpath}{entry.name}?sort={sort_order_value}",
        # Interactive Fiction (Step 9): a scanner-ingested .inkj file's item
        # view links to its play page. None for every other filetype, and
        # for an .inkj file whose Story row hasn't been created yet (e.g.
        # scanned but not yet ingested, or ingestion rejected it) — the
        # template only renders the link when this is set.
        "if_story_slug": (
            Story.objects.filter(source_fqfn=entry.full_filepathname).values_list("slug", flat=True).first()
            if entry.filetype.fileext == ".inkj"
            else None
        ),
    }

    build_time = time.perf_counter() - start_time
    logging.debug("Context built in %.4f seconds", build_time)
    return context


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


def _layout_manager_key(page_number: int, directory, sort_ordering: int, show_duplicates: bool, user=None):
    """
    Build the cache key for layout_manager using directory.pk instead of the full model instance.

    Using directory.pk (an int) rather than the DirectoryIndex object means:
    - clear_layout_cache_for_directories() can invalidate entries with a direct int
      comparison (key[1] in directory_ids) instead of scanning for model instances.
    - The key is stable across different query paths that load the same directory —
      no risk of identity vs. equality mismatches if Django's __hash__ behaviour changes.

    user.pk is appended last (not inserted earlier in the tuple) so
    key[1] (directory pk) stays at its existing position —
    clear_layout_cache_for_directories() reads it by that fixed index.

    Args:
        page_number: Current page number (1-indexed)
        directory: DirectoryIndex object (only .pk is used in the key)
        sort_ordering: Sort order to apply (0-2)
        show_duplicates: Whether duplicate files are included
        user: Requesting user for favorite-first ordering. None/anonymous
            collapses to the same key as before this parameter existed.
    Returns: cachetools hashkey tuple
    """
    user_pk = user.pk if user is not None and user.is_authenticated else None
    return hashkey(page_number, directory.pk if directory is not None else None, sort_ordering, show_duplicates, user_pk)


@cached(layout_manager_cache, key=_layout_manager_key)
def layout_manager(  # pylint: disable=too-many-locals
    page_number: int = 1,
    directory=None,
    sort_ordering: int = 0,
    show_duplicates: bool = False,
    user: "AbstractBaseUser | AnonymousUser | None" = None,
) -> dict:
    """
    Manage gallery layout with optimized database-level pagination.

    Uses database LIMIT/OFFSET for efficient pagination instead of loading
    all items into memory. Only fetches data for the requested page.

    Cache key is built by _layout_manager_key, which uses directory.pk rather than
    the full DirectoryIndex object so that cache invalidation can use a direct int
    comparison instead of scanning for model instances.

    Args:
        page_number: Current page number (1-indexed)
        directory: DirectoryIndex object representing the directory to layout
        sort_ordering: Sort order to apply (0-2), defaults to 0 (name)
        show_duplicates: Whether to show duplicate files
        user: Requesting user for favorite-first ordering (threaded into
            dirs_in_dir()/get_all_file_shas()/get_distinct_file_shas(), whose
            SORT_MATRIX/DIR_SORT_MATRIX leading -is_favorited key needs it).
            None (default) — byte-identical to the query before this
            parameter existed.
    Returns: Dictionary containing pagination data and current page items
    Raises:
        ValueError: If directory parameter is None
    """
    start_time = time.perf_counter()
    if directory is None:
        raise ValueError("Directory parameter is required")

    items_per_page = settings.GALLERY_ITEMS_PER_PAGE

    # Get base querysets first
    directories_qs = directory.dirs_in_dir(sort=sort_ordering, fields_only=("dir_fqpn_sha256",), select_related=(), prefetch_related=(), user=user)
    # Reads through dir_counts_cache (invalidated with the layout cache) —
    # directories_qs is still needed below for the page slice.
    dirs_count = directory.get_dir_counts()

    # Both modes read the directory's cached ordered SHA list — the same lists
    # build_context_info navigates, so gallery page order and item-view
    # prev/next agree even for rows with tied sort keys.
    if show_duplicates:
        # Include duplicates - cached full SHA list (all_files_shas_cache)
        all_shas = directory.get_all_file_shas(sort=sort_ordering, user=user)
    else:
        # Deduplicate - cached distinct SHA list (distinct_files_cache)
        all_shas = directory.get_distinct_file_shas(sort=sort_ordering, user=user)
    files_count = len(all_shas)

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
        # Slice the cached SHA list - cheap list slicing (no DB query)
        page_files = all_shas[start:end]
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

    # Calculate page_locale - which page this directory appears on in its parent.
    # Attname check avoids lazy-loading the parent row; the ordered sibling list
    # comes from sibling_dirs_cache (shared with get_prev_next_siblings).
    if directory.parent_directory_id:
        sibling_dir_shas = [sha for sha, _ in get_ordered_sibling_dirs(directory.parent_directory_id, sort_ordering)]
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
