"""
Django views for QuickBBS Gallery
"""

import datetime
import logging
import os
import os.path
import pathlib
import time
import uuid
import warnings
from itertools import chain
from pathlib import Path
from typing import Optional

# import bleach
# import django_icons.templatetags.icons
import markdown2
import psycopg
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.utils import IntegrityError
from django.http import Http404, HttpResponseBadRequest, HttpResponseNotFound,HttpRequest,HttpResponse
from django.shortcuts import render
from django.views.decorators.vary import vary_on_headers
# from django.db.models import Q
from numpy import arange
from PIL import Image, ImageFile
from rest_framework.decorators import api_view
from rest_framework.response import Response

from cache_watcher.models import Cache_Storage
# import frontend.archives3 as archives
from frontend.database import SORT_MATRIX
from frontend.thumbnail import new_process_dir2
from frontend.utilities import (ensures_endswith, executor, read_from_disk,
                                return_breadcrumbs, sort_order,
                                sync_database_disk)
from frontend.web import detect_mobile, g_option, respond_as_attachment
from quickbbs.models import IndexData, IndexDirs  # , Thumbnails_Files
from thumbnails import image_utils
from thumbnails.models import ThumbnailFiles
import filetypes
from django_htmx.middleware import HtmxDetails

class HtmxHttpRequest(HttpRequest):
    htmx: HtmxDetails
# log = logging.getLogger(__name__)

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
    count = directories.count()
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

                # "webpath": request.path,
                # "album_viewing": settings.ALBUMS_PATH + request.path,
                nextdir = nextdir.replace(settings.ALBUMS_PATH, "")
            except IndexError:
                pass
            break
    return (prevdir, nextdir)


@sync_to_async
def thumbnail_dir(request: WSGIRequest, tnail_id: Optional[str] = None):
    """
    The thumbnails function is used to serve the thumbnail memory image.
    It takes a request and an optional uuid as arguments.
    If no uuid is provided, it will return the default image for thumbnails.
    Otherwise, it will attempt to find a matching UUID in the database and return that file's thumbnail.

    :param request: Django Request object
    :param tnail_id: the uuid of the original file / thumbnail uuid
    :return: The image of the thumbnail to send

    :raises: HttpResponseBadRequest - If the uuid can not be found
    """
    directory_to_tnail = IndexDirs.objects.prefetch_related("filetype").filter(
        uuid=tnail_id
    )
    if not directory_to_tnail.exists():
        # does not exist
        print(tnail_id, "The directory Does not exist, No records returned.")
        return Http404

    entry = directory_to_tnail[0]
    if entry.is_generic_icon:
        if entry.do_files_exist():
            entry.small_thumb = None
    if entry.small_thumb in [b"", None, ""]:
        new_process_dir2(entry)

    return entry.send_thumbnail()  # Send existing thumbnail


async def view_dir_thumbnail(request: WSGIRequest, tnail_id: Optional[str] = None):
    return await thumbnail_dir(request, tnail_id)


@sync_to_async
def thumbnail_file(request: WSGIRequest, tnail_id: Optional[str] = None):
    """
    Check for a thumbnail / create a thumbnail for a particular file
    :param request: Django Request object
    :param tnail_id: The UUID of the file - IndexData object
    :return: The sent thumbnail
    """
    index_qs = (
        IndexData.objects.prefetch_related("new_ftnail")
        .prefetch_related("filetype")
        .filter(uuid=tnail_id)
    )
    if not index_qs.exists():
        # does not exist
        print(tnail_id, "File not found - No records returned.")
        return Http404

    thumbsize = request.GET.get("size", "small").lower()
    entry = index_qs[0]
    fs_item = os.path.join(entry.fqpndirectory, entry.name).title().strip()
    fs_item_hash = ThumbnailFiles.convert_text_to_md5_hdigest(fs_item)
    # fname = os.path.basename(entry.name).title().strip()
    if entry.new_ftnail:
        if entry.new_ftnail.thumbnail_exists(size=thumbsize):
            return entry.new_ftnail.send_thumbnail(
                filename_override=None, fext_override=".jpg", size=thumbsize
            )
    print("Miss hit")
    # return HttpResponseBadRequest(content="Do not create thumbnail.")
    #
    #   The only reason for this code, is for the generic icons, needs to be refactored.
    #
    if entry.filetype.is_pdf or entry.filetype.is_image or entry.filetype.is_movie:
        # add in file size comparison
        # if not entry.new_ftnail:
        #     tnail_record, created = ThumbnailFiles.objects.get_or_create(
        #         fqpn_hash=fs_item_hash, defaults={"fqpn_hash": fs_item_hash, "fqpn_filename": fs_item}
        #     )
        #     # ThumbnailFiles.objects.filter(fqpn_hash=fs_item_hash).delete()
        tnail_record, _ = ThumbnailFiles.objects.get_or_create(
            fqpn_hash=fs_item_hash,
            defaults={"fqpn_hash": fs_item_hash, "fqpn_filename": fs_item},
        )

        entry.new_ftnail = tnail_record
        raw_pil = image_utils.return_image_obj(fs_item, memory=False)
        entry.new_ftnail.pil_to_thumbnail(pil_data=raw_pil)
        try:
            entry.new_ftnail.save()
        except (IntegrityError, psycopg.errors.UniqueViolation):
            print("IntegrityError, or UniqueViolation")
            # should not occur, but some mp4's appear to have been duplicated?
            ThumbnailFiles.objects.filter(fqpn_hash=fs_item_hash).delete()
            entry.new_ftnail.save()
        entry.save()
        return entry.new_ftnail.send_thumbnail(
            filename_override=None, fext_override=None, size=thumbsize
        )

    if entry.filetype.icon_filename not in ["", None]:
        entry.is_generic_icon = True
        try:
            entry.save()
        except IntegrityError:
            pass
        return respond_as_attachment(
            request,
            os.path.join(settings.RESOURCES_PATH, "Images"),
            entry.filetype.icon_filename,
        )

    return HttpResponseBadRequest(content="Bad UUID or Unidentifable file.")


async def view_thumbnail(request: WSGIRequest, tnail_id: Optional[str] = None):
    return await thumbnail_file(request, tnail_id)


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
    context["page_cnt"] = list(arange(1, chk_list.num_pages + 1))

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
        "frontend/gallery_listing.jinja",
        context,
        using="Jinja2",
    )
    print("search View, processing time: ", time.perf_counter() - start_time)
    return response


#@sync_to_async
def new_viewgallery(request: WSGIRequest):
    """
    View the requested Gallery page

    Args:
        request : Django Request object

    Returns:
        response : Django response

    """
    
    print("NEW VIEW GALLERY")
    if not filetypes.models.FILETYPE_DATA:
        print("Loading filetypes")
        filetypes.models.FILETYPE_DATA = filetypes.models.load_filetypes()

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

    # if found:
    #     directories = directory.dirs_in_dir(sort=sort_order(request))
    #     files = directory.files_in_dir(sort=sort_order(request))
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
    layout = layout_manager(
        page_number=context["current_page"],
        directory=directory,
        sort_ordering=context["sort"],
    )

    all_listings = layout["all_uuids"]

    chk_list = Paginator(all_listings, per_page=30)
    context["page_cnt"] = list(arange(1, chk_list.num_pages + 1))

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

    dirs_to_display = IndexDirs.return_by_uuid_list(sort=context["sort"],
        uuid_list=layout["data"][context["current_page"] - 1]["directories"]
    )
    files_to_display = IndexData.return_by_uuid_list(sort=context["sort"],
        uuid_list=layout["data"][context["current_page"] - 1]["files"]
    ).filter(filetype__is_link=False)
    links_to_display = IndexData.return_by_uuid_list(sort=context["sort"],
        uuid_list=layout["data"][context["current_page"] - 1]["files"]
    ).filter(filetype__is_link=True)

    context["items_to_display"] = list(chain(dirs_to_display, links_to_display, files_to_display))

    if layout["no_thumbnails"] not in ["", None, []]:
        start = time.time()
        print(f"{len(layout["no_thumbnails"])} entries need thumbnails")

        batchsize = 100
        no_thumbs = IndexData.return_by_uuid_list(uuid_list=layout["no_thumbnails"])[
            0:batchsize
        ]
        futures = []
        for db_entry in no_thumbs:
            futures.append(executor.submit(update_thumbnail, db_entry))
        _ = [f.result() for f in futures]

        print("elapsed thumbnail time - ", time.time() - start)

    response = render(
        request,
        "frontend/gallery_listing2.jinja",
        context,
        using="Jinja2",
    )
    print(
        "Gallery View, processing time: ", time.perf_counter() - start_time
    )  # time.time() - start_time)
    return response


def update_thumbnail(entry):
    fs_item = os.path.join(entry.fqpndirectory, entry.name).title().strip()
    fs_item_hash = ThumbnailFiles.convert_text_to_md5_hdigest(fs_item)
    thumbnail, _ = ThumbnailFiles.objects.get_or_create(
        fqpn_filename=fs_item, fqpn_hash=fs_item_hash
    )
    thumbnail.image_to_thumbnail()
    entry.new_ftnail = thumbnail
    entry.save()


def build_context_info(request: WSGIRequest, i_uuid:str):
    """
    Create the JSON package for item view.  All Json item requests come here to
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
    entry = IndexData.objects.prefetch_related("filetype").filter(
        uuid=context["uuid"]
    )[0]
    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    found, directory_entry = IndexDirs.search_for_directory(
        fqpn_directory=context["webpath"]
    )
    if not entry and not found:
        return HttpResponseBadRequest(content="No entry found.")

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
    context["up_uri"] = (
        str(pathmaster.parent).lower().replace(settings.ALBUMS_PATH.lower(), "")
    )
    while context["up_uri"].endswith("/"):
        context["up_uri"] = context["up_uri"][:-1]

    catalog_qs = directory_entry.files_in_dir(sort=context["sort"])
    page_uuids = list(catalog_qs.values_list("uuid", flat=True))
    context["mobile"] = detect_mobile(request)
    if context["mobile"]:
        context["size"] = "medium"
    else:
        context["size"] = "large"
    
    item_list = Paginator(catalog_qs, 1)

    try:
        current_page = page_uuids.index(uuid.UUID(context["uuid"])) + 1
    except ValueError:
        current_page = 1

    filetype_data = entry.filetype.__dict__
    context["filetype"] = filetype_data
    context.update(
        {
            "page": current_page,
            "first_uuid": page_uuids[0],
            "last_uuid": page_uuids[len(page_uuids) - 1],
            "pagecount": item_list.count,  # Switch this to math only, no paginator?
            "uuid": entry.uuid,
            "filename": entry.name,
            "filesize": entry.size,
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
    context["page_locale"] = (
        int(context["page"] / settings.GALLERY_ITEMS_PER_PAGE) + 1,
    )
    # up_uri uses this to return you to the same page offset you were viewing

    # generate next uuid pointers, switch this away from paginator?
    page_contents = item_list.page(context["page"])
    # try:
    #     context["previous_uuid"] = page_uuids[current_page-1]
    # except ValueError:
    #     pass
    # try:
    #     context["next_uuid"] = page_uuids[current_page+1]
    # except ValueError:
    #     pass
    if page_contents.has_next():
        context["next_uuid"] = catalog_qs[page_contents.next_page_number() - 1].uuid
    if page_contents.has_previous():
        context["previous_uuid"] = catalog_qs[
            page_contents.previous_page_number() - 1
        ].uuid
#    print(context)
    # print("item info - Process time: ", time.perf_counter() - context["start_time"], "secs")
    return context


# @api_view()
# def item_info(request: WSGIRequest, i_uuid: str) -> Response | HttpResponseBadRequest:
#     context = build_context_info(request, i_uuid)
#     return Response(context)

# @sync_to_async
# def new_json_viewitem(request: WSGIRequest, i_uuid: str):
#     """
#     This is the new view item.  It's a view stub, that calls item_info via json, to load the
#     data for the record.

#     Parameters
#     ----------
#     request : Django request object
#     i_uuid : the items uuid

#     Returns
#     -------
#     json : Json payload that contains the information regarding the item

#     """
#     if not filetypes.models.FILETYPE_DATA:
#         print("Loading filetypes")
#         filetypes.models.FILETYPE_DATA = filetypes.models.load_filetypes()

#     i_uuid = str(i_uuid).strip().replace("/", "")

#     context = {"sort": sort_order(request), "uuid": i_uuid, "user": request.user}
#     response = render(
#         request, "frontend/gallery_json_item.jinja", context, using="Jinja2"
#     )
#     return response


@sync_to_async
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
    if not filetypes.models.FILETYPE_DATA:
        print("Loading filetypes")
        filetypes.models.FILETYPE_DATA = filetypes.models.load_filetypes()

    # Is this from an archive?  If so, get the Page ID.
    d_uuid = request.GET.get("UUID", None)
    if d_uuid is None:  # == None:
        d_uuid = request.GET.get("uuid", None)

    if d_uuid in ["", None]:
        raise Http404

    download = IndexData.objects.filter(uuid=d_uuid)

    try:
        return download[0].inline_sendfile(
            request, ranged=download[0].filetype.is_movie
        )
    except FileNotFoundError:
        raise Http404


async def download_item(request: WSGIRequest):
    return await download_file(request)

@vary_on_headers("HX-Request")
#def test(request: WSGIRequest, i_uuid: str):
def test(request: HtmxHttpRequest, i_uuid: str):
#def test(request: WSGIRequest):
    """
    Test function for mockup tests
    :param request:
    :return:
    """
    if request.htmx.boosted and request.htmx.current_url is not None and not request.GET.get("newwin", False):
        print("partial")
        template_name = "frontend/gallery_htmx_partial.jinja"
    else:
        print("full")
        template_name = "frontend/gallery_htmx_complete.jinja"
    if not filetypes.models.FILETYPE_DATA:
        print("Loading filetypes")
        filetypes.models.FILETYPE_DATA = filetypes.models.load_filetypes()

    i_uuid = str(i_uuid).strip().replace("/", "")

    context = build_context_info(request, i_uuid) | {"user": request.user} # | {"sort": sort_order(request) }

    response = render(
        request, template_name, context, using="Jinja2"
    )
    return response
    # return render(
    #     request,
    #     "partial-rendering.html",
    #     context={
    #         "base_template": base_template,
    #         "page": page,
    #     },
    # )


def layout_manager(
    page_number=0, directory=None, sort_ordering=None):
    print("Sort Ordering", sort_ordering)
    output = {}
    output["data"] = {}
    output["page_number"] = page_number
    # context["paths"] = paths
    output["dirs_count"] = directory.get_dir_counts()
    output["chunk_size"] = settings.GALLERY_ITEMS_PER_PAGE
    output["numb_of_files_on_dir_lastpage"] = 30 - (
        output["dirs_count"] % output["chunk_size"]
    )
    output["numb_of_dirs_on_dir_lastpage"] = output["dirs_count"] % output["chunk_size"]

    output["files_count"] = directory.get_file_counts()
    output["total_pages"] = (
        int((output["dirs_count"] + output["files_count"]) / output["chunk_size"]) + 1
    )

    directories = list(
        directory.dirs_in_dir(sort=sort_ordering).values_list("uuid", flat=True)
    )
    files = list(directory.files_in_dir(sort=sort_ordering).values_list("uuid", flat=True))
#    links = list(directory.files_in_dir(sort=sort_ordering, additional_filters={'filetype__is_link':True}).values_list("uuid", flat=True))
 #   if links:
  #      files = set(files)
   #     files.difference_update(links)
    #    files = links + list(files)
    file_offset = 0
    for page_cnt in range(0, output["total_pages"]):
        data = {}
        data["page"] = page_cnt
        data["directories"] = directories[
            output["chunk_size"] * page_cnt : output["chunk_size"] * (page_cnt + 1)
        ]
        data["cnt_dirs"] = len(data["directories"])
        data["files"] = files[file_offset : 30 - data["cnt_dirs"] + file_offset]
        data["cnt_files"] = len(data["files"])
        data["total_cnt"] = data["cnt_dirs"] + data["cnt_files"]
        file_offset += data["cnt_files"]
        output["data"][page_cnt] = data
        # output["links"] = links
    output["all_uuids"] = list(chain(directories, files))
    output["no_thumbnails"] = list(
        directory.files_in_dir(sort=sort_ordering, additional_filters={'new_ftnail__isnull':True})
        .values_list("uuid", flat=True)
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
