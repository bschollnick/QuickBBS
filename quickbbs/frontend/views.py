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


def search_viewresults(request: WSGIRequest):
    """
    View the search results Gallery page

    Args:
        request : Django Request object

    Returns:
        respons : Django response

    """
    print("NEW search GALLERY")
    start_time = time.perf_counter()  # time.time()
    context = {
        "small": g_option(request, "size", settings.IMAGE_SIZE["small"]),
        "medium": g_option(request, "size", settings.IMAGE_SIZE["medium"]),
        "large": g_option(request, "size", settings.IMAGE_SIZE["large"]),
        "user": request.user,
        "mobile": detect_mobile(request),
        "sort": sort_order(request),
        "fromtimestamp": datetime.datetime.fromtimestamp,
        "searchtext": request.GET.get("searchtext", default=None),
        "current_page": request.GET.get("page", 1),
        "originator": request.headers.get("referer"),
        "prev_uri": "",
        "next_uri": "",
    }

    index = IndexData.objects.filter(name__icontains=context["searchtext"]).order_by(
        *SORT_MATRIX[context["sort"]]
    )

    chk_list = Paginator(index, per_page=30, orphans=3)
    context["page_cnt"] = list(range(1, chk_list.num_pages + 1))

    if "/search/" in context["originator"] or context["originator"] is None:
        context["originator"] = request.GET.get("originator", "/albums")
        context["search"] = True

    context["gallery_name"] = f"Searching for {context['searchtext']}"
    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
        context["current_page"] = 1
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)

    response = render(
        request,
        "frontend/search/gallery_listing.jinja",
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
            "page_range": list(range(1, layout["total_pages"] + 1)),
        }
    )

    context["prev_uri"], context["next_uri"] = return_prev_next2(
        directory, sorder=context["sort"]
    )
    # all_dirs_in_directory = directory.dirs_in_dir()
    # all_files_in_directory = directory.files_in_dir()

    data_for_current_page = layout["data"][context["current_page"] - 1]
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
