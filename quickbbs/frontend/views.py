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
import warnings

from asgiref.sync import async_to_sync, sync_to_async
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
from PIL import Image

from cache_watcher.models import Cache_Storage
from frontend.managers import (
    clear_layout_cache_for_directories,
    async_layout_manager,
    async_build_context_info,
)
from frontend.utilities import (
    SORT_MATRIX,
    convert_to_webpath,
    ensures_endswith,
    return_breadcrumbs,
    sync_database_disk,
)
from quickbbs.common import get_dir_sha, normalize_fqpn
from quickbbs.directoryindex import (
    DIRECTORYINDEX_SR_FILETYPE_THUMB,
    DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE,
    DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE_PARENT,
)
from quickbbs.fileindex import FILEINDEX_SR_FILETYPE_HOME_VIRTUAL, FILEINDEX_SR_FILETYPE_HOME
from quickbbs.models import FileIndex, DirectoryIndex
from thumbnails.models import ThumbnailFiles

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


class HtmxHttpRequest(HttpRequest):
    """HttpRequest class with HTMX details."""

    htmx: HtmxDetails


logger = logging.getLogger()

warnings.simplefilter("ignore", Image.DecompressionBombWarning)


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


def _create_base_context(request: WSGIRequest) -> dict:
    """
    Create base context dictionary shared by all view functions.

    Args:
        request: Django WSGIRequest object
    Returns: Base context dictionary
    """
    from frontend.web import g_option

    small_size = settings.IMAGE_SIZE["small"]
    small_width, small_height = small_size

    return {
        "debug": settings.DEBUG,
        "small": g_option(request, "size", small_size),
        "small_width": small_width,
        "small_height": small_height,
        "user": request.user,
        "sort": int(request.GET.get("sort", default=0)),
        "fromtimestamp": datetime.datetime.fromtimestamp,
        "current_page": int(request.GET.get("page", 1)),
        "missing": [],
        "items_to_display": [],
        "no_thumbnails": [],
        "page_cnt": [],
        "has_previous": False,
        "has_next": False,
    }


async def _get_show_duplicates_preference(request: WSGIRequest) -> bool:
    """
    Get show_duplicates preference for the current user (async-safe).

    This function safely accesses the user's preferences from the database
    in an async context, preventing async-safety warnings and ensuring
    fresh data is retrieved.

    Args:
        request: Django WSGIRequest object

    Returns:
        bool: True if user wants to show duplicates, False otherwise
    """

    def get_preference():
        if not request.user.is_authenticated:
            return False
        try:
            return request.user.preferences.show_duplicates
        except Exception:
            return False

    return await sync_to_async(get_preference)()


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
            "file_count_cached": Count(
                "FileIndex_entries",
                filter=Q(FileIndex_entries__delete_pending=False),
            )
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


def thumbnail2_dir(request: WSGIRequest, dir_sha256: str | None = None):  # pylint: disable=unused-argument
    """
    Serve directory thumbnail using prioritized cover image selection.

    Uses DirectoryIndex.get_cover_image() to select thumbnails based on priority filenames
    (e.g., "cover", "title") before falling back to the first available file.

    Args:
        request: Django Request object
        dir_sha256: the sha256 of the directory

    Returns:
        The image of the thumbnail to send

    Raises:
        HttpResponseBadRequest: If the directory cannot be found
    """
    # Use optimized model method with prefetched relationships
    success, directory = DirectoryIndex.search_for_directory_by_sha(dir_sha256, DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE_PARENT, ())
    if not success:
        print(f"Directory not found: {dir_sha256}")
        return Http404

    # If directory already has a thumbnail set AND cache is valid, try to return it
    try:
        if directory.thumbnail and directory.thumbnail.new_ftnail and directory.is_cached:
            try:
                return directory.thumbnail.new_ftnail.send_thumbnail(fext_override=".jpg", size="small", index_data_item=directory.thumbnail)
            except Exception as e:
                # If thumbnail serving fails, fall through to cover image logic
                print(f"Directory thumbnail serving failed for {directory.fqpndirectory}: {e}")
                # Continue to cover image selection below
    except FileIndex.DoesNotExist:
        # Thumbnail FK points to deleted/non-existent record - clear it and regenerate
        print(f"Thumbnail reference broken for {directory.fqpndirectory} - regenerating")
        directory.invalidate_thumb()

    # Cache is invalidated or no thumbnail set - regenerate using get_cover_image
    # Clear any existing thumbnail reference
    if not directory.is_cached:
        directory.invalidate_thumb()

    # Use get_cover_image to find the best cover image for this directory
    cover_image = directory.get_cover_image()

    # If no cover image found, try syncing from disk and retry
    if not cover_image:
        async_to_sync(sync_database_disk)(directory)
        cover_image = directory.get_cover_image()

    # If still no cover image found, return default directory icon
    if not cover_image:
        return directory.filetype.send_thumbnail()

    # Set directory thumbnail to the selected cover image
    # Clear layout cache to ensure users see updated thumbnail
    directory.thumbnail = cover_image
    directory.is_generic_icon = False
    directory.save()

    # Clear cache for this directory
    clear_layout_cache_for_directories([directory])

    # Ensure thumbnail record exists
    if not directory.thumbnail.new_ftnail:
        from thumbnails.models import THUMBNAILFILES_PR_FILEINDEX_FILETYPE

        thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
            directory.thumbnail.file_sha256,
            suppress_save=False,
            prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE,
            select_related_fileindex=("filetype",),
        )
        directory.thumbnail.new_ftnail = thumbnail
        directory.save()

    # Try to return the thumbnail, fall back to generic icon on error
    try:
        return directory.thumbnail.new_ftnail.send_thumbnail(fext_override=".jpg", size="small", index_data_item=directory.thumbnail)
    except Exception as e:
        # If thumbnail generation/serving fails, mark directory as generic and return filetype icon
        # Clear layout cache to ensure users see updated generic icon state
        print(f"Directory thumbnail generation failed for {directory.fqpndirectory}: {e}")
        directory.is_generic_icon = True
        directory.save(update_fields=["is_generic_icon"])

        # Clear cache for this directory
        clear_layout_cache_for_directories([directory])

        return directory.filetype.send_thumbnail()


def thumbnail2_file(request: WSGIRequest, sha256: str):
    """
    Create and serve a thumbnail for a specific file.

    Args:
        request: Django Request object
        sha256: The sha256 of the file - FileIndex object

    Returns:
        The sent thumbnail
    """
    from thumbnails.models import THUMBNAILFILES_PR_FILEINDEX_FILETYPE

    thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
        sha256, suppress_save=False, prefetch_related_thumbnail=THUMBNAILFILES_PR_FILEINDEX_FILETYPE, select_related_fileindex=("filetype",)
    )

    # Get associated FileIndex - try reverse FK first, fall back to model method
    try:
        index_data_item = thumbnail.FileIndex.first()
        if not index_data_item:
            # Fallback: prefetch cache might be stale, use cached model method
            index_data_item = FileIndex.get_by_sha256(sha256, unique=False, select_related=FILEINDEX_SR_FILETYPE_HOME_VIRTUAL)
            if not index_data_item:
                return HttpResponseBadRequest(content="No associated file data found.")
    except (AttributeError, IndexError):
        return HttpResponseBadRequest(content="Error accessing file data.")

    # Return generic icon if filetype is generic OR if file is marked as generic icon
    if index_data_item.filetype.generic or index_data_item.is_generic_icon:
        return index_data_item.filetype.send_thumbnail()

    # Handle link files: if this is a link type with a virtual_directory,
    # delegate to the virtual directory's thumbnail
    if index_data_item.filetype.is_link and index_data_item.virtual_directory:
        return thumbnail2_dir(request, index_data_item.virtual_directory.dir_fqpn_sha256)

    # Try to return custom thumbnail, fall back to generic icon on error
    thumbsize = request.GET.get("size", "small").lower()
    try:
        return thumbnail.send_thumbnail(
            filename_override=index_data_item.name,
            fext_override=".jpg",
            size=thumbsize,
            index_data_item=index_data_item,
        )
    except Exception as e:
        # If thumbnail generation/serving fails, mark ALL files with this SHA256 as generic
        # Use FileIndex classmethod to ensure layout cache is cleared
        print(f"Thumbnail generation failed for {index_data_item.name}: {e}")
        FileIndex.set_generic_icon_for_sha(sha256, is_generic=True, clear_cache=True)
        return index_data_item.filetype.send_thumbnail()


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
    show_duplicates = await _get_show_duplicates_preference(request)

    # Use standardized template selection
    template_name = _determine_template(request, "search")

    # Get search parameters
    searchtext = request.GET.get("searchtext", default=None)
    current_page = int(request.GET.get("page", 1))

    # Build base context using shared function
    context = _create_base_context(request)
    context["show_duplicates"] = show_duplicates

    # Add search-specific context
    from frontend.web import g_option

    context.update(
        {
            "medium": g_option(request, "size", settings.IMAGE_SIZE["medium"]),
            "large": g_option(request, "size", settings.IMAGE_SIZE["large"]),
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

    dirs, files = await sync_to_async(get_search_results)(
        searchtext, search_regex_pattern, context["sort"], prefetch_dirs=SEARCH_PR_FILETYPE, prefetch_files=SEARCH_PR_FILETYPE_HOME
    )

    # Combine and limit results (async wrapped list conversion)
    max_search_results = 10000
    dir_list, file_list = await asyncio.gather(
        sync_to_async(list)(dirs[: max_search_results // 2]), sync_to_async(list)(files[: max_search_results // 2])
    )
    combined_results = dir_list + file_list

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
            "page_cnt": list(range(1, total_pages + 1)),
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

    # Check for missing thumbnails
    files_needing_thumbnails = [
        item.file_sha256
        for item in page_items
        if hasattr(item, "file_sha256") and hasattr(item, "new_ftnail") and item.new_ftnail is None and item.filetype.is_image
    ]

    if files_needing_thumbnails:
        print(f"{len(files_needing_thumbnails)} search results need thumbnails")
        context["no_thumbnails"] = files_needing_thumbnails

    response = await async_render(request, template_name, context, using="Jinja2")
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


def _find_directory(paths: dict):
    """
    Find directory in database, create if missing, and validate existence.

    Uses DirectoryIndex model methods to handle database operations efficiently.
    DirectoryIndex.add_directory() already validates physical path existence,
    so we only need to handle the happy path and error responses.

    :Args:
        paths: Dictionary containing path information (must have 'album_viewing' key)

    Returns:
        Tuple of (True, directory) on success
        HttpResponseNotFound if directory doesn't exist physically
        HttpResponseBadRequest on invalid path or other errors
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
                return HttpResponseNotFound("<h1>gallery not found</h1>")

            # Reload with optimized prefetches for view rendering
            # add_directory uses update_or_create without prefetch_related
            # REMOVED: ("FileIndex_entries",) prefetch - Phase 5 Fix 4
            _, directory = DirectoryIndex.search_for_directory_by_sha(dir_sha, DIRECTORYINDEX_SR_FILETYPE_THUMB_CACHE_PARENT, ())

            # Sync newly created directory to populate file entries
            directory = async_to_sync(sync_database_disk)(directory)

            if not directory:
                logger.info("Directory sync failed: %s", dirpath)
                return HttpResponseNotFound("<h1>gallery not found</h1>")

        # Validate physical directory still exists (race condition check)
        # This handles the case where directory was in DB but deleted from disk
        if not pathlib.Path(dirpath).exists():
            logger.info("Directory exists in DB but not on filesystem: %s", dirpath)
            # Invalidate cache and mark as deleted
            if directory.parent_directory:
                Cache_Storage.remove_from_cache_indexdirs(index_dir=directory.parent_directory)
            Cache_Storage.remove_from_cache_indexdirs(index_dir=directory)
            async_to_sync(sync_database_disk)(directory)
            return HttpResponseNotFound("<h1>gallery not found</h1>")

        logger.info("Viewing: %s", dirpath)
        return True, directory

    except Exception as e:
        logger.error("Error finding directory '%s': %s", paths["album_viewing"], e)
        return HttpResponseBadRequest("<h1>Invalid path specified</h1>")


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
    show_duplicates = await _get_show_duplicates_preference(request)

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

    # Get directory and handle early returns
    result = await sync_to_async(_find_directory)(paths)
    if isinstance(result, (HttpResponseNotFound, HttpResponseBadRequest)):
        return result
    _, directory = result

    # Ensure directory data is up to date
    await sync_database_disk(directory)

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
            "page_cnt": list(range(1, layout["total_pages"] + 1)),
            "page_locale": layout["page_locale"],
        }
    )

    # Set navigation URIs (async function)
    context["prev_uri"], context["next_uri"] = await directory.get_prev_next_siblings(sort_order=context["sort"])

    # Only fetch directories if there are any on this page (async wrapped)
    if layout["data"]["directories"]:
        dirs_to_display = await sync_to_async(list)(
            directory.dirs_in_dir(sort=context["sort"], select_related=DIRECTORYINDEX_SR_FILETYPE_THUMB, prefetch_related=()).filter(
                dir_fqpn_sha256__in=layout["data"]["directories"]
            )
            # REMOVED: .select_related("thumbnail__new_ftnail") - Phase 5 Fix 1
            # Thumbnails load on-demand via thumbnail2_dir() - no need for 750KB binary blobs
            .annotate(
                file_count_cached=Count(
                    "FileIndex_entries",
                    filter=Q(FileIndex_entries__delete_pending=False),
                )
            )
        )
    else:
        dirs_to_display = []

    # Only fetch files if there are any on this page (async wrapped)
    if layout["data"]["files"]:
        # Fetch and separate files and links in one pass
        # Note: select_related already handled by files_in_dir() - no need to duplicate
        all_items = await sync_to_async(list)(
            directory.files_in_dir(sort=context["sort"], select_related=FILEINDEX_SR_FILETYPE_HOME_VIRTUAL).filter(
                unique_sha256__in=layout["data"]["files"]
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

    # Check if thumbnails are needed (async-safe existence check)
    has_missing_thumbnails = await sync_to_async(layout["no_thumbnails"].exists)()
    if has_missing_thumbnails:
        no_thumb_start = time.time()
        # Use .count() for efficient SQL COUNT instead of materializing all records
        missing_count = await sync_to_async(layout["no_thumbnails"].count)()
        print(f"{missing_count} entries need thumbnails")
        # print(layout["no_thumbnails"][0:10])  # Show first 10 entries needing thumbs

        if missing_count > 0:  # Process first 100 entries
            # Materialize sliced queryset to get list of SHA256 hashes
            no_thumbs = await sync_to_async(list)(layout["no_thumbnails"][:100])

            # Use ThumbnailFiles batch processing method
            results = await ThumbnailFiles.batch_create_async(no_thumbs, batchsize=100, max_workers=6)

            if any(results.values()):
                # Clear ALL layout cache entries for this directory (all pages, all sort orders)
                # Thumbnails were created, so cached counts are now stale
                cleared_count = clear_layout_cache_for_directories([directory])
                if cleared_count > 0:
                    print(f"Cleared {cleared_count} layout cache entries for directory " "after thumbnail processing")
        print("elapsed thumbnail time - ", time.time() - no_thumb_start)

    response = await async_render(
        request,
        f"{template_name}",
        context,
        using="Jinja2",
    )

    # Prevent browser caching when user preferences might change
    if request.user.is_authenticated:
        response["Cache-Control"] = "private, no-cache, must-revalidate"

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
    show_duplicates = await _get_show_duplicates_preference(request)

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

    return await async_render(request, template_name, context, using="Jinja2")


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
