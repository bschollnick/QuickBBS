"""
Django views for QuickBBS Gallery
"""
import datetime
import logging
import os
import os.path
import sys
import time
import warnings
from pathlib import Path

# import bleach
import django_icons.templatetags.icons
import markdown2
from PIL import Image, ImageFile
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.utils import ProgrammingError, OperationalError
from django.http import (Http404, HttpResponseBadRequest, HttpResponseNotFound)
from django.shortcuts import render
from numpy import arange
from quickbbs.models import Thumbnails_Dirs, Thumbnails_Files, index_data  # , scan_lock
from rest_framework.decorators import api_view
from rest_framework.response import Response

import frontend.archives3 as archives
from cache.models import fs_Cache_Tracking as Cache_Tracking
from frontend.database import get_db_files, SORT_MATRIX  # check_dup_thumbs
from frontend.thumbnail import (new_process_dir,
                                new_process_img)
from frontend.utilities import (ensures_endswith, is_valid_uuid,
                                read_from_disk, return_breadcrumbs, sort_order, sync_database_disk)
from frontend.web import detect_mobile, g_option, respond_as_inline, respond_as_attachment

from filetypes.models import FILETYPE_DATA

log = logging.getLogger(__name__)
warnings.simplefilter('ignore', Image.DecompressionBombWarning)
ImageFile.LOAD_TRUNCATED_IMAGES = True


# https://stackoverflow.com/questions/12984426/

# Sending File or zipfile - https://djangosnippets.org/snippets/365/


def return_prev_next(fqpn, currentpath, sorder) -> tuple:
    """
    The return_prev_next function takes a fully qualified pathname,
    and the current path as parameters. It returns the previous and next paths in a tuple.

    :param fqpn: Get the path of the parent directory
    :param currentpath: Determine the current offset in the list of files
    :param sorder: Determine whether the index is sorted by name or size
    :return: A tuple of two strings,

    """
    # Parent_path = Path(fqpn).parent
    fqpn = ensures_endswith(fqpn.lower(), os.sep).replace("//", "/")
    currentpath = os.path.split(currentpath.lower().strip())[1]
    read_from_disk(fqpn, skippable=True)
    index = get_db_files(sorder, fqpn)
    # dirs_only = index.exclude(ignore=True, delete_pending=False).filter(filetype__is_dir=True).only("name").values_list()
    dir_names = list(index.exclude(ignore=True, delete_pending=False).filter(filetype__is_dir=True).only(
        "name").values_list("name", flat=True))
    print(dir_names)
    # dir_names = [dname.name.lower() for dname in dirs_only]
    nextdir = ""  # unnecessary since going beyond the max offset will cause indexerror.
    prevdir = ""
    try:
        current_offset = dir_names.index(currentpath.title()) + 1
    except ValueError:
        print("VE")
        return prevdir, nextdir

    try:
        nextdir = dir_names[current_offset]
    except IndexError:
        pass

    try:
        if current_offset >= 2:
            prevdir = dir_names[current_offset - 2]
    except IndexError:
        pass

    return (prevdir, nextdir)


def thumbnails(request: WSGIRequest, tnail_id: str = None):
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
    if is_valid_uuid(str(tnail_id)):
        index_qs = index_data.objects.exclude(ignore=True, delete_pending=True).select_related("filetype").filter(
            uuid=tnail_id)
        if not index_qs.exists():
            # does not exist
            print(tnail_id, "No records returned.")
            return None

        entry = index_qs[0]
        fs_item = os.path.join(entry.fqpndirectory, entry.name)
        fname = os.path.basename(fs_item).title()
        if entry.filetype.icon_filename not in ["", None] and not entry.filetype.is_dir:
            entry.is_generic_icon = True
            entry.fqpndirectory = os.path.join(settings.RESOURCES_PATH, "images",
                                               entry.filetype.icon_filename)
            return respond_as_attachment(request, os.path.join(settings.RESOURCES_PATH, "Images"),
                                         entry.filetype.icon_filename)

        if entry.filetype.is_dir:
            if entry.directory is None:  # == None:
                entry.directory = Thumbnails_Dirs()
                entry.directory.uuid = entry.uuid
                entry.directory.FilePath = fs_item
                entry.directory.DirName = fname
            return new_process_dir(entry)

        if entry.filetype.is_pdf or entry.filetype.is_image or entry.filetype.is_movie:
            if entry.file_tnail is None:  # == None:
                entry.file_tnail = Thumbnails_Files()
                entry.file_tnail.uuid = entry.uuid
                entry.file_tnail.FilePath = fs_item
                entry.file_tnail.FileName = fname
            return new_process_img(entry, request)

        # if entry.archives:
        #    page = int(g_option(request, "page", 0))
        #    return new_process_archive(entry, request, page)
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
    context = {"small": g_option(request,
                                 "size",
                                 settings.IMAGE_SIZE["small"]),
               "medium": g_option(request,
                                  "size",
                                  settings.IMAGE_SIZE["medium"]),
               "large": g_option(request,
                                 "size",
                                 settings.IMAGE_SIZE["large"]),
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

    index = index_data.objects.filter(name__icontains=context["searchtext"]). \
        order_by(*SORT_MATRIX[context["sort"]])

    chk_list = Paginator(index, 30)
    context["page_cnt"] = list(arange(1, chk_list.num_pages + 1))

    if "/search/" in context["originator"] or context["originator"] is None:
        context["originator"] = request.GET.get("originator", "/albums")

    context["gallery_name"] = f"Searching for {context['searchtext']}"
    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
        context["current_page"] = 1
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)

    response = render(request,
                      "frontend/search_listing.jinja",
                      context,
                      using="Jinja2")
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
    paths = {"webpath": request.path,
             "album_viewing": settings.ALBUMS_PATH + request.path,
             "thumbpath": ensures_endswith(request.path.replace(r"/albums/",
                                                                r"/thumbnails/"), "/")
             }
    context = {"debug": settings.DEBUG,
               "small": g_option(request,
                                 "size",
                                 settings.IMAGE_SIZE["small"]),
               "medium": g_option(request,
                                  "size",
                                  settings.IMAGE_SIZE["medium"]),
               "large": g_option(request,
                                 "size",
                                 settings.IMAGE_SIZE["large"]),
               "user": request.user,
               "mobile": detect_mobile(request),
               "sort": sort_order(request),
               "webpath": ensures_endswith(paths["webpath"], os.sep),
               "breadcrumbs": return_breadcrumbs(paths["webpath"])[:-1],
               "fromtimestamp": datetime.datetime.fromtimestamp, "thumbpath": paths["thumbpath"],
               "current_page": request.GET.get("page", 1),
               "gallery_name": os.path.split(request.path_info)[-1],
               "up_uri": "/".join(request.build_absolute_uri().split("/")[0:-1]),
               }
    if not os.path.exists(paths["album_viewing"]):
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    # The only thing left is a directory.
    fs_path = ensures_endswith(os.path.abspath(os.path.join(settings.ALBUMS_PATH,
                                                            paths["webpath"][1:])), os.sep)
    read_from_disk(fs_path, skippable=True)  # new_viewgallery
    index = get_db_files(context["sort"], fs_path)

    chk_list = Paginator(index, 30)
    context["page_cnt"] = list(arange(1, chk_list.num_pages + 1))

    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
        context["current_page"] = 1
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    context["prev_uri"], context["next_uri"] = return_prev_next(
        os.path.dirname(paths["album_viewing"]),
        paths["webpath"], context["sort"])
    response = render(request,
                      "frontend/gallery_listing.jinja",
                      context,
                      using="Jinja2")
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
    start_time = time.perf_counter()  # time.time()
    context = {"start_time": time.perf_counter(),
               "uuid": str(i_uuid).strip().replace("/", ""),
               "sort": sort_order(request),
               "html": "",
               "breadcrumbs": "",
               "breadcrumbs_list": [],
               }

    entry = index_data.objects.select_related("filetype").filter(uuid=context["uuid"])[0]
    if not entry:
        return HttpResponseBadRequest(content="No entry found.")
    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")

    sync_database_disk(entry.fqpndirectory)
    breadcrumbs = return_breadcrumbs(context["webpath"])
    for bcrumb in breadcrumbs:
        context["breadcrumbs"] += f"<li>{bcrumb[2]}</li>"
        context["breadcrumbs_list"].append(bcrumb[2])

    filename = context["webpath"].replace("/", os.sep).replace("//", "/") + entry.name

    if entry.filetype.is_text or entry.filetype.is_markdown:
        with open(filename, 'r', encoding="ISO-8859-1") as textfile:
            context["html"] = markdown2.Markdown().convert("\n".join(textfile.readlines()))
    if entry.filetype.is_html:
        with open(filename, 'r', encoding="utf-8") as htmlfile:
            # context["html"] = bleach.clean("<br>".join(htmlfile.readlines()))
            context["html"] = "<br>".join(htmlfile.readlines())

    pathmaster = Path(os.path.join(entry.fqpndirectory, entry.name))
    context["up_uri"] = str(pathmaster.parent).lower().replace(settings.ALBUMS_PATH.lower(), "")
    while context["up_uri"].endswith("/"):
        context["up_uri"] = context["up_uri"][:-1]

    # read_from_disk(context["webpath"].strip(), skippable=True)
    catalog_qs = get_db_files(context["sort"], context["webpath"])

    page_uuids = [str(record.uuid) for record in catalog_qs]

    context["mobile"] = detect_mobile(request)
    if context["mobile"]:
        context["size"] = "medium"
    else:
        context["size"] = "large"
    item_list = Paginator(catalog_qs, 1)

    context.update({"page": page_uuids.index(context["uuid"]) + 1,
                    "first_uuid": page_uuids[0],
                    "last_uuid": page_uuids[len(page_uuids) - 1],
                    "pagecount": item_list.count,  # Switch this to math only, no paginator?
                    "uuid": entry.uuid,
                    "filename": entry.name,
                    "filesize": entry.size,
                    "filecount": entry.numfiles,
                    "dircount": entry.numdirs,
                    "subdircount": entry.count_subfiles,
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
                    })
    context["page_locale"] = int(context["page"] / settings.GALLERY_ITEMS_PER_PAGE) + 1,
    # up_uri uses this to return you to the same page offset you were viewing

    # generate next uuid pointers, switch this away from paginator?
    page_contents = item_list.page(context["page"])
    if page_contents.has_next():
        context["next_uuid"] = catalog_qs[page_contents.next_page_number() - 1].uuid
    if page_contents.has_previous():
        context["previous_uuid"] = catalog_qs[page_contents.previous_page_number() - 1].uuid
    print("item info - Process time: ", time.perf_counter() - context["start_time"], "secs")
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

    context = {"sort": sort_order(request),
               "uuid": i_uuid,
               "user": request.user}
    response = render(request,
                      "frontend/gallery_json_item.jinja",
                      context,
                      using="Jinja2")
    return response


def downloadFile(request: WSGIRequest):  # , filename=None):
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

    download = index_data.objects.select_related("filetype").exclude(ignore=True).filter(uuid=d_uuid,
                                                                                         delete_pending=False)

    if d_uuid in ["", None] or not download.exists():
        raise Http404

    return respond_as_inline(request,
                             download[0].fqpndirectory.lower(),
                             download[0].name,
                             ranged=download[0].filetype.is_movie)


def new_view_archive(request: WSGIRequest, i_uuid: str):
    """
    Show the gallery from the archive contents

    *need to rewrite*
    """
    context = {
        "next": "",
        "previous": ""
    }
    i_uuid = str(i_uuid).strip().replace("/", "")
    if not is_valid_uuid(i_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    entry = index_data.objects.filter(uuid=i_uuid)[0]
    context["basename"] = os.path.basename
    context["splitext"] = os.path.splitext
    context["small"] = g_option(request,
                                "size",
                                settings.IMAGE_SIZE["small"])
    # configdata["configuration"]["small"])
    context["medium"] = g_option(request,
                                 "size",
                                 # configdata["configuration"]["medium"])
                                 settings.IMAGE_SIZE["medium"])
    context["large"] = g_option(request,
                                "size",
                                # configdata["configuration"]["large"])
                                settings.IMAGE_SIZE["large"])
    context["user"] = request.user
    context["mobile"] = detect_mobile(request)
    context["sort"] = sort_order(request)

    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    context["webpath"] = ensures_endswith(context["webpath"], "/")
    context["fromtimestamp"] = datetime.datetime.fromtimestamp
    # context["djicons"] = django_icons.templatetags.icons.icon
    context["djicons"] = django_icons.templatetags.icons.icon_tag
    arc_filename = settings.ALBUMS_PATH + context["webpath"]. \
        replace("/", os.sep).replace("//", "/") + entry.name
    archive_file = archives.id_cfile_by_sig(arc_filename)
    archive_file.get_listings()
    context["db_entry"] = entry

    context["current_page"] = request.GET.get("page", 1)
    chk_list = Paginator(archive_file.listings, 30)
    context["page_cnt"] = list(range(1, chk_list.num_pages + 1))

    #    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["up_uri"] = entry.fqpndirectory.lower()

    context["gallery_name"] = os.path.split(request.path_info)[-1]
    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
        context["current_page"] = 1
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)

    context["first"] = "1"

    context["last"] = context["pagelist"].end_index

    response = render(request,
                      "frontend/archive_newgallery.jinja",
                      context,
                      using="Jinja2")
    return response


def test(request: WSGIRequest):
    response = render(request,
                      "frontend/test.html",
                      {},
                      using="Django")
    return response


def new_archive_item(request, i_uuid):
    """
    Show item in an archive

    *need to rewrite*

    """
    i_uuid = str(i_uuid).strip().replace("/", "")
    context = {"next": "",
               "prev": "",
               }
    if not is_valid_uuid(i_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    context["sort"] = sort_order(request)
    e_uuid = i_uuid
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]
    context.update({

    })
    item_fs = os.path.join(settings.ALBUMS_PATH,
                           entry.fqpndirectory[1:],
                           entry.name)
    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    #    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["up_uri"] = entry.fqpndirectory.lower()
    #        read_from_disk(context["webpath"].strip())

    context["current_page"] = int(request.GET.get("page", 0))  # 1 based not zero based
    context["page"] = context["current_page"] + 1  # 1 based not zero based
    #    print (context["current_page"])
    archive_file = archives.id_cfile_by_sig(item_fs)
    archive_file.get_listings()
    context["pagecount"] = len(archive_file.listings) - 1
    #    context["pagecount"] = archive_file.listings.count()-1
    context["item"] = entry
    item_list = Paginator(archive_file.listings, 1)
    context["page_contents"] = item_list.page(context["current_page"] + 1)

    if context["page_contents"].has_next():
        context["next"] = f"view_archive_item/{entry.uuid}?page={context['page_contents'].next_page_number() - 1}"

    if context["page_contents"].has_previous():
        context[
            "previous"] = f"view_archive_item/{entry.uuid}?page={context['page_contents'].previous_page_number() - 1}"

    context["first"] = f"view_archive_item/{entry.uuid}?page={0}"
    context["last"] = f"view_archive_item/{entry.uuid}?page={context['pagecount']}"

    response = render(request,
                      "frontend/archive_item.html",
                      context)  # ,
    # using="Jinja2")
    return response


def view_setup():
    """
    Wrapper for view startup

    """
    print("Clearing all entries from Directory Lock Tracking")
    #  scan_lock.release_all()

    print("Clearing all entries from Cache Tracking")
    try:
        Cache_Tracking.objects.all().delete()
    except ProgrammingError:
        print("Unable to clear Cache Table")
    except OperationalError:
        print("Cache table doesn't exist")

    if 'runserver' in sys.argv or "--host" in sys.argv:
        print("Starting cleanup")
        #    check_for_deletes()
        print("Cleanup is done.")
        if settings.DEMO:
            read_from_disk(os.path.join(settings.ALBUMS_PATH, "albums"))
        else:
            try:
                for prepath in settings.PRELOAD:
                    print("Pre-Caching: ", prepath)
                    read_from_disk(prepath.strip())  # startup
                read_from_disk(os.path.join(settings.ALBUMS_PATH, "albums"))
            except:
                pass
    index_data.objects.filter(delete_pending=True).delete()


if __name__ != "__main__":
    view_setup()
