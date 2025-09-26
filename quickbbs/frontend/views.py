"""
Django views for QuickBBS Gallery
"""

import datetime
import logging
import os
import os.path
import pathlib
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import chain
from django.db.models import Q, Prefetch, Count, Case, When, IntegerField
import re
from typing import Optional

from cache_watcher.models import Cache_Storage
from cachetools.keys import hashkey
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import close_old_connections, connections, transaction
from django.db.utils import IntegrityError
from django.http import (
    Http404,
    HttpRequest,
    HttpResponseBadRequest,
    HttpResponseNotFound,
)
from django.shortcuts import render
from django.views.decorators.vary import vary_on_headers
from django_htmx.middleware import HtmxDetails
# from filetypes.models import load_filetypes  # Now loaded via middleware
from frontend.managers import build_context_info, layout_manager, layout_manager_cache
from frontend.utilities import (
    SORT_MATRIX,
    ensures_endswith,
    read_from_disk,
    return_breadcrumbs,
    sort_order,
    sync_database_disk,
)
from frontend.web import detect_mobile, g_option
from PIL import Image, ImageFile
from thumbnails.models import ThumbnailFiles

from quickbbs.models import IndexData, IndexDirs


class HtmxHttpRequest(HttpRequest):
    htmx: HtmxDetails


logger = logging.getLogger()

warnings.simplefilter("ignore", Image.DecompressionBombWarning)
ImageFile.LOAD_TRUNCATED_IMAGES = True


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


def return_prev_next2(directory, sorder: int) -> tuple[str | None, str | None]:
    """
    The return_prev_next function takes a fully qualified pathname,
    and the current path as parameters. It returns the previous and next paths in a tuple.

    :param fqpn: Get the path of the parent directory
    :param currentpath: Determine the current offset in the list of files
    :param sorder: Determine whether the index is sorted by name or size
    :return: A tuple of two strings,

    Note:
    ORM only derived from https://stackoverflow.com/questions/1042596/
            get-the-index-of-an-element-in-a-queryset
                Specifically Richard's answer.
    """
    nextdir = ""
    prevdir = ""
    parent_dir = directory.return_parent_directory()
    if not parent_dir:
        return (None, None)
    directories = parent_dir.dirs_in_dir(sort=sorder)
    parent_dir_data = directories.values("fqpndirectory")
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


def thumbnail2_dir(request: WSGIRequest, dir_sha256: str | None = None):
    """
    The thumbnails function is used to serve the thumbnail memory image.
    It takes a request and an optional sha256 as arguments.
    If no sha256 is provided, it will return the default image for thumbnails.
    Otherwise, it will attempt to find a matching sha256 in the database and return that file's thumbnail.

    :param request: Django Request object
    :param dir_sha256: the sha256 of the directory
    :return: The image of the thumbnail to send

    :raises: HttpResponseBadRequest - If the uuid can not be found
    """

    def get_files_for_review(directory):
        """
        Get a list of image files in the directory for thumbnail generation.

        :param directory: IndexDirs object representing the directory
        :return: QuerySet of image files in the directory
        """
        """
        Get a list of files in the directory for review.
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
            fext_override=".jpg", size="small"
        )  # Send existing thumbnail

    files_in_directory = get_files_for_review(directory)
    # If the directory is generic or has no thumbnail, force a rescan
    # to help ensure that there are files in the directory
    # set a thumbnail if there are files in the directory
    # file_count = files_in_directory.count() # len(files_in_directory)
    if not files_in_directory.exists():
        return directory.filetype.send_thumbnail()

    directory.thumbnail = files_in_directory.first()
    directory.is_generic_icon = False
    if (
        not directory.is_generic_icon
    ):  # We have found a thumbnail, and set it, so save changes
        directory.save()

    if directory.thumbnail in [b"", None]:
        # If the thumbnail is still None, it means that
        # there is no links (eg. Files) in the directory
        if not files_in_directory:
            if directory.is_generic_icon is False:
                directory.is_generic_icon = True
                directory.save()
            return directory.filetype.send_thumbnail()

    if directory.thumbnail.new_ftnail is None:
        # If the IndexData record (thumbnail) is not set,
        # then process it with get_or_create_thumbnail_record
        # to force the linkage to the thumbnail record.
        try:
            thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
                directory.thumbnail.file_sha256
            )
        except ThumbnailFiles.DoesNotExist:
            return HttpResponseBadRequest(content="Thumbnail not found.")

        directory.thumbnail.new_ftnail = thumbnail
        directory.save()

    if directory.thumbnail:
        return directory.thumbnail.new_ftnail.send_thumbnail(
            fext_override=".jpg", size="small"
        )  # Send existing thumbnail


def thumbnail2_file(request: WSGIRequest, sha256: str):
    """
    Check for a thumbnail / create a thumbnail for a particular file
    :param request: Django Request object
    :param sha256: The sha256 of the file - IndexData object
    :return: The sent thumbnail
    """
    try:
        thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(sha256)
    except ThumbnailFiles.DoesNotExist:
        print(sha256, "File not found - No records returned.")
        return HttpResponseBadRequest(content="Thumbnail not found.")

    if thumbnail.IndexData.first().filetype.generic:
        # If the filetype is a generic icon, then return the default icon
        return thumbnail.IndexData.first().filetype.send_thumbnail()

    thumbsize = request.GET.get("size", "small").lower()
    return thumbnail.send_thumbnail(
        filename_override=thumbnail.IndexData.first().name,
        fext_override=".jpg",
        size=thumbsize,
    )


@vary_on_headers("HX-Request")
def search_viewresults(request: WSGIRequest):
    """
    View the search results Gallery page

    Args:
        request : Django Request object

    Returns:
        response : Django response

    """
    print("NEW search GALLERY")

    # HTMX template selection
    if (
        request.htmx.boosted
        and request.htmx.current_url is not None
        and not request.GET.get("newwin", False)
    ):
        print("partial")
        template_name = "frontend/search/search_listings_partial.jinja"
    else:
        print("full")
        template_name = "frontend/search/search_listings_complete.jinja"

    start_time = time.perf_counter()
    searchtext = request.GET.get("searchtext", default=None)
    current_page = int(request.GET.get("page", 1))
    sort_order_value = sort_order(request)

    # Create regex pattern for separator-agnostic search (optimized approach)
    def create_search_regex_pattern(text):
        """
        Create a regex pattern for separator-agnostic search.
        This is more efficient than multiple OR conditions.

        Examples:
            'Mary Jane Watson' -> 'Mary[\\s_-]+Jane[\\s_-]+Watson'
            'spider_man' -> 'spider[\\s_-]+man'
            'single' -> 'single'

        Args:
            text: The search text to create regex pattern for

        Returns:
            Regex pattern string for case-insensitive matching, or empty string if invalid
        """
        if not text or not text.strip():
            return ''

        # Clean and normalize the input
        cleaned_text = text.strip()

        # Escape special regex characters to prevent regex injection
        try:
            escaped = re.escape(cleaned_text)
        except Exception:
            # If escaping fails for some reason, return empty to avoid errors
            return ''

        # Replace escaped separators with flexible pattern
        # [\s_-]+ matches one or more: spaces, underscores, or dashes
        pattern = (escaped
                   .replace(r'\ ', r'[\s_-]+')     # spaces to flexible separator
                   .replace(r'\_', r'[\s_-]+')     # underscores to flexible separator
                   .replace(r'\-', r'[\s_-]+'))    # dashes to flexible separator

        # Validate the pattern is reasonable (not too complex)
        if len(pattern) > 500:  # Prevent extremely long patterns
            return ''

        return pattern

    def fallback_search_query(searchtext, model_class, field_name):
        """
        Fallback search method using icontains if regex fails.
        Used as backup when regex pattern is invalid or causes database errors.

        Args:
            searchtext: Original search text
            model_class: Model to search (IndexData or IndexDirs)
            field_name: Field to search ('name' or 'fqpndirectory')

        Returns:
            QuerySet with fallback search results
        """
        if not searchtext or not searchtext.strip():
            return model_class.objects.none()

        return (model_class.objects
                .filter(**{f'{field_name}__icontains': searchtext.strip()})
                .filter(delete_pending=False))

    context = {
        "debug": settings.DEBUG,
        "small": g_option(request, "size", settings.IMAGE_SIZE["small"]),
        "medium": g_option(request, "size", settings.IMAGE_SIZE["medium"]),
        "large": g_option(request, "size", settings.IMAGE_SIZE["large"]),
        "user": request.user,
        "mobile": detect_mobile(request),
        "sort": sort_order_value,
        "fromtimestamp": datetime.datetime.fromtimestamp,
        "searchtext": searchtext,
        "current_page": current_page,
        "originator": request.headers.get("referer"),
        "gallery_name": f"Searching for {searchtext}",
        "search": True,
        "prev_uri": "",
        "next_uri": "",
        "breadcrumbs": [{"name": "Search Results", "url": request.path}],
        "webpath": "/search/",
        "up_uri": "/albums/",
        "missing": [],
        "items_to_display": [],
        "no_thumbnails": [],
    }

    # Search both files and directories with separator-agnostic matching (optimized)
    search_regex_pattern = create_search_regex_pattern(searchtext)
    print(f"Search text: '{searchtext}' -> Regex pattern: '{search_regex_pattern}'")

    # Directory search results (search directory paths for folder names)
    # Optimize with precomputed counts to avoid N+1 queries in template
    if search_regex_pattern:
        try:
            dirs = (
                IndexDirs.objects
                .filter(fqpndirectory__iregex=search_regex_pattern, delete_pending=False)
                .select_related('filetype')
                .annotate(
                    # Precompute file count (used by get_file_counts in template)
                    file_count_cached=Count('IndexData_entries',
                                          filter=Q(IndexData_entries__delete_pending=False)),
                    # Precompute directory count (used by get_dir_counts in template)
                    dir_count_cached=Count('parent_dir',
                                          filter=Q(parent_dir__delete_pending=False))
                )
                .prefetch_related('IndexData_entries__filetype')  # Still need files for other operations
                .order_by(*SORT_MATRIX[sort_order_value])
            )
        except Exception as e:
            # Fallback to simple icontains search if regex fails
            print(f"Regex search failed for directories, using fallback: {e}")
            dirs = (
                fallback_search_query(searchtext, IndexDirs, 'fqpndirectory')
                .select_related('filetype')
                .annotate(
                    file_count_cached=Count('IndexData_entries',
                                          filter=Q(IndexData_entries__delete_pending=False)),
                    dir_count_cached=Count('parent_dir',
                                          filter=Q(parent_dir__delete_pending=False))
                )
                .prefetch_related('IndexData_entries__filetype')
                .order_by(*SORT_MATRIX[sort_order_value])
            )
    else:
        dirs = IndexDirs.objects.none()

    # File search results (search filenames)
    if search_regex_pattern:
        try:
            files = (
                IndexData.objects
                .filter(name__iregex=search_regex_pattern, delete_pending=False)
                .select_related('filetype', 'home_directory')
                .prefetch_related('new_ftnail')
                .order_by(*SORT_MATRIX[sort_order_value])
            )
        except Exception as e:
            # Fallback to simple icontains search if regex fails
            print(f"Regex search failed for files, using fallback: {e}")
            files = (
                fallback_search_query(searchtext, IndexData, 'name')
                .select_related('filetype', 'home_directory')
                .prefetch_related('new_ftnail')
                .order_by(*SORT_MATRIX[sort_order_value])
            )
    else:
        files = IndexData.objects.none()

    # Combine results with directories/links first, then files
    # Convert to lists to allow sorting by type priority
    # Limit results to prevent performance issues with very large result sets
    MAX_SEARCH_RESULTS = 10000  # Reasonable limit for search results

    dir_list = list(dirs[:MAX_SEARCH_RESULTS//2])  # Limit directories
    file_list = list(files[:MAX_SEARCH_RESULTS//2])  # Limit files

    # Create combined list with directories first, then files
    combined_results = dir_list + file_list

    if len(combined_results) >= MAX_SEARCH_RESULTS:
        print(f"Search results limited to {MAX_SEARCH_RESULTS} items for performance")

    # Create a combined queryset-like object for pagination
    from django.core.paginator import Paginator
    index = combined_results

    chk_list = Paginator(index, per_page=30, orphans=3)
    context["page_cnt"] = list(range(1, chk_list.num_pages + 1))
    context["total_pages"] = chk_list.num_pages

    # Handle originator URL
    if "/search/" in str(context["originator"]) or context["originator"] is None:
        context["originator"] = request.GET.get("originator", "/albums")

    # Get paginated results
    try:
        pagelist = chk_list.page(current_page)
        context["pagelist"] = pagelist
        context["has_previous"] = pagelist.has_previous()
        context["has_next"] = pagelist.has_next()
    except PageNotAnInteger:
        pagelist = chk_list.page(1)
        context["pagelist"] = pagelist
        context["current_page"] = 1
        context["has_previous"] = False
        context["has_next"] = pagelist.has_next()
    except EmptyPage:
        pagelist = chk_list.page(chk_list.num_pages)
        context["pagelist"] = pagelist
        context["current_page"] = chk_list.num_pages
        context["has_previous"] = pagelist.has_previous()
        context["has_next"] = False

    # Set items to display from paginated results
    context["items_to_display"] = list(context["pagelist"].object_list)

    # Check for missing thumbnails and process if needed (only for files, not directories)
    files_needing_thumbnails = [
        item.file_sha256 for item in context["items_to_display"]
        if hasattr(item, 'file_sha256') and hasattr(item, 'new_ftnail') and item.new_ftnail is None and item.filetype.is_image
    ]

    if files_needing_thumbnails:
        print(f"{len(files_needing_thumbnails)} search results need thumbnails")
        context["no_thumbnails"] = files_needing_thumbnails

        # Note: Thumbnail generation is handled by the template system
        # Search results will show generic thumbnails for missing thumbnails

    response = render(
        request,
        template_name,
        context,
        using="Jinja2",
    )
    print("search View, processing time: ", time.perf_counter() - start_time)
    close_old_connections()
    return response


# @sync_to_async
@vary_on_headers("HX-Request")
def new_viewgallery(request: WSGIRequest):
    """
    View the requested Gallery page

    Args:
        request : Django Request object

    Returns:
        response : Django response

    """
    print("NEW VIEW GALLERY for ", request.path)
    if (
        request.htmx.boosted
        and request.htmx.current_url is not None
        and not request.GET.get("newwin", False)
    ):
        print("partial")
        template_name = "frontend/gallery/gallery_listing_partial.jinja"
    else:
        print("full")
        template_name = "frontend/gallery/gallery_listing_complete.jinja"

    # load_filetypes() - Now loaded via middleware, no per-request overhead

    start_time = time.perf_counter()  # time.time()
    request.path = request.path.lower().replace(os.sep, r"/")
    paths = {
        "webpath": request.path,
        "album_viewing": settings.ALBUMS_PATH + request.path,
        "thumbpath": ensures_endswith(
            request.path.replace(r"/albums/", r"/thumbnails/"), "/"
        ),
    }
    found, directory = IndexDirs.search_for_directory(paths["album_viewing"])
    if not found:
        sync_database_disk(paths["album_viewing"])
        found, directory = IndexDirs.search_for_directory(paths["album_viewing"])

        if not found:
            logger.info(f"Directory not found: {paths['album_viewing']}")
            return HttpResponseNotFound("<h1>gallery not found</h1>")

    logger.info(f"Viewing: {paths['album_viewing']}")

    if not os.path.exists(paths["album_viewing"]):
        if found:
            parent_dir = directory.return_parent_directory()
        else:
            parent_dir = IndexDirs.objects.none()
        if parent_dir.exists():
            Cache_Storage.remove_from_cache_name(DirName=parent_dir[0].fqpndirectory)
            Cache_Storage.remove_from_cache_name(DirName=paths["album_viewing"])
            sync_database_disk(paths["album_viewing"])
        #   Albums doesn't exist
        return HttpResponseNotFound("<h1>gallery not found</h1>")

    read_from_disk(paths["album_viewing"], skippable=True)  # new_viewgallery

    context = {
        "debug": settings.DEBUG,
        "small": g_option(request, "size", settings.IMAGE_SIZE["small"]),
        "user": request.user,
        "mobile": detect_mobile(request),
        "sort": sort_order(request),
        "webpath": ensures_endswith(paths["webpath"], os.sep),
        "breadcrumbs": return_breadcrumbs(paths["webpath"])[:-1],
        "fromtimestamp": datetime.datetime.fromtimestamp,
        "thumbpath": paths["thumbpath"],
        "current_page": int(request.GET.get("page", 1)),
        "gallery_name": pathlib.Path(paths["webpath"]).name,
        "up_uri": "/".join(request.build_absolute_uri().split("/")[0:-1]),
        "missing": [],
        "search": False,
        "page_cnt": [],
        "pagelist": [],
        "has_previous": False,
        "has_next": False,
        "prev_uri": None,
        "next_uri": None,
        "items_to_display": [],
        "no_thumbnails": [],
    }

    layout_settings = {
        "page_number": context["current_page"],
        "directory": directory,
        "sort_ordering": context["sort"],
    }
    layout = layout_manager(
        page_number=layout_settings["page_number"],
        directory=layout_settings["directory"],
        sort_ordering=layout_settings["sort_ordering"],
    )
    # all_listings = layout["all_shas"]

    context.update(
        {
            "total_pages": layout["total_pages"],
            # Removed page_range generation for memory optimization
        }
    )

    context["prev_uri"], context["next_uri"] = return_prev_next2(
        directory, sorder=context["sort"]
    )
    # all_dirs_in_directory = directory.dirs_in_dir()
    # all_files_in_directory = directory.files_in_dir()

    # New layout_manager returns single page data directly
    data_for_current_page = layout["data"]
    # dirs_to_display = all_dirs_in_directory.filter(
    #     dir_fqpn_sha256__in=data_for_current_page["directories"]
    # ).order_by(*SORT_MATRIX[context["sort"]])

    # files_to_display = (
    #     all_files_in_directory.filter(unique_sha256__in=data_for_current_page["files"])
    #     .filter(filetype__is_link=False)
    #     .order_by(*SORT_MATRIX[context["sort"]])
    # )

    # links_to_display = (
    #     all_files_in_directory.filter(unique_sha256__in=data_for_current_page["files"])
    #     .filter(filetype__is_link=True)
    #     .order_by(*SORT_MATRIX[context["sort"]])
    # )
    # context["items_to_display"] = list(
    #     chain(dirs_to_display, links_to_display, files_to_display)
    # )
  # Get all needed data in minimal queries with proper prefetching
    dirs_to_display = (
        directory.dirs_in_dir(sort=context["sort"])
        .filter(dir_fqpn_sha256__in=data_for_current_page["directories"])
        .select_related('filetype', 'thumbnail')
        .prefetch_related('thumbnail__new_ftnail')
        .annotate(
            # Precompute file count (used by get_file_counts in template)
            file_count_cached=Count('IndexData_entries',
                                  filter=Q(IndexData_entries__delete_pending=False)),
            # Precompute directory count (used by get_dir_counts in template)
            dir_count_cached=Count('parent_dir',
                                 filter=Q(parent_dir__delete_pending=False))
        )
    )

    files_and_links = (
        directory.files_in_dir(sort=context["sort"])
        .filter(unique_sha256__in=data_for_current_page["files"])
        .select_related('filetype', 'home_directory')
        .prefetch_related('new_ftnail')
    )

    # Separate files and links in Python (single query already executed)
    files_list = [f for f in files_and_links if not f.filetype.is_link]
    links_list = [f for f in files_and_links if f.filetype.is_link]

    context["items_to_display"] = list(dirs_to_display) + links_list + files_list
    # print("elapsed view gallery (pre-thumb) time - ", time.time() - start_time)
    if layout["no_thumbnails"]:
        no_thumb_start = time.time()
        print(f"{len(layout["no_thumbnails"])} entries need thumbnails")
        # print(layout["no_thumbnails"][0:10])  # Show first 10 entries needing thumbs

        batchsize = 100
        no_thumbs = layout["no_thumbnails"][0:batchsize]
        if no_thumbs:
            process_thumbnails_threaded(layout, batchsize=100, max_workers=6)
            for page_numb in range(0, layout_settings["page_number"] + 1):
                key = hashkey(
                    page_number=page_numb,
                    directory=layout_settings["directory"],
                    sort_ordering=layout_settings["sort_ordering"],
                )
                if key in layout_manager_cache:
                    print("Key found in cache", key)
                    del layout_manager_cache[key]
        print("elapsed thumbnail time - ", time.time() - no_thumb_start)

    response = render(
        request,
        f"{template_name}",
        context,
        using="Jinja2",
    )
    print("Gallery View, processing time: ", time.perf_counter() - start_time)
    return response


def process_thumbnail(sha256: str) -> tuple[bool, str, any]:
    """
    Process a single thumbnail with proper Django database handling.

    :param sha256: SHA256 hash of the file to create thumbnail for
    :return: Tuple of (success, sha256, thumbnail) where success is bool,
             sha256 is the file hash, and thumbnail is the ThumbnailFiles object or None
    """
    try:
        # Each thread needs its own database connection
        # Django handles this automatically when using transaction.atomic()
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
    finally:
        # Close the connection for this thread to prevent connection leaks
        connections.close_all()


def process_thumbnails_threaded(layout: dict, batchsize: int = 100, max_workers: int = 4) -> bool:
    """
    Process thumbnails using threaded multitasking for improved performance.

    :param layout: Layout dictionary containing thumbnail information
    :param batchsize: Number of thumbnails to process in batch (default: 100)
    :param max_workers: Maximum number of worker threads (default: 4)
    :return: True if any thumbnails were successfully updated, False otherwise
    """
    no_thumbs = layout["no_thumbnails"][0:batchsize]
    if not no_thumbs:
        return False

    updated_thumbnails = False
    successful_updates = []

    # Use ThreadPoolExecutor for better control over thread lifecycle
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_sha256 = {
            executor.submit(process_thumbnail, sha256): sha256 for sha256 in no_thumbs
        }

        # Process completed tasks
        for future in as_completed(future_to_sha256):
            sha256 = future_to_sha256[future]
            try:
                success, processed_sha256, thumbnail = future.result()
                if success:
                    updated_thumbnails = True
                    successful_updates.append(processed_sha256)
            except Exception as e:
                print(f"Thread execution error for {sha256}: {e}")

    return updated_thumbnails


@vary_on_headers("HX-Request")
def htmx_view_item(request: HtmxHttpRequest, sha256: str):
    """
    Test function for mockup tests
    :param request:
    :return:
    """
    if (
        request.htmx.boosted
        and request.htmx.current_url is not None
        and not request.GET.get("newwin", False)
    ):
        print("partial")
        template_name = "frontend/item/gallery_htmx_partial.jinja"
    else:
        print("full")
        template_name = "frontend/item/gallery_htmx_complete.jinja"

    context = build_context_info(request, sha256) | {"user": request.user}

    response = render(request, template_name, context, using="Jinja2")
    return response


def download_file(request: WSGIRequest):  # , filename=None):
    """
    Replaces new_download.

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
    file_to_send = IndexData.get_by_sha256(sha_value, unique=True)
    if file_to_send:
        return file_to_send.inline_sendfile(
            request, ranged=file_to_send.filetype.is_movie
        )
    raise Http404("No File to Send")
