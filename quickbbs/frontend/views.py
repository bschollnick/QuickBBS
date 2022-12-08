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

import bleach
import django_icons.templatetags.icons
import markdown2
from django.conf import settings
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.utils import ProgrammingError
from django.http import (Http404, HttpResponseBadRequest, HttpResponseNotFound,
                         JsonResponse)
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from PIL import Image, ImageFile
from cache.models import fs_Cache_Tracking as Cache_Tracking
from quickbbs.models import Thumbnails_Dirs, Thumbnails_Files, index_data

import frontend.archives3 as archives
from frontend.database import get_db_files  # check_dup_thumbs
from frontend.thumbnail import (new_process_archive, new_process_dir,
                                new_process_img)
from frontend.utilities import (ensures_endswith, is_valid_uuid,
                                read_from_disk, return_breadcrumbs, sort_order)
from frontend.web import detect_mobile, g_option, respond_as_inline

log = logging.getLogger(__name__)
warnings.simplefilter('ignore', Image.DecompressionBombWarning)
ImageFile.LOAD_TRUNCATED_IMAGES = True
# https://stackoverflow.com/questions/12984426/
# Sending File or zipfile - https://djangosnippets.org/snippets/365/


DF_PNEXT = ["lastscan", "lastmod",
            "size", "numfiles",
            "numdirs", "parent_dir_id"]


def return_prev_next(fqpn, currentpath, sorder):
    """
    Read the parent directory, get the index of the current path,
    return the previous & next paths.

    Replace the old system, with Django pagination.
    """
    # Parent_path = Path(fqpn).parent
    fqpn = ensures_endswith(fqpn.lower(), os.sep)
    currentpath = os.path.split(currentpath.lower().strip())[1]
    read_from_disk(fqpn, skippable=True)
    index = get_db_files(sorder, fqpn)
    dirs_only = index.filter(ignore=False,
                             filetype__is_dir=True)
    dir_names = [dname.name.lower() for dname in dirs_only]
    nextdir = ""  # unnecessary since going beyond the max offset will cause indexerror.
    prevdir = ""
    try:
        current_offset = dir_names.index(currentpath) + 1
    except ValueError:
        return (prevdir, nextdir)

    try:
        nextdir = dir_names[current_offset]
    except IndexError:
        nextdir = ""

    try:
        if current_offset >= 2:
            prevdir = dir_names[current_offset - 2]
    except IndexError:
        prevdir = ""

    return (prevdir, nextdir)


@cache_page(500)
@vary_on_headers('User-Agent', 'Cookie', 'Request')
def thumbnails(request, tnail_id=None):
    """
    Serve the thumbnail resources

    URL -> thumbnails/(?P<t_url_name>.*)
    """
    #
    if is_valid_uuid(str(tnail_id)):
        index_qs = index_data.objects.filter(uuid=tnail_id,
                                             ignore=False, delete_pending=False)
        count = index_qs.count()
        if count == 0:
            # does not exist
            print(tnail_id, "is 0 ")
            return None

        index_qs = index_data.objects.filter(uuid=tnail_id)
        entry = index_qs[0]

        fs_item = os.path.join(entry.fqpndirectory, entry.name)
        fname = os.path.basename(fs_item).title()
        # thumb_size = g_option(request, "size", "Small").title()
        if entry.filetype.is_dir:
            if entry.directory is None:  # == None:
                entry.directory = Thumbnails_Dirs.objects.update_or_create(
                    uuid=entry.uuid, FilePath=fs_item, DirName=fname,
                    defaults={"uuid": entry.uuid,
                              "FilePath": fs_item,
                              "DirName": fname})[0]
                entry.save()
            return new_process_dir(entry)

        if entry.filetype.is_pdf or entry.filetype.is_image or entry.filetype.is_movie:
            if entry.file_tnail is None:  # == None:
                entry.file_tnail = Thumbnails_Files.objects.update_or_create(
                    uuid=entry.uuid,
                    FilePath=fs_item,
                    FileName=fname,
                    defaults={"uuid": entry.uuid,
                              "FilePath": fs_item,
                              "FileName": fname,
                              })[0]
                entry.save()
            return new_process_img(entry, request)

        # if entry.archives:
        #    page = int(g_option(request, "page", 0))
        #    return new_process_archive(entry, request, page)
    return HttpResponseBadRequest(content="Bad UUID or Unidentifable file.")


# @cache_page(500)
# @vary_on_headers('User-Agent', 'Cookie', 'Request')
def new_viewgallery(request):
    """
    View the requested Gallery page
    """
    print("NEW VIEW GALLERY")
    start_time = time.time()
    context = {}
    paths = {}
    context["small"] = g_option(request,
                                "size",
                                settings.IMAGE_SIZE["small"])
    context["medium"] = g_option(request,
                                 "size",
                                 settings.IMAGE_SIZE["medium"])

    context["large"] = g_option(request,
                                "size",
                                settings.IMAGE_SIZE["large"])
    context["user"] = request.user
    context["mobile"] = detect_mobile(request)
    request.path = request.path.lower().replace(os.sep, r"/")
    paths["webpath"] = request.path
    print("WebPath, View:", paths["webpath"])
    context["sort"] = sort_order(request)
    context["webpath"] = ensures_endswith(paths["webpath"], os.sep)
    context["breadcrumbs"] = return_breadcrumbs(paths["webpath"])[:-1]
    context["fromtimestamp"] = datetime.datetime.fromtimestamp
    # paths["album_viewing"] = configdata["locations"]["albums_path"] + paths["webpath"]
    paths["album_viewing"] = settings.ALBUMS_PATH + paths["webpath"]

    paths["thumbpath"] = paths["webpath"].replace(r"/albums/",
                                                  r"/thumbnails/")
    paths["thumbpath"] = ensures_endswith(paths["thumbpath"], "/")
    context["thumbpath"] = paths["thumbpath"]
    if not os.path.exists(paths["album_viewing"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    # The only thing left is a directory.
    fs_path = ensures_endswith(os.path.abspath(os.path.join(settings.ALBUMS_PATH,
                                                            paths["webpath"][1:])), os.sep)
    read_from_disk(fs_path, skippable=True)  # new_viewgallery
    index = get_db_files(context["sort"], fs_path)
    #    index = list(index.order_by(*SORT_MATRIX[context["sort"]]))
    #   already sorted by get_db_files call.

    context["current_page"] = request.GET.get("page", 1)
    chk_list = Paginator(index, 30)
    context["page_cnt"] = list(range(1, chk_list.num_pages + 1))

    #    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["up_uri"] = "/".join(request.build_absolute_uri().split("/")[0:-1])

    context["gallery_name"] = os.path.split(request.path_info)[-1]
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
    patch_vary_headers(response, [f"sort-{context['sort']}"])
    print("Gallery View, processing time: ", time.time() - start_time)
    return response


@cache_page(500)
@vary_on_headers('User-Agent', 'Cookie', 'Request', 'i_uuid')
def item_info(request, i_uuid):
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
    context = {}
    context["start_time"] = time.time()
    e_uuid = str(i_uuid).strip().replace("/", "")
    if not is_valid_uuid(e_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    context["sort"] = sort_order(request)
    entry = index_data.objects.filter(uuid=e_uuid)[0]

    context["html"] = ""
    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    breadcrumbs = return_breadcrumbs(context["webpath"])
    context["breadcrumbs"] = ""
    for bcrumb in breadcrumbs:
        context["breadcrumbs"] += f"<li>{bcrumb[2]}</li>"

    filename = context["webpath"].replace("/", os.sep).replace("//", "/") + entry.name
    if entry.filetype.is_text or entry.filetype.is_markdown:
        # context["html"] = markdown2.Markdown().convert("\n".join(open(filename).readlines()))
        with open(filename, 'r', encoding="latin-1") as textfile:
            context["html"] = markdown2.Markdown().convert("\n".join(textfile.readlines()))
    if entry.filetype.is_html:
        with open(filename, 'r', encoding="latin-1") as htmlfile:
            context["html"] = bleach.clean("<br>".join(htmlfile.readlines()))

    pathmaster = Path(os.path.join(entry.fqpndirectory, entry.name))
    context["up_uri"] = str(pathmaster.parent).lower().replace(settings.ALBUMS_PATH.lower(), "")
    while context["up_uri"].endswith("/"):
        context["up_uri"] = context["up_uri"][:-1]

    read_from_disk(context["webpath"].strip(), skippable=True)
    catalog_qs = get_db_files(context["sort"], context["webpath"])
    item_list = Paginator(catalog_qs, 1)

    pages = [str(record.uuid) for record in catalog_qs]
    context["page"] = pages.index(e_uuid) + 1
    context["page_locale"] = int(context["page"] / settings.GALLERY_ITEMS_PER_PAGE) + 1
    context["pagecount"] = item_list.count
    context["next_uuid"] = ""
    context["prev_uuid"] = ""
    context["uuid"] = entry.uuid
    context["filename"] = entry.name
    context["filesize"] = entry.size
    context["filecount"] = entry.numfiles
    context["dircount"] = entry.numdirs
    context["subdircount"] = entry.count_subfiles
    context["is_animated"] = entry.is_animated
    context["lastmod"] = entry.lastmod
    context["lastmod_ds"] = datetime.datetime.fromtimestamp(entry.lastmod). \
        strftime("%m/%d/%y %H:%M:%S")
    context["ft_filename"] = entry.filetype.icon_filename
    context["ft_color"] = entry.filetype.color
    context["ft_is_image"] = entry.filetype.is_image
    context["ft_is_archive"] = entry.filetype.is_archive
    context["ft_is_pdf"] = entry.filetype.is_pdf
    context["ft_is_movie"] = entry.filetype.is_movie
    context["ft_is_dir"] = entry.filetype.is_dir
    context["mobile"] = detect_mobile(request)

    page_contents = item_list.page(context["page"])
    if page_contents.has_next():
        context["next_uuid"] = catalog_qs[page_contents.next_page_number() - 1].uuid

    if page_contents.has_previous():
        context["previous_uuid"] = catalog_qs[page_contents.previous_page_number() - 1].uuid

    context["first_uuid"] = catalog_qs[0].uuid
    context["last_uuid"] = catalog_qs[catalog_qs.count() - 1].uuid
    print("Process time: ", time.time() - context["start_time"], "secs")
    response = JsonResponse(context, status=200)
    return response


@cache_page(300)
@vary_on_headers('User-Agent', 'Cookie', 'Request', 'i_uuid')
def new_json_viewitem(request, i_uuid):
    """

    Parameters
    ----------
    request
    i_uuid

    Returns
    -------

    """
    i_uuid = str(i_uuid).strip().replace("/", "")
    context = {}
    if not is_valid_uuid(i_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    context["sort"] = sort_order(request)
    context["uuid"] = i_uuid
    context["user"] = request.user
    response = render(request,
                      "frontend/gallery_json_item.jinja",
                      context,
                      using="Jinja2")
    patch_vary_headers(response, [f"sort-{context['sort']}"])
    return response


# @cache_page(60)  # Caching actually slows down the download, at least for small files.
@vary_on_headers('User-Agent', 'Cookie', 'Request', 'i_uuid')
def downloadFile(request, filename=None):
    """
    Replaces new_download.

    This now takes http://<servername>/downloads/<filename>?UUID=<uuid>

    This fakes the browser into displaying the filename as the title of the
    download.

    """
    # Is this from an archive?  If so, get the Page ID.
    d_uuid = request.GET.get("UUID", None)
    if d_uuid is None:  # == None:
        d_uuid = request.GET.get("uuid", None)

    if d_uuid in ["", None]:
        raise Http404

    page = request.GET.get('page', None)
    if page is None:
        download = index_data.objects.filter(uuid=d_uuid,
                                             ignore=False,
                                             delete_pending=False)[0]
    else:
        print(f"Attempting to find page {page} in archive")

    print(f"\tDownloading - {download.fqpndirectory.lower()}, {download.name}")

    return respond_as_inline(request,
                             download.fqpndirectory.lower(),
                             download.name,
                             ranged=download.filetype.is_movie)


# @cache_page(500)
# @vary_on_headers('User-Agent', 'Cookie', 'Request', 'i_uuid')
def new_view_archive(request, i_uuid):
    """
    Show the gallery from the archive contents
    """
    context = {}
    i_uuid = str(i_uuid).strip().replace("/", "")
    if not is_valid_uuid(i_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    #    context["sort"] = sort_order(request)
    e_uuid = i_uuid
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]
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

    context["next"] = ""
    context["previous"] = ""
    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    context["webpath"] = ensures_endswith(context["webpath"], "/")
    context["fromtimestamp"] = datetime.datetime.fromtimestamp
    # context["djicons"] = django_icons.templatetags.icons.icon
    context["djicons"] = django_icons.templatetags.icons.icon_tag
    arc_filename = settings.ALBUMS_PATH + context["webpath"].replace("/",
                                                                     os.sep).replace("//", "/") + entry.name
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
    patch_vary_headers(response, [f"sort-{context['sort']}"])
    return response


# @cache_page(500)
# @vary_on_headers('User-Agent', 'Cookie', 'Request', 'i_uuid')
def new_archive_item(request, i_uuid):
    """
    Show item in an archive
    """
    i_uuid = str(i_uuid).strip().replace("/", "")
    context = {}
    if not is_valid_uuid(i_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    context["sort"] = sort_order(request)
    e_uuid = i_uuid
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]
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
    else:
        context["next"] = ""

    if context["page_contents"].has_previous():
        context[
            "previous"] = f"view_archive_item/{entry.uuid}?page={context['page_contents'].previous_page_number() - 1}"
    else:
        context["previous"] = ""
    #
    context["first"] = f"view_archive_item/{entry.uuid}?page={0}"
    context["last"] = "view_archive_item/{}?page={}".format(entry.uuid, context["pagecount"])

    response = render(request,
                      "frontend/archive_item.html",
                      context)  # ,
    # using="Jinja2")
    patch_vary_headers(response, ["sort-%s" % context["sort"]])
    return response


print("Clearing all entries from Cache Tracking")
try:
    Cache_Tracking.objects.all().delete()
except ProgrammingError:
    print("Unable to clear Cache Table")

if 'runserver' in sys.argv or "--host" in sys.argv:
    print("Starting cleanup")
    #    check_for_deletes()
    print("Cleanup is done.")
    try:
        for prepath in settings.PRELOAD:
            print("Pre-Caching: ", prepath)
            read_from_disk(prepath.strip())  # startup

            # for ignored in configdata["filetypes"]["files_to_ignore"]:
            #    test = index_data.objects.filter(name__iexact=ignored.title())
            #    if test.exists():
            #        print("%s - %s" % (ignored, test.count()))
            #        test.delete()
    except:
        pass
