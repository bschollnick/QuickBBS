"""
Django views for QuickBBS Gallery
"""

import datetime
import logging
import os
import os.path
import pathlib
from typing import Optional
import time
import warnings
from pathlib import Path

# import bleach
# import django_icons.templatetags.icons
import markdown2
from cache.models import Cache_Storage
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.utils import IntegrityError
from django.http import Http404, HttpResponseBadRequest, HttpResponseNotFound
from django.shortcuts import render

# from django.db.models import Q
from numpy import arange
from PIL import Image, ImageFile
from quickbbs.models import IndexData, IndexDirs  # , Thumbnails_Files
from rest_framework.decorators import api_view
from rest_framework.response import Response

# import frontend.archives3 as archives
from frontend.database import SORT_MATRIX, get_db_files  # check_dup_thumbs
from frontend.thumbnail import new_process_dir2, new_process_img
from frontend.utilities import (
    ensures_endswith,
    read_from_disk,
    return_breadcrumbs,
    sort_order,
    sync_database_disk,
)
from thumbnails.models import ThumbnailFiles
import thumbnails.image_utils as image_utils
from frontend.web import detect_mobile, g_option, respond_as_attachment

log = logging.getLogger(__name__)
warnings.simplefilter("ignore", Image.DecompressionBombWarning)
ImageFile.LOAD_TRUNCATED_IMAGES = True


# https://stackoverflow.com/questions/12984426/

# Sending File or zipfile - https://djangosnippets.org/snippets/365/


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
    # Parent_path = Path(fqpn).parent
    # unnecessary since going beyond the max offset will cause indexerror.
    nextdir = ""
    prevdir = ""
    parent_dir = directory.return_parent_directory()
    if parent_dir:
        parent_dir = parent_dir[0]
    else:
        return (None, None)
    count, directories = parent_dir.dirs_in_dir(sort=sorder)
    parent_dir_data = directories.values("pk", "fqpndirectory", "parent_dir_md5", "combined_md5")
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
    directory_to_tnail = IndexDirs.objects.filter(uuid=tnail_id)
    if not directory_to_tnail.exists():
        # does not exist
        print(tnail_id, "The directory Does not exist, No records returned.")
        return Http404

    entry = directory_to_tnail[0]
    count = 0
    if entry.is_generic_icon:
        count = entry.get_file_counts()
        if count in [0, None]:
            entry.small_thumb = None
    if entry.small_thumb in [b"", None, ""]:
        new_process_dir2(entry)

    return entry.send_thumbnail()  # Send existing thumbnail


def thumbnail_file(request: WSGIRequest, tnail_id: Optional[str] = None):
    """
    Check for a thumbnail / create a thumbnail for a particular file
    :param request: Django Request object
    :param tnail_id: The UUID of the file - IndexData object
    :return: The sent thumbnail
    """
    index_qs = IndexData.objects.prefetch_related("filetype").filter(uuid=tnail_id)
    if not index_qs.exists():
        # does not exist
        print(tnail_id, "File not found - No records returned.")
        return Http404

    thumbsize = request.GET.get("size", "small").lower()
    entry = index_qs[0]
    fs_item = os.path.join(entry.fqpndirectory, entry.name)
    fs_item_hash = ThumbnailFiles.convert_text_to_md5_hdigest(fs_item)
    fname = os.path.basename(entry.name).title()
    if entry.new_ftnail:
        if entry.new_ftnail.thumbnail_exists(size=thumbsize):
            return entry.new_ftnail.send_thumbnail(filename_override=None, fext_override=None, size=thumbsize)

    if entry.filetype.is_pdf or entry.filetype.is_image or entry.filetype.is_movie:
        # add in file size comparison
        if not entry.new_ftnail:
            tnail_record, created = ThumbnailFiles.objects.get_or_create(
                fqpn_hash=fs_item_hash, defaults={"fqpn_hash": fs_item_hash, "fqpn_filename": fs_item}
            )
            entry.new_ftnail = tnail_record
            raw_pil = image_utils.return_image_obj(fs_item, memory=False)
            entry.new_ftnail.pil_to_thumbnail(pil_data=raw_pil)
            entry.new_ftnail.save()
            entry.save()
            return entry.new_ftnail.send_thumbnail(filename_override=None, fext_override=None, size=thumbsize)

    if entry.filetype.icon_filename not in ["", None]:
        entry.is_generic_icon = True
        entry.fqpndirectory = os.path.join(settings.RESOURCES_PATH, "images", entry.filetype.icon_filename)
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
        "originator": request.META.get("HTTP_REFERER"),
        "prev_uri": "",
        "next_uri": "",
    }

    index = IndexData.objects.filter(name__icontains=context["searchtext"]).order_by(*SORT_MATRIX[context["sort"]])

    chk_list = Paginator(index, 30)
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


def new_viewgallery(request: WSGIRequest):
    """
    View the requested Gallery page

    Args:
        request : Django Request object

    Returns:
        response : Django response

    """
    print("NEW VIEW GALLERY")
    start_time = time.perf_counter()  # time.time()
    request.path = request.path.lower().replace(os.sep, r"/")
    paths = {
        "webpath": request.path,
        "album_viewing": settings.ALBUMS_PATH + request.path,
        "thumbpath": ensures_endswith(request.path.replace(r"/albums/", r"/thumbnails/"), "/"),
    }
    found, directory = IndexDirs.search_for_directory(paths["album_viewing"])
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

    directories = []
    files = []
    if found:
        #        if counts["all_files"] == 0:
        _, directories = directory.dirs_in_dir(sort=sort_order(request))
        _, files = directory.files_in_dir(sort=sort_order(request))
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
        "current_page": request.GET.get("page", 1),
        "gallery_name": pathlib.Path(paths["webpath"]).name,
        "up_uri": "/".join(request.build_absolute_uri().split("/")[0:-1]),
        "missing": [],
        "search": False,
    }

    context["all_listings"] = list(directories)
    context["all_listings"].extend(list(files))
    context["no_thumbs"] = []

    if files:
        context["no_thumbs"] = files.filter(new_ftnail__isnull=True)[0:99]
    # The only thing left is a directory.
    # fs_path = ensures_endswith(
    #     os.path.abspath(os.path.join(settings.ALBUMS_PATH, paths["webpath"][1:])),
    #     os.sep,
    # )

    chk_list = Paginator(context["all_listings"], 30)
    context["page_cnt"] = list(arange(1, chk_list.num_pages + 1))

    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
        context["current_page"] = 1
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    context["prev_uri"], context["next_uri"] = return_prev_next2(directory, sorder=context["sort"])

    response = render(
        request,
        "frontend/gallery_listing2.jinja",
        context,
        using="Jinja2",
    )
    print("Gallery View, processing time: ", time.perf_counter() - start_time)  # time.time() - start_time)
    return response


@api_view()
def item_info(request: WSGIRequest, i_uuid: str) -> Response | HttpResponseBadRequest:
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
    # start_time = time.perf_counter()  # time.time()
    context = {
        "start_time": time.perf_counter(),
        "uuid": str(i_uuid).strip().replace("/", ""),
        "sort": sort_order(request),
        "html": "",
        "breadcrumbs": "",
        "breadcrumbs_list": [],
    }

    entry = IndexData.objects.select_related("filetype").filter(uuid=context["uuid"])[0]
    if not entry:
        # sync_database_disk(entry.fqpndirectory)
        entry = IndexData.objects.select_related("filetype").filter(uuid=context["uuid"])[0]
        if not entry:
            return HttpResponseBadRequest(content="No entry found.")
    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")

    breadcrumbs = return_breadcrumbs(context["webpath"])
    for bcrumb in breadcrumbs:
        context["breadcrumbs"] += f"<li>{bcrumb[2]}</li>"
        context["breadcrumbs_list"].append(bcrumb[2])

    filename = context["webpath"].replace("/", os.sep).replace("//", "/") + entry.name

    if entry.filetype.is_text or entry.filetype.is_markdown:
        with open(filename, "r", encoding="ISO-8859-1") as textfile:
            context["html"] = markdown2.Markdown().convert("\n".join(textfile.readlines()))
    if entry.filetype.is_html:
        with open(filename, "r", encoding="utf-8") as htmlfile:
            # context["html"] = bleach.clean("<br>".join(htmlfile.readlines()))
            context["html"] = "<br>".join(htmlfile.readlines())

    pathmaster = Path(os.path.join(entry.fqpndirectory, entry.name))
    context["up_uri"] = str(pathmaster.parent).lower().replace(settings.ALBUMS_PATH.lower(), "")
    while context["up_uri"].endswith("/"):
        context["up_uri"] = context["up_uri"][:-1]

    catalog_qs = get_db_files(context["sort"], context["webpath"])

    page_uuids = [str(record.uuid) for record in catalog_qs]

    context["mobile"] = detect_mobile(request)
    context["size"] = "large"
    if context["mobile"]:
        context["size"] = "medium"
    item_list = Paginator(catalog_qs, 1)

    context.update(
        {
            "page": page_uuids.index(context["uuid"]) + 1,
            "first_uuid": page_uuids[0],
            "last_uuid": page_uuids[len(page_uuids) - 1],
            "pagecount": item_list.count,  # Switch this to math only, no paginator?
            "uuid": entry.uuid,
            "filename": entry.name,
            "filesize": entry.size,
            #   "filecount": entry.numfiles,
            #   "dircount": entry.numdirs,
            #   "subdircount": entry.count_subfiles,
            "is_animated": entry.is_animated,
            "lastmod": entry.lastmod,
            "lastmod_ds": datetime.datetime.fromtimestamp(entry.lastmod).strftime("%m/%d/%y %H:%M:%S"),
            "ft_filename": entry.filetype.icon_filename,
            "ft_color": entry.filetype.color,
            "ft_is_image": entry.filetype.is_image,
            "ft_is_archive": entry.filetype.is_archive,
            "ft_is_pdf": entry.filetype.is_pdf,
            "ft_is_movie": entry.filetype.is_movie,
            "ft_is_dir": entry.filetype.is_dir,
            "download_uri": entry.get_download_url(),
            "next_uuid": "",
            "previous_uuid": "",
            "dir_link": f'{context["webpath"]}{entry.name}?sort={context["sort"]}',
            "thumbnail_uri": entry.get_thumbnail_url(size=context["size"]),
        }
    )
    context["page_locale"] = (int(context["page"] / settings.GALLERY_ITEMS_PER_PAGE) + 1,)
    # up_uri uses this to return you to the same page offset you were viewing

    # generate next uuid pointers, switch this away from paginator?
    page_contents = item_list.page(context["page"])
    if page_contents.has_next():
        context["next_uuid"] = catalog_qs[page_contents.next_page_number() - 1].uuid
    if page_contents.has_previous():
        context["previous_uuid"] = catalog_qs[page_contents.previous_page_number() - 1].uuid
    # print("item info - Process time: ", time.perf_counter() - context["start_time"], "secs")
    return Response(context)


def new_json_viewitem(request: WSGIRequest, i_uuid: str):
    """
    This is the new view item.  It's a view stub, that calls item_info via json, to load the
    data for the record.

    Parameters
    ----------
    request : Django request object
    i_uuid : the items uuid

    Returns
    -------
    json : Json payload that contains the information regarding the item

    """
    i_uuid = str(i_uuid).strip().replace("/", "")

    context = {"sort": sort_order(request), "uuid": i_uuid, "user": request.user}
    response = render(request, "frontend/gallery_json_item.jinja", context, using="Jinja2")
    return response


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
    d_uuid = request.GET.get("UUID", None)
    if d_uuid is None:  # == None:
        d_uuid = request.GET.get("uuid", None)

    if d_uuid in ["", None]:
        raise Http404

    download = IndexData.objects.prefetch_related("filetype").filter(uuid=d_uuid)

    try:
        return download[0].inline_sendfile(request, ranged=download[0].filetype.is_movie)
    except FileNotFoundError:
        raise Http404


#
# def new_view_archive(request: WSGIRequest, i_uuid: str):
#     """
#     Show the gallery from the archive contents
#
#     *need to rewrite*
#     """
#     context = {"next": "", "previous": ""}
#     i_uuid = str(i_uuid).strip().replace("/", "")
#     if not is_valid_uuid(i_uuid):
#         return HttpResponseBadRequest(content="Non-UUID thumbnail request.")
#
#     entry = IndexData.objects.filter(uuid=i_uuid)[0]
#     context["basename"] = os.path.basename
#     context["splitext"] = os.path.splitext
#     context["small"] = g_option(request, "size", settings.IMAGE_SIZE["small"])
#     # configdata["configuration"]["small"])
#     context["medium"] = g_option(
#         request,
#         "size",
#         # configdata["configuration"]["medium"])
#         settings.IMAGE_SIZE["medium"],
#     )
#     context["large"] = g_option(
#         request,
#         "size",
#         # configdata["configuration"]["large"])
#         settings.IMAGE_SIZE["large"],
#     )
#     context["user"] = request.user
#     context["mobile"] = detect_mobile(request)
#     context["sort"] = sort_order(request)
#
#     context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
#     context["webpath"] = ensures_endswith(context["webpath"], "/")
#     context["fromtimestamp"] = datetime.datetime.fromtimestamp
#     # context["djicons"] = django_icons.templatetags.icons.icon
#     context["djicons"] = django_icons.templatetags.icons.icon_tag
#     arc_filename = (
#         settings.ALBUMS_PATH
#         + context["webpath"].replace("/", os.sep).replace("//", "/")
#         + entry.name
#     )
#     archive_file = archives.id_cfile_by_sig(arc_filename)
#     archive_file.get_listings()
#     context["db_entry"] = entry
#
#     context["current_page"] = request.GET.get("page", 1)
#     chk_list = Paginator(archive_file.listings, 30)
#     context["page_cnt"] = list(range(1, chk_list.num_pages + 1))
#
#     #    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
#     context["up_uri"] = entry.fqpndirectory.lower()
#
#     context["gallery_name"] = os.path.split(request.path_info)[-1]
#     try:
#         context["pagelist"] = chk_list.page(context["current_page"])
#     except PageNotAnInteger:
#         context["pagelist"] = chk_list.page(1)
#         context["current_page"] = 1
#     except EmptyPage:
#         context["pagelist"] = chk_list.page(chk_list.num_pages)
#
#     context["first"] = "1"
#
#     context["last"] = context["pagelist"].end_index
#
#     response = render(
#         request, "frontend/archive_newgallery.jinja", context, using="Jinja2"
#     )
#     return response


def test(request: WSGIRequest):
    """
    Test function for mockup tests
    :param request:
    :return:
    """
    response = render(request, "frontend/test.html", {}, using="Django")
    return response


def view_setup():
    """
    Wrapper for view startup

    """
    pass
    # if 'runserver' in sys.argv or "--host" in sys.argv:
    #     print("Starting cleanup")
    #     #    check_for_deletes()
    #     print("Cleanup is done.")
    #     if settings.DEMO:
    #         read_from_disk(os.path.join(settings.ALBUMS_PATH, "albums"))
    #     else:
    #         try:
    #             for prepath in settings.PRELOAD:
    #                 print("Pre-Caching: ", prepath)
    #                 read_from_disk(prepath.strip())  # startup
    #             read_from_disk(os.path.join(settings.ALBUMS_PATH, "albums"))
    #         except:
    #             pass


#    IndexData.objects.filter(delete_pending=True).delete()


if __name__ != "__main__":
    view_setup()
