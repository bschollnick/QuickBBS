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

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest

# from django.core.paginator import EmptyPage, PageNotAnInteger  # Unused after optimization
from django.db import close_old_connections, connections, transaction
from django.db.models import Count, Q
from django.db.utils import IntegrityError, DatabaseError, OperationalError
from django.http import (
    Http404,
    HttpRequest,
    HttpResponseBadRequest,
    HttpResponseNotFound,
)
from django.shortcuts import render
from django.views.decorators.vary import vary_on_headers
from django_htmx.middleware import HtmxDetails
from PIL import Image, ImageFile

from cache_watcher.models import Cache_Storage
from cachetools.keys import hashkey
from frontend.managers import build_context_info, layout_manager, layout_manager_cache
from frontend.utilities import (
    SORT_MATRIX,
    ensures_endswith,
    read_from_disk,
    return_breadcrumbs,
    sort_order,
    sync_database_disk,
)
from frontend.web import detect_mobile
from quickbbs.models import IndexData, IndexDirs
from thumbnails.models import ThumbnailFiles


class HtmxHttpRequest(HttpRequest):
    """HttpRequest class with HTMX details."""

    htmx: HtmxDetails


logger = logging.getLogger()

warnings.simplefilter("ignore", Image.DecompressionBombWarning)
ImageFile.LOAD_TRUNCATED_IMAGES = True


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
    from frontend.web import detect_mobile, g_option

    return {
        "debug": settings.DEBUG,
        "small": g_option(request, "size", settings.IMAGE_SIZE["small"]),
        "user": request.user,
        "mobile": detect_mobile(request),
        "sort": sort_order(request),
        "fromtimestamp": datetime.datetime.fromtimestamp,
        "current_page": int(request.GET.get("page", 1)),
        "missing": [],
        "items_to_display": [],
        "no_thumbnails": [],
        "page_cnt": [],
        "has_previous": False,
        "has_next": False,
    }


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


def get_search_results(
    searchtext: str, search_regex_pattern: str, sort_order_value: int
) -> tuple:
    """
    Get both directory and file search results with optimized queries.

    Returns:
        Tuple of (dirs_queryset, files_queryset)
    """
    if not search_regex_pattern:
        return IndexDirs.objects.none(), IndexData.objects.none()

    base_filters = {"delete_pending": False}
    order_by = SORT_MATRIX[sort_order_value]

    # Directory search with optimized prefetching
    try:
        dirs = (
            IndexDirs.objects.filter(
                fqpndirectory__iregex=search_regex_pattern, **base_filters
            )
            .select_related("filetype")
            .prefetch_related("IndexData_entries__filetype")
            .annotate(
                file_count_cached=Count(
                    "IndexData_entries",
                    filter=Q(IndexData_entries__delete_pending=False),
                )
            )
            .order_by(*order_by)
        )
    except (DatabaseError, OperationalError) as e:
        print(f"Regex search failed for directories, using fallback: {e}")
        dirs = (
            IndexDirs.objects.filter(
                fqpndirectory__icontains=searchtext.strip(), **base_filters
            )
            .select_related("filetype")
            .prefetch_related("IndexData_entries__filetype")
            .annotate(
                file_count_cached=Count(
                    "IndexData_entries",
                    filter=Q(IndexData_entries__delete_pending=False),
                )
            )
            .order_by(*order_by)
        )

    # File search with optimized prefetching
    try:
        files = (
            IndexData.objects.filter(name__iregex=search_regex_pattern, **base_filters)
            .select_related("filetype", "home_directory", "new_ftnail")
            .order_by(*order_by)
        )
    except (DatabaseError, OperationalError) as e:
        print(f"Regex search failed for files, using fallback: {e}")
        files = (
            IndexData.objects.filter(name__icontains=searchtext.strip(), **base_filters)
            .select_related("filetype", "home_directory", "new_ftnail")
            .order_by(*order_by)
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


async def return_prev_next2(directory, sorder: int) -> tuple[str | None, str | None]:
    """
    The return_prev_next function takes a fully qualified pathname,
    and the current path as parameters. It returns the previous and next paths in a tuple.

    ASGI async version - all database operations wrapped.

    Args:
        fqpn: Get the path of the parent directory
        currentpath: Determine the current offset in the list of files
        sorder: Determine whether the index is sorted by name or size

    Returns:
        A tuple of two strings

    Note:
        ORM only derived from https://stackoverflow.com/questions/1042596/
        get-the-index-of-an-element-in-a-queryset
        Specifically Richard's answer.
    """
    nextdir = ""
    prevdir = ""

    # Wrap model method that accesses database
    parent_dir = await sync_to_async(directory.return_parent_directory)()
    if not parent_dir:
        return (None, None)

    # Wrap queryset operations
    directories = await sync_to_async(parent_dir.dirs_in_dir)(sort=sorder)
    parent_dir_data = await sync_to_async(list)(directories.values("fqpndirectory"))

    for count, entry in enumerate(parent_dir_data):
        if entry["fqpndirectory"] == directory.fqpndirectory:
            if count >= 1:
                prevdir = str(pathlib.Path(parent_dir_data[count - 1]["fqpndirectory"]))
                prevdir = prevdir.replace(settings.ALBUMS_PATH, "")

            try:
                nextdir = str(pathlib.Path(parent_dir_data[count + 1]["fqpndirectory"]))
                nextdir = nextdir.replace(settings.ALBUMS_PATH, "")
            except IndexError:
                pass
            break
    return (prevdir, nextdir)


def thumbnail2_dir(
    request: WSGIRequest, dir_sha256: str | None = None
):  # pylint: disable=unused-argument
    """
    Serve directory thumbnail by finding the first image in the directory.

    Args:
        request: Django Request object
        dir_sha256: the sha256 of the directory

    Returns:
        The image of the thumbnail to send

    Raises:
        HttpResponseBadRequest: If the directory cannot be found
    """

    def get_image_files(directory):
        """
        Get image files in the directory for thumbnail generation.

        :param directory: IndexDirs object representing the directory
        :return: QuerySet of image files in the directory
        """
        files_in_directory = directory.files_in_dir(
            additional_filters={"filetype__is_image": True}
        )
        if not files_in_directory.exists():
            sync_database_disk(directory.fqpndirectory)
            files_in_directory = directory.files_in_dir(
                additional_filters={"filetype__is_image": True}
            )
        return files_in_directory

    try:
        directory = IndexDirs.objects.get(dir_fqpn_sha256=dir_sha256)
    except IndexDirs.DoesNotExist:
        # does not exist
        print(dir_sha256, "Directory not found - No records returned.")
        return Http404

    if directory.thumbnail and directory.thumbnail.new_ftnail:
        #
        return directory.thumbnail.new_ftnail.send_thumbnail(
            fext_override=".jpg", size="small", index_data_item=directory.thumbnail
        )  # Send existing thumbnail

    files_in_directory = get_image_files(directory)

    # If no image files found, return default directory icon
    if not files_in_directory.exists():
        return directory.filetype.send_thumbnail()

    # Set directory thumbnail to first image file
    directory.thumbnail = files_in_directory.first()
    directory.is_generic_icon = False
    directory.save()

    # Ensure thumbnail record exists
    if not directory.thumbnail.new_ftnail:
        try:
            thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
                directory.thumbnail.file_sha256
            )
            directory.thumbnail.new_ftnail = thumbnail
            directory.save()
        except ThumbnailFiles.DoesNotExist:
            return HttpResponseBadRequest(content="Thumbnail not found.")

    # Return the thumbnail
    return directory.thumbnail.new_ftnail.send_thumbnail(
        fext_override=".jpg", size="small", index_data_item=directory.thumbnail
    )


def thumbnail2_file(request: WSGIRequest, sha256: str):
    """
    Create and serve a thumbnail for a specific file.

    Args:
        request: Django Request object
        sha256: The sha256 of the file - IndexData object

    Returns:
        The sent thumbnail
    """
    try:
        thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(sha256)
    except ThumbnailFiles.DoesNotExist:
        print(f"{sha256} - File not found")
        return HttpResponseBadRequest(content="Thumbnail not found.")

    # Get associated IndexData
    try:
        index_data_item = thumbnail.IndexData.first()
        if not index_data_item:
            return HttpResponseBadRequest(content="No associated file data found.")
    except (AttributeError, IndexError):
        return HttpResponseBadRequest(content="Error accessing file data.")

    # Return generic icon if filetype is generic
    if index_data_item.filetype.generic:
        return index_data_item.filetype.send_thumbnail()

    # Return custom thumbnail
    thumbsize = request.GET.get("size", "small").lower()
    return thumbnail.send_thumbnail(
        filename_override=index_data_item.name,
        fext_override=".jpg",
        size=thumbsize,
        index_data_item=index_data_item,
    )


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

    # Use standardized template selection
    template_name = _determine_template(request, "search")

    # Get search parameters
    searchtext = request.GET.get("searchtext", default=None)
    current_page = int(request.GET.get("page", 1))

    # Build base context using shared function
    context = _create_base_context(request)

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

    dirs, files = await sync_to_async(get_search_results)(searchtext, search_regex_pattern, context["sort"])

    # Combine and limit results (async wrapped list conversion)
    max_search_results = 10000
    dir_list, file_list = await asyncio.gather(
        sync_to_async(list)(dirs[: max_search_results // 2]),
        sync_to_async(list)(files[: max_search_results // 2])
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

    # Update context with pagination data
    context.update(
        {
            "page_cnt": list(range(1, total_pages + 1)),
            "total_pages": total_pages,
            "current_page": current_page,
            "has_previous": current_page > 1,
            "has_next": current_page < total_pages,
            "items_to_display": page_items,
            "pagelist": {"object_list": page_items},
        }
    )

    # Handle originator URL
    if "/search/" in str(context["originator"]) or context["originator"] is None:
        context["originator"] = request.GET.get("originator", "/albums")

    # Check for missing thumbnails
    files_needing_thumbnails = [
        item.file_sha256
        for item in page_items
        if hasattr(item, "file_sha256")
        and hasattr(item, "new_ftnail")
        and item.new_ftnail is None
        and item.filetype.is_image
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
    is_partial = (
        request.htmx.boosted
        and request.htmx.current_url is not None
        and not request.GET.get("newwin", False)
    )

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


def _process_request_path(request: WSGIRequest) -> dict:
    """
    Process and normalize the request path for gallery viewing.

    Args:
        request: Django WSGIRequest object
    Returns: Dictionary containing processed paths
    """
    # Properly decode URL before processing to handle special characters like #
    try:
        decoded_path = urllib.parse.unquote(request.path)
        request.path = decoded_path.lower().replace(os.sep, r"/")
    except (ValueError, UnicodeDecodeError) as e:
        logger.warning("Failed to decode URL path '%s': %s", request.path, e)
        # Fallback to original behavior for malformed URLs
        request.path = request.path.lower().replace(os.sep, r"/")

    return {
        "webpath": request.path,
        "album_viewing": settings.ALBUMS_PATH + request.path,
        "thumbpath": ensures_endswith(
            request.path.replace(r"/albums/", r"/thumbnails/"), "/"
        ),
    }


def _find_directory(paths: dict):
    """
    Find and validate directory existence.

    Args:
        paths: Dictionary containing path information
    Returns: Tuple of (found, directory) or raises Http404/HttpResponseBadRequest
    """
    try:
        found, directory = IndexDirs.search_for_directory(paths["album_viewing"])
        if not found:
            sync_database_disk(paths["album_viewing"])
            found, directory = IndexDirs.search_for_directory(paths["album_viewing"])

            if not found:
                logger.info("Directory not found: %s", paths["album_viewing"])
                return HttpResponseNotFound("<h1>gallery not found</h1>")
    except Exception as e:
        logger.error(
            "Error searching for directory '%s': %s", paths["album_viewing"], e
        )
        return HttpResponseBadRequest("<h1>Invalid path specified</h1>")

    logger.info("Viewing: %s", paths["album_viewing"])

    # Check if physical directory exists
    if not pathlib.Path(paths["album_viewing"]).exists():
        if found:
            parent_dir = directory.return_parent_directory()
        else:
            parent_dir = IndexDirs.objects.none()
        if parent_dir.exists():
            Cache_Storage.remove_from_cache_name(DirName=parent_dir[0].fqpndirectory)
            Cache_Storage.remove_from_cache_name(DirName=paths["album_viewing"])
            sync_database_disk(paths["album_viewing"])
        return HttpResponseNotFound("<h1>gallery not found</h1>")

    return found, directory


def _build_gallery_context(
    request: WSGIRequest, paths: dict, directory
) -> dict:  # pylint: disable=unused-argument
    """
    Build gallery-specific context using shared base context.

    Args:
        request: Django WSGIRequest object
        paths: Dictionary containing path information
        directory: IndexDirs object for the directory
    Returns: Context dictionary
    """
    # Start with shared base context
    context = _create_base_context(request)

    # Add gallery-specific context
    context.update(
        {
            "webpath": ensures_endswith(paths["webpath"], os.sep),
            "breadcrumbs": return_breadcrumbs(paths["webpath"])[:-1],
            "thumbpath": paths["thumbpath"],
            "gallery_name": pathlib.Path(paths["webpath"]).name,
            "up_uri": "/".join(request.build_absolute_uri().split("/")[0:-1]),
            "search": False,
            "prev_uri": None,
            "next_uri": None,
            "pagelist": [],
        }
    )

    return context


@vary_on_headers("HX-Request")
async def new_viewgallery(request: WSGIRequest):
    """
    View the requested Gallery page using optimized helper functions (ASGI async version).

    Args:
        request: Django Request object
    Returns: Django response
    """
    from frontend.managers import async_layout_manager
    from frontend.utilities import async_read_from_disk

    print("NEW VIEW GALLERY for ", request.path)
    start_time = time.perf_counter()

    # Use standardized template selection
    template_name = _determine_template(request, "gallery")
    paths = _process_request_path(request)
    directory_result = await sync_to_async(_find_directory)(paths)

    # Handle early returns from directory lookup
    if isinstance(directory_result, (HttpResponseNotFound, HttpResponseBadRequest)):
        return directory_result

    _, directory = directory_result

    # Ensure directory data is up to date
    await async_read_from_disk(paths["album_viewing"], skippable=True)

    # Build initial context
    context = _build_gallery_context(request, paths, directory)

    # Get layout data and update context (async wrapped)
    layout = await async_layout_manager(
        page_number=context["current_page"],
        directory=directory,
        sort_ordering=context["sort"],
    )

    # Update context with layout data efficiently
    context.update(
        {
            "total_pages": layout["total_pages"],
            "page_cnt": list(range(1, layout["total_pages"] + 1)),
        }
    )

    # Set navigation URIs (async function)
    context["prev_uri"], context["next_uri"] = await return_prev_next2(
        directory, sorder=context["sort"]
    )

    # Get current page data and build display items with optimized queries
    data_for_current_page = layout["data"]

    # Only fetch directories if there are any on this page (async wrapped)
    if data_for_current_page["directories"]:
        dirs_to_display = await sync_to_async(list)(
            directory.dirs_in_dir(sort=context["sort"])
            .filter(dir_fqpn_sha256__in=data_for_current_page["directories"])
            .select_related("filetype", "thumbnail__new_ftnail")
            .annotate(
                file_count_cached=Count(
                    "IndexData_entries",
                    filter=Q(IndexData_entries__delete_pending=False),
                )
            )
        )
    else:
        dirs_to_display = []

    # Only fetch files if there are any on this page (async wrapped)
    if data_for_current_page["files"]:
        files_and_links = await sync_to_async(list)(
            directory.files_in_dir(sort=context["sort"])
            .filter(unique_sha256__in=data_for_current_page["files"])
            .select_related("filetype", "home_directory", "new_ftnail")
        )

        # Separate files and links in Python (single query already executed)
        files_list = [f for f in files_and_links if not f.filetype.is_link]
        links_list = [f for f in files_and_links if f.filetype.is_link]
    else:
        files_list = []
        links_list = []

    context["items_to_display"] = list(dirs_to_display) + links_list + files_list
    # print("elapsed view gallery (pre-thumb) time - ", time.time() - start_time)
    if layout["no_thumbnails"]:
        no_thumb_start = time.time()
        print(f"{len(layout["no_thumbnails"])} entries need thumbnails")
        # print(layout["no_thumbnails"][0:10])  # Show first 10 entries needing thumbs

        batchsize = 100
        no_thumbs = layout["no_thumbnails"][0:batchsize]
        if no_thumbs:
            await process_thumbnails_async(layout, batchsize=100, max_workers=6)
            # Clear layout cache for affected pages
            for page_numb in range(0, context["current_page"] + 1):
                key = hashkey(
                    page_number=page_numb,
                    directory=directory,
                    sort_ordering=context["sort"],
                )
                if key in layout_manager_cache:
                    print("Key found in cache", key)
                    del layout_manager_cache[key]
        print("elapsed thumbnail time - ", time.time() - no_thumb_start)

    response = await async_render(
        request,
        f"{template_name}",
        context,
        using="Jinja2",
    )
    print("Gallery View, processing time: ", time.perf_counter() - start_time)
    return response


@sync_to_async
def process_thumbnail(sha256: str) -> tuple[bool, str, any]:
    """
    Process a single thumbnail with proper Django database handling.

    Args:
        sha256: SHA256 hash of the file to create thumbnail for
    Returns: Tuple of (success, sha256, thumbnail) where success is bool,
             sha256 is the file hash, and thumbnail is the ThumbnailFiles object or None
    """
    try:
        with transaction.atomic():
            thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
                sha256, suppress_save=False
            )
        return True, sha256, thumbnail
    except IntegrityError as e:
        print(f"Error creating thumbnail for {sha256}: {e}")
        return False, sha256, None
    except Exception as e:
        print(f"Unexpected error creating thumbnail for {sha256}: {e}")
        return False, sha256, None


async def process_thumbnails_async(
    layout: dict, batchsize: int = 100, max_workers: int = 4
) -> bool:
    """
    Process thumbnails using asyncio tasks for improved performance.

    Args:
        layout: Layout dictionary containing thumbnail information
        batchsize: Number of thumbnails to process in batch (default: 100)
        max_workers: Maximum number of concurrent tasks (default: 4)
    Returns: True if any thumbnails were successfully updated, False otherwise
    """
    no_thumbs = layout["no_thumbnails"][:batchsize]
    if not no_thumbs:
        return False

    print(f"Processing {len(no_thumbs)} thumbnails with {max_workers} concurrent tasks")

    # Process in batches to limit concurrency
    successful_count = 0
    for i in range(0, len(no_thumbs), max_workers):
        batch = no_thumbs[i:i + max_workers]
        tasks = [process_thumbnail(sha256) for sha256 in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                print(f"Task execution error: {result}")
            elif result and result[0]:
                successful_count += 1

    if successful_count > 0:
        print(f"Successfully processed {successful_count}/{len(no_thumbs)} thumbnails")
        return True
    return False


@vary_on_headers("HX-Request")
async def htmx_view_item(request: HtmxHttpRequest, sha256: str):
    """
    View individual item with HTMX support using standardized patterns (ASGI async version).

    Args:
        request: Django HtmxHttpRequest object
        sha256: SHA256 hash of the item to view
    Returns: Django response
    """
    from frontend.managers import async_build_context_info

    # Use standardized template selection
    template_name = _determine_template(request, "item")

    # Use managers.py for context building (async wrapped)
    context = await async_build_context_info(request, sha256)
    if isinstance(context, HttpResponseBadRequest):
        return context

    # Ensure user is in context (standardized pattern)
    context["user"] = request.user

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

    """
    sha_value = request.GET.get("usha", None) or request.GET.get("USHA", None)

    if sha_value in ["", None]:
        raise Http404("No Identifier provided for download.")
    sha_value = sha_value.strip().lower()

    # Wrap database query
    file_to_send = await sync_to_async(IndexData.get_by_sha256)(sha_value, unique=True)
    if file_to_send:
        # Use async sendfile method to avoid sync iterator warning
        return await file_to_send.async_inline_sendfile(
            request, ranged=file_to_send.filetype.is_movie
        )
    raise Http404("No File to Send")
