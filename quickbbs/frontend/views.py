"""
Django views for QuickBBS Gallery
"""

import datetime
import logging
import math
import os
import os.path
import pathlib
import time
import uuid
import warnings
from functools import lru_cache
from itertools import chain
from pathlib import Path
from typing import Optional

import markdown2
# from asgiref.sync import sync_to_async
from cache_watcher.models import Cache_Storage
from cachetools import LRUCache, cached
from cachetools.keys import hashkey
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import close_old_connections, transaction # , connections, 
from django.db.utils import IntegrityError
from django.http import (  # HttpResponse,
    Http404,
    HttpRequest,
    HttpResponseBadRequest,
    HttpResponseNotFound,
)
from django.shortcuts import render
from django.views.decorators.vary import vary_on_headers
from django_htmx.middleware import HtmxDetails
from filetypes.models import load_filetypes # , filetypes 
from frontend.serve_up import static_or_resources
from frontend.utilities import SORT_MATRIX  # executor,
from frontend.utilities import (
#    MAX_THREADS,
#    DjangoConnectionThreadPoolExecutor,
    convert_to_webpath,
    ensures_endswith,
    read_from_disk,
    return_breadcrumbs,
    sort_order,
    sync_database_disk,
)
from frontend.web import detect_mobile, g_option # , respond_as_attachment
from PIL import Image, ImageFile
# from thumbnails import image_utils
from thumbnails.models import ThumbnailFiles
# from thumbnails.thumbnail_engine import FastImageProcessor

from quickbbs.models import IndexData, IndexDirs  # , Thumbnails_Files

# from rest_framework.decorators import api_view
# from rest_framework.response import Response
# from django.db.models import Q


class HtmxHttpRequest(HttpRequest):
    htmx: HtmxDetails


layout_manager_cache = LRUCache(maxsize=1000)

build_context_info_cache = LRUCache(maxsize=500)

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


@lru_cache(maxsize=250)
def return_prev_next2(directory, sorder) -> tuple:
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
    if parent_dir:
        parent_dir = parent_dir[0]
    else:
        return (None, None)
    directories = parent_dir.dirs_in_dir(sort=sorder)
    parent_dir_data = directories.values(
        "pk", "fqpndirectory", "parent_dir_md5", "combined_md5"
    )
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


def thumbnail2_dir(request: WSGIRequest, dir_sha256: Optional[str] = None):
    """
    The thumbnails function is used to serve the thumbnail memory image.
    It takes a request and an optional uuid as arguments.
    If no uuid is provided, it will return the default image for thumbnails.
    Otherwise, it will attempt to find a matching UUID in the database and return that file's thumbnail.

    :param request: Django Request object
    :param dir_sha256: the sha256 of the directory
    :return: The image of the thumbnail to send

    :raises: HttpResponseBadRequest - If the uuid can not be found
    """
    try:
        directory = IndexDirs.objects.get(dir_fqpn_sha256=dir_sha256)
    except IndexDirs.DoesNotExist:
        # does not exist
        print(dir_sha256, "Directory not found - No records returned.")
        return Http404
    file_count = 0

    if directory.is_generic_icon or directory.thumbnail in [b"", None]:
        # If the directory is generic or has no thumbnail, force a rescan
        # to help ensure that there are files in the directory
        sync_database_disk(directory.fqpndirectory)
        files_in_directory = directory.files_in_dir(
            additional_filters={"filetype__is_image": True}
        )
        file_count = len(files_in_directory)
        directory.thumbnail = files_in_directory.first() if files_in_directory else None
        directory.is_generic_icon = False
        directory.save()

    if directory.thumbnail is None:
        # there is no links (eg. Files) in the directory
        sync_database_disk(directory.fqpndirectory)
        files_in_directory = directory.files_in_dir(
            additional_filters={"filetype__is_image": True}
        )
        file_count = len(files_in_directory)
        if file_count == 0:
            if directory.is_generic_icon is False:
                directory.is_generic_icon = True
                directory.save()
            return static_or_resources(
                request,
                settings.RESOURCES_PATH
                + r"/images/"
                + directory.filetype.icon_filename,
            )  # Default icon

    if directory.thumbnail.new_ftnail is None:
        # If the thumbnail is not set, create a new thumbnail
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

    thumbsize = request.GET.get("size", "small").lower()
    return thumbnail.send_thumbnail(
        filename_override=thumbnail.IndexData.all().first().name,
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
        # "frontend/search_listing.jinja",
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
    print("NEW VIEW GALLERY")
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

    load_filetypes()

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
    all_listings = layout["all_uuids"]

    chk_list = Paginator(all_listings, per_page=30)
    context["page_cnt"] = list(range(1, chk_list.num_pages + 1))

    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
        context["current_page"] = 1
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    context["prev_uri"], context["next_uri"] = return_prev_next2(
        directory, sorder=context["sort"]
    )

    all_dirs_in_directory = directory.dirs_in_dir()
    all_files_in_directory = directory.files_in_dir()

    data_for_current_page = layout["data"][context["current_page"] - 1]
    dirs_to_display = all_dirs_in_directory.filter(
        uuid__in=data_for_current_page["directories"]
    ).order_by(*SORT_MATRIX[context["sort"]])

    files_to_display = (
        all_files_in_directory.filter(uuid__in=data_for_current_page["files"])
        .filter(filetype__is_link=False)
        .order_by(*SORT_MATRIX[context["sort"]])
    )

    links_to_display = (
        all_files_in_directory.filter(uuid__in=data_for_current_page["files"])
        .filter(filetype__is_link=True)
        .order_by(*SORT_MATRIX[context["sort"]])
    )

    context["items_to_display"] = list(
        chain(dirs_to_display, links_to_display, files_to_display)
    )

    # print("elapsed view gallery (pre-thumb) time - ", time.time() - start_time)
    if layout["no_thumbnails"]:
        no_thumb_start = time.time()
        print(f"{len(layout["no_thumbnails"])} entries need thumbnails")

        batchsize = 100
        no_thumbs = layout["no_thumbnails"][0:batchsize]

        if no_thumbs:
            updated_thumbnails = []
            with transaction.atomic():
                for sha256 in no_thumbs:
                    try:
                        thumbnail = ThumbnailFiles.get_or_create_thumbnail_record(
                            sha256, suppress_save=True
                        )
                        updated_thumbnails.append(thumbnail)
                    except IntegrityError as e:
                        print(f"Error creating thumbnail for {sha256}: {e}")
                if updated_thumbnails:
                    ThumbnailFiles.objects.bulk_create(
                        updated_thumbnails, ignore_conflicts=True, batch_size=25
                    )
                    # with transaction.atomic():
                    #     with DjangoConnectionThreadPoolExecutor(
                    #         max_workers=MAX_THREADS
                    #     ) as executor:
                    #         futures = []
                    #         for sha256 in no_thumbs:
                    #             futures.append(executor.submit(ThumbnailFiles.get_or_create_thumbnail_record, sha256))
                    #             #futures.append(executor.submit(update_thumbnail, db_entry))
                    #         _ = [f.result() for f in futures]
                    #         del futures
                    for page_numb in range(0, layout_settings["page_number"] + 1):
                        key = hashkey(
                            page_number=page_numb,
                            directory=layout_settings["directory"],
                            sort_ordering=layout_settings["sort_ordering"],
                        )
                        if key in layout_manager_cache:
                            print("Key found in cache", key)
                            del layout_manager_cache[key]
                        else:
                            print("Key not found in cache", key)
        print("elapsed thumbnail time - ", time.time() - no_thumb_start)
    # close_old_connections()

    response = render(
        request,
        f"{template_name}",
        context,
        using="Jinja2",
    )
    print("Gallery View, processing time: ", time.perf_counter() - start_time)
    return response


# def update_thumbnail(entry):
#     fs_item = os.path.join(entry.fqpndirectory, entry.name).title().strip()
#     if not entry.filetype.is_link:
#         thumbnail, created = ThumbnailFiles.objects.get_or_create(
#             sha256_hash=entry.file_sha256,
#             # defaults={"fqpn_filename": fs_item, "sha256_hash": entry.file_sha256},
#             defaults={"sha256_hash": entry.file_sha256},
#         )
#         if created:  # or not thumbnail.fqpn_filename:
#             entry.fqpn_filename = fs_item

#             # thumbnail.fqpn_filename = fs_item

#         entry.new_ftnail = thumbnail
#         entry.save()  # update_fields=["new_ftnail", "fqpn_filename"])
#         thumbnail.image_to_thumbnail()
#         thumbnail.save()


# @lru_cache(maxsize=500)
@cached(build_context_info_cache)
def build_context_info(request: WSGIRequest, i_uuid: str):
    """
    Create the JSON package for item view.  All Json *item* requests come here to
    get their data.

    Parameters
    ----------
    request : Django requests object
    i_uuid : The UUID4 id of the item to get the information on.

    Returns
    -------
    JsonResponse : The Json response from the web query.
    """
    context = {
        "start_time": time.perf_counter(),
        "uuid": str(i_uuid).strip().replace("/", ""),
        "sort": sort_order(request),
        "html": "",
        "breadcrumbs": "",
        "breadcrumbs_list": [],
    }
    try:
        # entry = IndexData.objects.select_related("filetype").get(uuid=context["uuid"])
        entry = IndexData.get_by_uuid(context["uuid"])
    except IndexData.DoesNotExist:
        return HttpResponseBadRequest(content="No entry found.")

    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    directory_entry = entry.home_directory

    # found, directory_entry = IndexDirs.search_for_directory(
    #    fqpn_directory=context["webpath"]
    # )
    # if not entry and not found:
    # return HttpResponseBadRequest(content="No entry found.")

    breadcrumbs = return_breadcrumbs(context["webpath"])
    for bcrumb in breadcrumbs:
        context["breadcrumbs"] += f"<li>{bcrumb[2]}</li>"
        context["breadcrumbs_list"].append(bcrumb[2])

    filename = context["webpath"].replace("/", os.sep).replace("//", "/") + entry.name

    if entry.filetype.is_text or entry.filetype.is_markdown:
        with open(filename, "r", encoding="ISO-8859-1") as textfile:
            context["html"] = markdown2.Markdown().convert(
                "\n".join(textfile.readlines())
            )
    if entry.filetype.is_html:
        with open(filename, "r", encoding="utf-8") as htmlfile:
            context["html"] = "<br>".join(htmlfile.readlines())

    pathmaster = Path(os.path.join(entry.fqpndirectory, entry.name))
    context["up_uri"] = convert_to_webpath(str(pathmaster.parent)).rstrip("/")

    all_uuids = list(
        directory_entry.files_in_dir(sort=context["sort"])
        .only("uuid")
        .values_list("uuid", flat=True)
    )
    context["mobile"] = detect_mobile(request)
    if context["mobile"]:
        context["size"] = "medium"
    else:
        context["size"] = "large"

    try:
        current_page = all_uuids.index(uuid.UUID(context["uuid"])) + 1
    except ValueError:
        current_page = 1

    context.update(
        {
            "filetype": entry.filetype.__dict__,
            "page": current_page,
            "first_uuid": all_uuids[0],
            "last_uuid": all_uuids[len(all_uuids) - 1],
            "pagecount": len(
                all_uuids
            ),  # item_list.count,  # Switch this to math only, no paginator?
            "uuid": entry.uuid,
            "filename": entry.name,
            "filesize": entry.size,
            "duration": entry.duration,
            "is_animated": entry.is_animated,
            "lastmod": entry.lastmod,
            "lastmod_ds": datetime.datetime.fromtimestamp(entry.lastmod).strftime(
                "%m/%d/%y %H:%M:%S"
            ),
            "ft_filename": entry.filetype.icon_filename,
            "download_uri": entry.get_download_url(),
            "next_uuid": "",
            "previous_uuid": "",
            "dir_link": f'{context["webpath"]}{entry.name}?sort={context["sort"]}',
            "thumbnail_uri": entry.get_thumbnail_url(size=context["size"]),
        }
    )
    context["page_locale"] = int(context["page"] / settings.GALLERY_ITEMS_PER_PAGE) + 1
    # up_uri uses this to return you to the same page offset you were viewing

    # generate next uuid pointers, switch this away from paginator?
    if current_page < len(all_uuids):
        context["next_uuid"] = all_uuids[
            current_page
        ]  # current_page is 1-indexed, so this gives us next
    else:
        context["next_uuid"] = ""

    if current_page > 1:
        context["previous_uuid"] = all_uuids[current_page - 2]  # Get the previous item
    else:
        context["previous_uuid"] = ""
    return context


def download_item(request: WSGIRequest):  # , filename=None):
    """
    Replaces new_download.

    This now takes http://<servername>/downloads/<filename>?UUID=<uuid>

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
    # Is this from an archive?  If so, get the Page ID.
    d_uuid = request.GET.get("UUID", None)
    if d_uuid is None:  # == None:
        d_uuid = request.GET.get("uuid", None)

    if d_uuid in ["", None]:
        raise Http404

    try:
        # download = IndexData.objects.get(uuid=d_uuid)
        download = IndexData.get_by_uuid(d_uuid)
        return download.inline_sendfile(request, ranged=download.filetype.is_movie)
    except (IndexData.DoesNotExist, FileNotFoundError):
        raise Http404


def download_file(request: WSGIRequest):  # , filename=None):
    """
    Replaces new_download.

    This now takes http://<servername>/downloads/<filename>?UUID=<uuid>

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
    # Is this from an archive?  If so, get the Page ID.
    sha_value = request.GET.get("usha", None)

    if sha_value in ["", None]:
        raise Http404

    # try:
    file_to_send = IndexData.get_by_sha256(sha_value, unique=False)
    if file_to_send is None:
        raise Http404
    return file_to_send.inline_sendfile(request, ranged=file_to_send.filetype.is_movie)
    # except (IndexData.DoesNotExist, FileNotFoundError):
    #    raise Http404


@vary_on_headers("HX-Request")
def htmx_view_item(request: HtmxHttpRequest, i_uuid: str):
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

    i_uuid = str(i_uuid).strip().replace("/", "")

    context = build_context_info(request, i_uuid) | {"user": request.user}

    response = render(request, template_name, context, using="Jinja2")
    return response


@cached(layout_manager_cache)
def layout_manager(page_number=0, directory=None, sort_ordering=None):
    """
    Optimized layout manager with better performance and readability.
    """
    if directory is None:
        raise ValueError("Directory parameter is required")

    chunk_size = settings.GALLERY_ITEMS_PER_PAGE

    # Optimize database queries with select_related/prefetch_related if needed
    # and only fetch what we need
    directories_queryset = directory.dirs_in_dir(sort=sort_ordering)
    files_queryset = directory.files_in_dir(sort=sort_ordering)

    # Get UUIDs in batches instead of loading everything at once
    directories = list(directories_queryset.values_list("uuid", flat=True))
    files = list(files_queryset.values_list("uuid", flat=True))

    # Get counts once and cache them
    dirs_count = len(directories)
    files_count = len(files)
    # total_items = dirs_count + files_count

    # Calculate pagination info
    # total_pages = (total_items + chunk_size - 1) // chunk_size  # Ceiling division
    total_pages = max(1, math.ceil((dirs_count + files_count) / chunk_size))
    # Build base output structure
    output = {
        "data": {},
        "page_number": page_number,
        "dirs_count": dirs_count,
        "chunk_size": chunk_size,
        "files_count": files_count,
        "total_pages": total_pages,
        "numb_of_dirs_on_dir_lastpage": dirs_count % chunk_size,
        "numb_of_files_on_dir_lastpage": chunk_size - (dirs_count % chunk_size),
    }

    # Process pages more efficiently
    file_offset = 0
    for page_cnt in range(total_pages):
        start_idx = chunk_size * page_cnt
        end_idx = chunk_size * (page_cnt + 1)

        # Get directories for this page
        page_directories = directories[start_idx:end_idx]
        dirs_on_page = len(page_directories)

        # Calculate remaining space for files
        files_space = chunk_size - dirs_on_page
        page_files = (
            files[file_offset : file_offset + files_space] if files_space > 0 else []
        )
        files_on_page = len(page_files)

        # Build page data
        output["data"][page_cnt] = {
            "page": page_cnt,
            "directories": page_directories,
            "cnt_dirs": dirs_on_page,
            "files": page_files,
            "cnt_files": files_on_page,
            "total_cnt": dirs_on_page + files_on_page,
        }

        file_offset += files_on_page

    # Add remaining data

    output["all_uuids"] = (
        directories + files
    )  # More efficient than itertools.chain for lists
    # Optimize the no_thumbnails query - only fetch UUIDs
    output["no_thumbnails"] = list(
        directory.files_in_dir(
            sort=sort_ordering, additional_filters={"new_ftnail__isnull": True}
        ).values_list("file_sha256", flat=True)
    )

    return output


# def view_setup():
#     """
#     Wrapper for view startup

#     """
#     pass

#    IndexData.objects.filter(delete_pending=True).delete()


# if __name__ != "__main__":
#    view_setup()
