"""
Django views for QuickBBS Gallery

ASGI: Views are being converted to async for ASGI compatibility.
Both sync and async versions will be maintained during transition.
"""

import asyncio
import datetime
import logging
import os
import pathlib
import re
import time
import urllib.parse

from asgiref.sync import sync_to_async
from cachetools import TTLCache
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.db.models import Count, Q
from django.db.utils import DatabaseError, OperationalError
from django.http import (
    Http404,
    HttpRequest,
    HttpResponseBadRequest,
    HttpResponseNotFound,
)
from django.shortcuts import render
from django.views.decorators.vary import vary_on_headers
from django_htmx.middleware import HtmxDetails

from cache_watcher.models import Cache_Storage
from frontend.managers import (
    _get_files_needing_thumbnails,
    async_build_context_info,
    async_layout_manager,
)
from frontend.utilities import (
    breadcrumbs_cache,
    convert_to_webpath,
    ensures_endswith,
    return_breadcrumbs,
    webpaths_cache,
)
from quickbbs.common import SORT_MATRIX, get_dir_sha, normalize_fqpn
from quickbbs.directoryindex import (
    DIRECTORYINDEX_SR_FILETYPE_THUMB,
    DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE_PARENT,
    directoryindex_cache,
    update_database_from_disk,
)
from quickbbs.fileindex import (
    FILEINDEX_SR_FILETYPE_HOME,
    FILEINDEX_SR_FILETYPE_HOME_VIRTUAL,
    fileindex_cache,
    fileindex_download_cache,
)
from quickbbs.cache_registry import (
    build_context_info_cache,
    distinct_files_cache,
    layout_manager_cache,
)
from quickbbs.models import (
    DirectoryIndex,
    FileIndex,
)
from quickbbs.tasks import generate_missing_thumbnails, snapshot_cache_statistics

# download_cache = LRUCache(maxsize=1000)

# =============================================================================
# SEARCH PREFETCH_RELATED CONSTANTS
# Colocated with search functions
# See related_fetches.md for usage details
# NOTE: Using tuples (not lists) so they can be used as cache keys (hashable)
# =============================================================================

# Directory search results
SEARCH_PR_FILETYPE = ("filetype",)

# File search results
SEARCH_PR_FILETYPE_HOME = ("filetype", "home_directory")


# =============================================================================
# Custom Exceptions for Directory Operations
# =============================================================================


class DirectoryNotFoundError(Exception):
    """Raised when a directory doesn't exist physically on the filesystem."""


class DirectoryInvalidError(Exception):
    """Raised when a directory path is invalid or inaccessible."""


class HtmxHttpRequest(HttpRequest):
    """HttpRequest class with HTMX details."""

    htmx: HtmxDetails


logger = logging.getLogger()


# ASGI: Async wrapper for render function
async def async_render(request, template_name, context=None, **kwargs):
    """
    Async wrapper for Django's render function.

    Args:
        request: HttpRequest object
        template_name: Template file name
        context: Context dictionary
        **kwargs: Additional arguments for render
    Returns: HttpResponse
    """
    return await sync_to_async(render)(request, template_name, context, **kwargs)


def get_sort_param(request: WSGIRequest) -> int:
    """
    Get and validate sort parameter from query string.

    Valid values are defined by SORT_MATRIX keys.

    :Args:
        request: Django request object

    :Returns:
        Sort parameter (validated against SORT_MATRIX), defaults to 0 if invalid
    """
    try:
        sort_value = int(request.GET.get("sort", str(settings.DEFAULT_SORT_ORDER)))
        # Use existing SORT_MATRIX keys - no need to duplicate valid values
        return sort_value if sort_value in SORT_MATRIX else settings.DEFAULT_SORT_ORDER
    except (ValueError, TypeError):
        return settings.DEFAULT_SORT_ORDER


def _create_base_context(request: WSGIRequest) -> dict:
    """
    Create base context dictionary shared by all view functions.

    Args:
        request: Django WSGIRequest object
    Returns: Base context dictionary
    """
    small_size = settings.IMAGE_SIZE["small"]
    small_width, small_height = small_size

    return {
        "debug": settings.DEBUG,
        "small": request.GET.get("size", small_size),
        "small_width": small_width,
        "small_height": small_height,
        "user": request.user,
        "sort": get_sort_param(request),
        "fromtimestamp": datetime.datetime.fromtimestamp,
        "current_page": int(request.GET.get("page", 1)),
        "missing": [],
        "items_to_display": [],
        "files_needing_thumbnails": [],
        "page_range": [],
        "has_previous": False,
        "has_next": False,
    }


# TTL cache for user show_duplicates preference — avoids a DB query on every page load.
# Keyed on user.pk, expires after USER_PREF_CACHE_TTL seconds.
# Explicitly cleared by toggle_show_duplicates() in user_preferences/views.py.
_user_pref_cache: TTLCache = TTLCache(
    maxsize=settings.USER_PREF_CACHE_SIZE,
    ttl=settings.USER_PREF_CACHE_TTL,
)


def _get_show_duplicates_preference(request: WSGIRequest) -> bool:
    """
    Get show_duplicates preference for the current user.

    Results are cached in a TTL cache keyed on user.pk to avoid a DB query
    per page load. The cache is explicitly invalidated by toggle_show_duplicates().

    This is a sync function — wrap with sync_to_async() when calling from async contexts.

    Args:
        request: Django WSGIRequest object

    Returns:
        bool: True if user wants to show duplicates, False otherwise
    """
    if not request.user.is_authenticated:
        return False

    user_pk = request.user.pk
    cached = _user_pref_cache.get(user_pk)
    if cached is not None:
        return cached

    try:
        from user_preferences.models import UserPreferences

        preferences = UserPreferences.objects.filter(user=request.user).first()
        result = preferences.show_duplicates if preferences else False
    except (DatabaseError, OperationalError, AttributeError):
        result = False

    _user_pref_cache[user_pk] = result
    return result


def create_search_regex_pattern(text: str) -> str:
    """
    Create a regex pattern for separator-agnostic search.

    Args:
        text: The search text to create regex pattern for

    Returns:
        Regex pattern string for case-insensitive matching, or empty string if invalid
    """
    if not text or not text.strip():
        return ""

    cleaned_text = text.strip()

    try:
        escaped = re.escape(cleaned_text)
    except (TypeError, ValueError):
        return ""

    # Replace escaped separators with flexible pattern
    pattern = (
        escaped.replace(r"\ ", r"[\s_-]+")  # spaces to flexible separator
        .replace(r"\_", r"[\s_-]+")  # underscores to flexible separator
        .replace(r"\-", r"[\s_-]+")
    )  # dashes to flexible separator

    return pattern if len(pattern) <= 500 else ""


def _safe_regex_search(model, field_name: str, regex_pattern: str, fallback_text: str, order_by: tuple, **filter_kwargs):
    """
    Perform regex search with automatic fallback to icontains on failure.

    ASYNC-SAFE: Pure ORM operations, no blocking I/O

    Args:
        model: Django model class to query
        field_name: Name of field to search (e.g., "fqpndirectory", "name")
        regex_pattern: Regex pattern to search with
        fallback_text: Text to use for icontains fallback if regex fails
        order_by: Tuple of field names for ordering
        **filter_kwargs: Additional filter arguments and queryset methods

    Returns:
        QuerySet with results
    """
    # Extract queryset methods from kwargs
    prefetch_fields = filter_kwargs.pop("prefetch_fields", [])
    annotate_kwargs = filter_kwargs.pop("annotate_kwargs", {})

    try:
        # Try regex search first
        filter_lookup = {f"{field_name}__iregex": regex_pattern}
        qs = model.objects.filter(**filter_lookup, **filter_kwargs)
    except (DatabaseError, OperationalError) as e:
        print(f"Regex search failed for {model.__name__}.{field_name}, using fallback: {e}")
        # Fallback to case-insensitive contains
        filter_lookup = {f"{field_name}__icontains": fallback_text.strip()}
        qs = model.objects.filter(**filter_lookup, **filter_kwargs)

    # Apply prefetch if provided
    if prefetch_fields:
        qs = qs.prefetch_related(*prefetch_fields)

    # Apply annotations if provided
    if annotate_kwargs:
        qs = qs.annotate(**annotate_kwargs)

    # Apply ordering
    return qs.order_by(*order_by)


def get_search_results(
    searchtext: str, search_regex_pattern: str, sort_order_value: int, prefetch_dirs: list[str], prefetch_files: list[str]
) -> tuple:
    """
    Get both directory and file search results with optimized queries.

    ASYNC-SAFE: Uses _safe_regex_search which is async-safe

    Args:
        searchtext: Original search text for fallback
        search_regex_pattern: Compiled regex pattern
        sort_order_value: Sort order index
        prefetch_dirs: List of related fields to prefetch for directories (required)
        prefetch_files: List of related fields to prefetch for files (required)

    Returns:
        Tuple of (dirs_queryset, files_queryset)
    """
    if prefetch_dirs is None:
        raise ValueError("prefetch_dirs parameter is required")
    if prefetch_files is None:
        raise ValueError("prefetch_files parameter is required")
    if not search_regex_pattern:
        return DirectoryIndex.objects.none(), FileIndex.objects.none()

    base_filters = {"delete_pending": False}
    order_by = SORT_MATRIX[sort_order_value]

    # Directory search with optimized prefetching
    dirs = _safe_regex_search(
        DirectoryIndex,
        "fqpndirectory",
        search_regex_pattern,
        searchtext,
        order_by,
        prefetch_fields=prefetch_dirs,
        annotate_kwargs={
            "file_count": Count(
                "FileIndex_entries",
                filter=Q(FileIndex_entries__delete_pending=False),
                distinct=True,
            ),
            "directory_count": Count(
                "parent_dir",
                filter=Q(parent_dir__delete_pending=False),
                distinct=True,
            ),
        },
        **base_filters,
    )

    # File search with optimized prefetching
    files = _safe_regex_search(
        FileIndex,
        "name",
        search_regex_pattern,
        searchtext,
        order_by,
        prefetch_fields=prefetch_files,
        **base_filters,
    )

    return dirs, files


# https://stackoverflow.com/questions/12984426/

# Sending File or zipfile - https://djangosnippets.org/snippets/365/

# def favicon(request:HttpRequest) -> HttpResponse:
#     return HttpResponse(
#         (
#             '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
#             + '<text y=".9em" font-size="90">🦊</text>'
#             + "</svg>"
#         ),
#         content_type="image/svg+xml",
#     )


def _get_materialized_search_results(
    searchtext: str,
    regex_pattern: str,
    sort_order: int,
    prefetch_dirs: tuple,
    prefetch_files: tuple,
    max_results: int,
) -> tuple[list, list]:
    """
    Get search results and materialize querysets in a single sync call.

    Consolidates get_search_results + list materialization to reduce
    async/sync boundary crossings from 3 to 1.

    Args:
        searchtext: Original search text for fallback
        regex_pattern: Compiled regex pattern
        sort_order: Sort order index
        prefetch_dirs: Prefetch fields for directory results
        prefetch_files: Prefetch fields for file results
        max_results: Maximum total results to return

    Returns:
        Tuple of (directory_results_list, file_results_list)
    """
    dirs, files = get_search_results(searchtext, regex_pattern, sort_order, prefetch_dirs, prefetch_files)
    return list(dirs[: max_results // 2]), list(files[: max_results // 2])


@vary_on_headers("HX-Request")
async def search_viewresults(request: WSGIRequest):
    """
    View the search results Gallery page using shared patterns (ASGI async version).

    Args:
        request: Django Request object

    Returns:
        response: Django response
    """
    print("NEW search GALLERY")
    start_time = time.perf_counter()

    # Get show_duplicates preference (async-safe)
    show_duplicates = await sync_to_async(_get_show_duplicates_preference)(request)

    # Use standardized template selection
    template_name = _determine_template(request, "search")

    # Get search parameters (support both POST and GET)
    searchtext = request.POST.get("searchtext") or request.GET.get("searchtext", default=None)
    current_page = int(request.POST.get("page") or request.GET.get("page", 1))

    # Build base context using shared function
    context = _create_base_context(request)
    context["show_duplicates"] = show_duplicates

    # Add search-specific context
    context.update(
        {
            "medium": request.GET.get("size", settings.IMAGE_SIZE["medium"]),
            "large": request.GET.get("size", settings.IMAGE_SIZE["large"]),
            "searchtext": searchtext,
            "originator": request.headers.get("referer"),
            "gallery_name": f"Searching for {searchtext}",
            "search": True,
            "prev_uri": "",
            "next_uri": "",
            "breadcrumbs": [{"name": "Search Results", "url": request.path}],
            "webpath": "/search/",
            "up_uri": "/albums/",
        }
    )

    # Perform search using shared functions (async wrapped)
    search_regex_pattern = create_search_regex_pattern(searchtext)
    print(f"Search text: '{searchtext}' -> Regex pattern: '{search_regex_pattern}'")

    max_search_results = settings.MAX_SEARCH_RESULTS
    directory_results, file_results = await sync_to_async(_get_materialized_search_results)(
        searchtext,
        search_regex_pattern,
        context["sort"],
        SEARCH_PR_FILETYPE,
        SEARCH_PR_FILETYPE_HOME,
        max_search_results,
    )
    combined_results = directory_results + file_results

    if len(combined_results) >= max_search_results:
        print(f"Search results limited to {max_search_results} items for performance")

    # Use optimized pagination (shared pattern with gallery view)
    items_per_page = 30
    total_items = len(combined_results)
    total_pages = max(1, (total_items + items_per_page - 1) // items_per_page)
    current_page = max(1, min(current_page, total_pages))

    start_idx = (current_page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_items = combined_results[start_idx:end_idx]

    # Update context with pagination data (consistent with gallery view)
    context.update(
        {
            "page_range": list(range(1, total_pages + 1)),
            "total_pages": total_pages,
            "total_items": total_items,
            "current_page": current_page,
            "has_previous": current_page > 1,
            "has_next": current_page < total_pages,
            "items_to_display": page_items,
        }
    )

    # Handle originator URL
    if "/search/" in str(context["originator"]) or context["originator"] is None:
        context["originator"] = request.GET.get("originator", "/albums")

    # Check for missing thumbnails (FileIndex only, using FK ID to avoid query)
    # Creating missing thumbnails during search would result in searching the entire database,
    # instead of being a focused creation in a particular directory.
    # Use an empty queryset to maintain consistent type (QuerySet) with gallery view.
    context["files_needing_thumbnails"] = FileIndex.objects.none()

    response = await async_render(request, template_name, context, using="Jinja2")

    # Prevent HTMX history caching AND browser caching for search results
    # This fixes the issue where subsequent searches show cached results from the first search
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    # Tell HTMX not to add this page to history cache
    response["HX-Replace-Url"] = "false"

    print("search View, processing time: ", time.perf_counter() - start_time)
    # ASGI: close_old_connections() commented out for ASGI compatibility
    # ASGI handles connection lifecycle automatically
    # close_old_connections()
    return response


def _determine_template(request: WSGIRequest, template_type: str = "gallery") -> str:
    """
    Determine which template to use based on HTMX request type.

    Args:
        request: Django WSGIRequest object
        template_type: Type of template ("gallery", "search", "item")
    Returns: Template name string
    """
    is_partial = request.htmx.boosted and request.htmx.current_url is not None and not request.GET.get("newwin", False)

    template_map = {
        "gallery": {
            "partial": "frontend/gallery/gallery_listing_partial.jinja",
            "complete": "frontend/gallery/gallery_listing_complete.jinja",
        },
        "search": {
            "partial": "frontend/search/search_listings_partial.jinja",
            "complete": "frontend/search/search_listings_complete.jinja",
        },
        "item": {
            "partial": "frontend/item/gallery_htmx_partial.jinja",
            "complete": "frontend/item/gallery_htmx_complete.jinja",
        },
    }

    template_set = template_map.get(template_type, template_map["gallery"])
    return template_set["partial"] if is_partial else template_set["complete"]


def _find_directory(paths: dict) -> DirectoryIndex:
    """
    Find directory in database, create if missing, and validate existence.

    Uses DirectoryIndex model methods to handle database operations efficiently.
    DirectoryIndex.add_directory() already validates physical path existence,
    so we only need to handle the happy path and raise exceptions on errors.

    :Args:
        paths: Dictionary containing path information (must have 'album_viewing' key)

    Returns:
        DirectoryIndex: The directory object on success

    Raises:
        DirectoryNotFoundError: If directory doesn't exist physically on filesystem
        DirectoryInvalidError: If path is invalid or other errors occur
    """
    try:
        # Normalize path once and compute SHA (DirectoryIndex methods will do this again,
        # but we need dirpath for logging and validation)
        dirpath = normalize_fqpn(paths["album_viewing"])
        dir_sha = get_dir_sha(dirpath)

        # Search for directory in database (uses optimized prefetches)
        # REMOVED: ("FileIndex_entries",) prefetch - Phase 5 Fix 4
        # Files loaded separately via files_in_dir() when needed - no need to prefetch all
        found, directory = DirectoryIndex.search_for_directory_by_sha(dir_sha, DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE_PARENT, ())

        if not found:
            # Create directory record - add_directory handles:
            # - Physical path validation (returns False, None if path doesn't exist)
            # - Parent directory creation (recursive)
            # - Database record creation
            created, directory = DirectoryIndex.add_directory(dirpath)

            if not created and not directory:
                # Physical directory doesn't exist on filesystem
                logger.info("Directory not found on filesystem: %s", dirpath)
                raise DirectoryNotFoundError(f"Gallery not found: {dirpath}")

            # Clear parent's cache if this is a new directory (web discovery case)
            # This ensures the parent directory listing shows the new subdirectory
            if created and directory.parent_directory:
                Cache_Storage.remove_from_cache_indexdirs(directory.parent_directory)

            # Reload with optimized prefetches for view rendering
            # add_directory uses update_or_create without prefetch_related
            # REMOVED: ("FileIndex_entries",) prefetch - Phase 5 Fix 4
            _, directory = DirectoryIndex.search_for_directory_by_sha(dir_sha, DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE_PARENT, ())

            # Sync newly created directory to populate file entries
            directory = update_database_from_disk(directory)

            if not directory:
                logger.info("Directory sync failed: %s", dirpath)
                raise DirectoryNotFoundError(f"Gallery sync failed: {dirpath}")

        # Validate physical directory still exists (race condition check)
        # This handles the case where directory was in DB but deleted from disk
        if not pathlib.Path(dirpath).exists():
            logger.info("Directory exists in DB but not on filesystem: %s", dirpath)
            # Invalidate cache and mark as deleted
            if directory.parent_directory:
                Cache_Storage.remove_from_cache_indexdirs(index_dir=directory.parent_directory)
            Cache_Storage.remove_from_cache_indexdirs(index_dir=directory)
            update_database_from_disk(directory)
            raise DirectoryNotFoundError(f"Gallery not found on filesystem: {dirpath}")

        logger.info("Viewing: %s", dirpath)
        return directory

    except DirectoryNotFoundError:
        # Re-raise our custom exceptions
        raise
    except Exception as e:
        logger.error("Error finding directory '%s': %s", paths["album_viewing"], e)
        raise DirectoryInvalidError(f"Invalid path specified: {paths['album_viewing']}") from e


def _check_and_enqueue_missing_thumbnails(directory: DirectoryIndex, sort_ordering: int, batch_limit: int) -> int:
    """
    Check for files needing thumbnails and enqueue generation if needed.

    Consolidates three sequential ORM operations into a single sync function
    to reduce async/sync boundary crossings.

    Args:
        directory: DirectoryIndex to check for missing thumbnails
        sort_ordering: Sort order for file query
        batch_limit: Maximum number of thumbnails to enqueue per batch

    Returns:
        Number of files enqueued for thumbnail generation
    """
    qs = _get_files_needing_thumbnails(directory, sort_ordering)
    no_thumbs = list(qs[:batch_limit])
    missing_count = len(no_thumbs)
    if missing_count > 0:
        print(f"{missing_count} entries need thumbnails, enqueuing to task runner")
        generate_missing_thumbnails.enqueue(
            files_needing_thumbnails=no_thumbs,
            directory_pk=directory.pk,
            batchsize=missing_count,
        )
    return missing_count


@vary_on_headers("HX-Request")
async def new_viewgallery(request: WSGIRequest):
    """
    View the requested Gallery page using optimized helper functions (ASGI async version).

    Args:
        request: Django Request object
    Returns: Django response
    """
    print("NEW VIEW GALLERY for ", request.path)
    start_time = time.perf_counter()

    # Get show_duplicates preference (async-safe)
    show_duplicates = await sync_to_async(_get_show_duplicates_preference)(request)

    # Use standardized template selection
    template_name = _determine_template(request, "gallery")

    # Process and normalize request path
    try:
        request.path = urllib.parse.unquote(request.path).lower().replace(os.sep, r"/")
    except (ValueError, UnicodeDecodeError) as e:
        logger.warning("Failed to decode URL path '%s': %s", request.path, e)
        request.path = request.path.lower().replace(os.sep, r"/")

    paths = {
        "webpath": request.path,
        "album_viewing": normalize_fqpn(settings.ALBUMS_PATH + request.path),
        "thumbpath": ensures_endswith(request.path.replace(r"/albums/", r"/thumbnails/"), "/"),
    }

    # Get directory and handle errors via exceptions
    try:
        directory = await sync_to_async(_find_directory)(paths)
    except DirectoryNotFoundError as e:
        return HttpResponseNotFound("<h1>gallery not found</h1>")
    except DirectoryInvalidError as e:
        return HttpResponseBadRequest("<h1>Invalid path specified</h1>")

    # Ensure directory data is up to date
    await sync_to_async(update_database_from_disk)(directory)

    # Build initial context - start with shared base context
    context = _create_base_context(request)

    # Add gallery-specific context
    context.update(
        {
            "webpath": ensures_endswith(paths["webpath"], os.sep),
            "breadcrumbs": return_breadcrumbs(paths["webpath"])[:-1],
            "thumbpath": paths["thumbpath"],
            "gallery_name": pathlib.Path(paths["webpath"]).name,
            "up_uri": convert_to_webpath(str(pathlib.Path(paths["webpath"]).parent)),
            "search": False,
            "prev_uri": None,
            "next_uri": None,
            "pagelist": [],
        }
    )

    # Get layout data and update context (async wrapped)
    layout = await async_layout_manager(
        page_number=context["current_page"],
        directory=directory,
        sort_ordering=context["sort"],
        show_duplicates=show_duplicates,
    )

    # Update context with layout data efficiently
    context.update(
        {
            "total_pages": layout["total_pages"],
            "page_range": list(range(1, layout["total_pages"] + 1)),
            "page_locale": layout["page_locale"],
        }
    )

    # Set navigation URIs (sync function wrapped for async context)
    context["prev_uri"], context["next_uri"] = await sync_to_async(directory.get_prev_next_siblings)(sort_order=context["sort"])

    # Only fetch directories if there are any on this page (async wrapped)
    if layout["page_items"]["directory_shas"]:
        dirs_to_display = await sync_to_async(list)(
            directory.dirs_in_dir(sort=context["sort"], select_related=DIRECTORYINDEX_SR_FILETYPE_THUMB, prefetch_related=()).filter(
                dir_fqpn_sha256__in=layout["page_items"]["directory_shas"]
            )
            # REMOVED: .select_related("thumbnail__new_ftnail") - Phase 5 Fix 1
            # Thumbnails load on-demand via thumbnail2_dir() - no need for 750KB binary blobs
            .annotate(
                file_count=Count(
                    "FileIndex_entries",
                    filter=Q(FileIndex_entries__delete_pending=False),
                    distinct=True,
                ),
                directory_count=Count(
                    "parent_dir",
                    filter=Q(parent_dir__delete_pending=False),
                    distinct=True,
                ),
            )
        )
    else:
        dirs_to_display = []

    # Only fetch files if there are any on this page (async wrapped)
    if layout["page_items"]["file_shas"]:
        # Fetch and separate files and links in one pass
        # Note: select_related already handled by files_in_dir() - no need to duplicate
        all_items = await sync_to_async(list)(
            directory.files_in_dir(sort=context["sort"], select_related=FILEINDEX_SR_FILETYPE_HOME_VIRTUAL).filter(
                unique_sha256__in=layout["page_items"]["file_shas"]
            )
        )
        files_list = [f for f in all_items if not f.filetype.is_link]
        links_list = [f for f in all_items if f.filetype.is_link]
    else:
        files_list = []
        links_list = []

    context["items_to_display"] = list(dirs_to_display) + links_list + files_list
    context["show_duplicates"] = show_duplicates
    # print("elapsed view gallery (pre-thumb) time - ", time.time() - start_time)

    # Check if thumbnails are needed (computed separately from cached layout
    # to avoid invalidating layout cache when thumbnails are generated)
    missing_count = await sync_to_async(_check_and_enqueue_missing_thumbnails)(directory, context["sort"], settings.THUMBNAIL_BATCH_LIMIT)

    response = await async_render(
        request,
        f"{template_name}",
        context,
        using="Jinja2",
    )

    # Prevent browser caching when user preferences might change
    if request.user.is_authenticated:
        response["Cache-Control"] = "private, no-cache, must-revalidate"

    if settings.CACHE_MONITORING:
        await sync_to_async(snapshot_cache_statistics)()

    print("Gallery View, processing time: ", time.perf_counter() - start_time)

    return response


@vary_on_headers("HX-Request")
async def htmx_view_item(request: HtmxHttpRequest, sha256: str):
    """
    View individual item with HTMX support using standardized patterns (ASGI async version).

    Args:
        request: Django HtmxHttpRequest object
        sha256: SHA256 hash of the item to view
    Returns: Django response
    """
    # Get show_duplicates preference (async-safe)
    show_duplicates = await sync_to_async(_get_show_duplicates_preference)(request)

    # Use standardized template selection
    template_name = _determine_template(request, "item")

    # Use managers.py for context building (async wrapped)
    # Pass show_duplicates to ensure navigation uses same distinct mode as gallery
    context = await async_build_context_info(request, sha256, show_duplicates)
    if isinstance(context, HttpResponseBadRequest):
        return context

    # Ensure user is in context (standardized pattern)
    context["user"] = request.user
    context["show_duplicates"] = show_duplicates

    # Proactively warm thumbnails for the directory this item belongs to.
    # Same pattern as new_viewgallery() but with a smaller batch limit.
    # Uses cached DirectoryIndex from build_context_info (avoids redundant DB fetch).
    directory = context["home_directory"]
    await sync_to_async(_check_and_enqueue_missing_thumbnails)(directory, context["sort"], settings.ITEM_VIEW_THUMBNAIL_BATCH_LIMIT)

    response = await async_render(request, template_name, context, using="Jinja2")

    # Prevent browser caching when user preferences might change
    if request.user.is_authenticated:
        response["Cache-Control"] = "private, no-cache, must-revalidate"

    return response


async def download_file(request: WSGIRequest):  # , filename=None):
    """
    Replaces new_download (ASGI async version).

    This now takes http://<servername>/downloads/<filename>?usha=<unique_sha>

    This fakes the browser into displaying the filename as the title of the
    download.

    Args:
        request : Django request object
        # filename (str): This is unused, and only captured in django URLS to allow
        #     the web browser to "see" a default filename.  That's why the uuid is
        #     an argument passed in (?uuid=xxxxxx), so that the web browser doesn't
        #     see the uuid, and use that as the filename (which is an issue that was
        #     found during v2 development).

    Raises:
        Http404: If file not found or no identifier provided
        asyncio.CancelledError: Re-raised if client disconnects (normal operation)
    """
    sha_value = request.GET.get("usha", None) or request.GET.get("USHA", None)
    if sha_value in ["", None]:
        raise Http404("No Identifier provided for download.")
    sha_value = sha_value.strip().lower()

    try:
        # Wrap database query - use optimized download method
        file_to_send = await sync_to_async(FileIndex.get_by_sha256_for_download)(sha_value, unique=True, select_related=FILEINDEX_SR_FILETYPE_HOME)
        if file_to_send:
            # Use async sendfile method to avoid sync iterator warning
            response = await file_to_send.async_inline_sendfile(request, ranged=file_to_send.filetype.is_movie)
            return response
        raise Http404("No File to Send")
    except asyncio.CancelledError:
        # Client disconnected (timeout, network issue, etc.) - this is expected
        # Re-raise to let Django's async machinery handle cleanup
        # Don't log as error since it's normal for clients to disconnect
        raise
