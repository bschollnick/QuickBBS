# coding: utf-8
"""
Django views for QuickBBS Gallery
"""
from __future__ import absolute_import, print_function, unicode_literals

import datetime
from itertools import chain
import os
import os.path
import sys
import time
import warnings

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import (HttpResponse, HttpResponseNotFound,
                         HttpResponseBadRequest)
from django.shortcuts import render
from django.template import loader
from django.utils.cache import patch_vary_headers
from django.views.decorators.vary import vary_on_headers
from PIL import Image, ImageFile

import frontend.archives3 as archives
from frontend.config import configdata
import frontend.filetypes as filetypes
from frontend.utilities import (is_valid_uuid,
                                sort_order, read_from_disk,
                                ensures_endswith)
from frontend.database import (SORT_MATRIX,
                               check_for_deletes, get_db_files,
                               check_dup_thumbs)
from frontend.thumbnail import (new_process_dir, new_process_archive,
                                new_process_img)
from frontend.web import (verify_login_status, detect_mobile,
                          respond_as_attachment, g_option)

from quickbbs.models import index_data#, Thumbnails_Archives

from urllib.parse import unquote

import logging
log = logging.getLogger(__name__)

warnings.simplefilter('ignore', Image.DecompressionBombWarning)
ImageFile.LOAD_TRUNCATED_IMAGES = True
# https://stackoverflow.com/questions/12984426/
# Sending File or zipfile - https://djangosnippets.org/snippets/365/



DF_PNEXT = ["lastscan", "lastmod",
            "size", "numfiles",
            "numdirs", "parent_dir_id"]
def return_prev_next(parent_path, currentpath, sorder):
    """
    Read the parent directory, get the index of the current path,
    return the previous & next paths.

    Replace the old system, with Django pagination.
    """
    prevdir = ""
    nextdir = ""
    currentpath = currentpath.lower().strip()
#    if currentpath.lower() == (r"/%s/" % "albums").lower():
    if currentpath == (r"/%s/" % "albums"):
        return ("", "")
    url_parent = parent_path.replace(configdata["locations"]["albums_path"], "").lower()
    if url_parent == r"/albums":
        url_parent = r"/albums/"

    read_from_disk(url_parent, skippable=True)
    pagedata = index_data.objects.filter(
        fqpndirectory=url_parent,
        ignore=False,
        delete_pending=False,
        archives=None,
        file_tnail=None).exclude(directory=None).order_by(*SORT_MATRIX[sorder])

    found = None
    directories = Paginator(pagedata, 1)
    low_path = os.path.split(currentpath)[1]
    try:
        search = next(i for i, v in enumerate(directories.object_list)
                      if v.name.lower() == low_path) + 1
    except StopIteration:
        search = 1

    found = directories.page(search)
    if found.has_next():
        nextdir = pagedata[found.next_page_number()-1].name

    if found.has_previous():
        prevdir = pagedata[found.previous_page_number()-1].name

    return (prevdir, nextdir)

@vary_on_headers('User-Agent', 'Cookie', 'Request')
def thumbnails(request, t_url_name=None):
    """
    Serve the thumbnail resources

    URL -> thumbnails/(?P<t_url_name>.*)
    """
#
#    print ("Entering Thumbnails")
    t_url_name = str(t_url_name).strip().replace("/", "")
    if not is_valid_uuid(t_url_name):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")
    #e_uuid = t_url_name
    index_qs = index_data.objects.filter(uuid=t_url_name)
    if index_qs.count() > 1:
        check_dup_thumbs(t_url_name)
        index_qs = index_data.objects.filter(uuid=t_url_name)
    entry = index_qs[0]
    fs_item = os.path.join(configdata["locations"]["albums_path"],
                           entry.fqpndirectory[1:].lower(),
                           entry.name)
    fs_item = fs_item.replace("//", "/")
#    check_dup_thumbs(e_uuid)
    page = int(g_option(request, "page", 0))
    if page == "":
        page = 0
    # entry.fqpndirectory[1:] since a / in the root cancels the configdata
    # albums path

    if entry.directory:
        #print ("Directory", entry.name)
        return new_process_dir(entry)
    elif entry.archives:
        #print("is archive")
        return new_process_archive(entry, request, page)
    elif entry.file_tnail:
        return new_process_img(entry, request)

    return HttpResponseBadRequest(content="Unidentifable file.")

#@vary_on_headers('User-Agent', 'Cookie')
@vary_on_headers('User-Agent', 'Cookie', 'Request')
def new_viewgallery(request):
    """
    View the requested Gallery page
    """
    start_time = time.time()
    context = {}
    paths = {}
    context["filetypes"] = configdata["filetypes"]
    context["ftypemap"] = filetypes.ftypes
    context["small"] = g_option(request,
                                "size",
                                configdata["configuration"]["small"])
    context["medium"] = g_option(request,
                                 "size",
                                 configdata["configuration"]["medium"])
    context["large"] = g_option(request,
                                "size",
                                configdata["configuration"]["large"])
    context["user"] = request.user
    context["mobile"] = detect_mobile(request)
    request.path = request.path.lower().replace(os.sep, r"/")
#    paths["webpath"] = request.path.lower().replace(os.sep, r"/")
    paths["webpath"] = request.path

    request, context = sort_order(request, context)
    context["webpath"] = ensures_endswith(request.path, "/")
#    if not context["webpath"].endswith("/"):
#        context["webpath"] += "/"
    context["fromtimestamp"] = datetime.datetime.fromtimestamp
    paths["album_viewing"] = configdata["locations"]["albums_path"] + paths["webpath"]

    paths["fs_thumbpath"] = paths["album_viewing"].replace(r"%salbums%s" % (
        os.sep, os.sep), r"%sthumbnails%s" % (os.sep, os.sep))
    paths["thumbpath"] = paths["webpath"].replace(r"/albums/",
                                                  r"/thumbnails/")
    paths["thumbpath"] = ensures_endswith(paths["thumbpath"], "/")
    context["thumbpath"] = paths["thumbpath"]

    if not os.path.exists(paths["album_viewing"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    #elif isdir(paths["album_viewing"]):
    #
    # The only thing left is a directory.
    log.info("Reading from Disk")
    read_from_disk(paths["webpath"], skippable=True) # new_viewgallery
    index = get_db_files(context["sort_order"], paths["webpath"])
    dirs_only = index.filter(ignore=False, file_tnail=None, archives=None).exclude(directory=None)
    files_only = index.filter(ignore=False, directory=None)
    if context["sort_order"] == 0:
        dirs_only = dirs_only.order_by("sortname")
        files_only = files_only.order_by("sortname")
    else:
        dirs_only = dirs_only.order_by("lastmod", "sortname")
        files_only = files_only.order_by("lastmod", "sortname")

    index = list(chain(dirs_only, files_only))
    print(
        "after make_thumbnail fqfns, elapsed after enumerate - %s\r" %
        (time.time() - start_time))
    context["current_page"] = request.GET.get("page", 1)
    chk_list = Paginator(index, 30)
    context["page_cnt"] = list(range(1, chk_list.num_pages + 1))
    # Replace with Paginator num_pages?  Have JS count?

    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
        context["current_page"] = 1
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
#        context["all_listings"] = index
    context["prev_uri"], context["next_uri"] = return_prev_next(
        os.path.dirname(paths["album_viewing"]),
        paths["webpath"], context["sort_order"])
#        if context["prev_uri"] and not context["prev_uri"].endswith(r"/"):
#            context["prev_uri"] += r"/"
#        if context["next_uri"]© and not context["next_uri"].endswith(r"/"):
#            context["next_uri"] += r"/"
    print("\r-------------\r")
    print(
        "Gallery page, elapsed after thumbnails - %s\r" %
        (time.time() - start_time))
    print("\r-------------\r")
    response = render(request,
                      "frontend/gallery_listing.jinja",
                      context,
                      using="Jinja2")
    patch_vary_headers(response, ["sort-%s" % context["sort_order"]])
    return response

#@vary_on_headers('User-Agent', 'Cookie')
@vary_on_headers('User-Agent', 'Cookie', 'Request')
def new_viewitem(request, i_uuid):
    i_uuid = str(i_uuid).strip().replace("/", "")
    context = {}
    if not is_valid_uuid(i_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    request, context = sort_order(request, context)
    e_uuid = i_uuid
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]

    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
#    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["up_uri"] = entry.fqpndirectory.lower()
    read_from_disk(context["webpath"].strip(), skippable=True)

    catalog_qs = get_db_files(context["sort_order"], context["webpath"])
    context["page"] = 1
    for counter, data in enumerate(catalog_qs, start=1):
        if str(data.uuid) == e_uuid:
            context["page"] = counter
            break

    item_list = Paginator(catalog_qs, 1)
    context["pagecount"] = item_list.count
    context["page_contents"] = item_list.page(context["page"])
    context["item"] = entry

    if context["page_contents"].has_next():
        context["next"] = catalog_qs[context["page_contents"].next_page_number()-1].uuid
    else:
        context["next"] = ""

    if context["page_contents"].has_previous():
        context["previous"] = catalog_qs[context["page_contents"].previous_page_number()-1].uuid
    else:
        context["previous"] = ""
#
    context["first"] = catalog_qs[0].uuid
    context["last"] = catalog_qs[catalog_qs.count()-1].uuid
#        context["last"] = catalog_qs[context["page_contents"].page_range[-1]].uuid
    response = render(request,
                      "frontend/gallery_newitem.html",
                      context)#,
                      #using="Jinja2")
    patch_vary_headers(response, ["sort-%s" % context["sort_order"]])
    return response


@vary_on_headers('User-Agent', 'Cookie', 'Request')
def new_download(request, d_uuid=None):
    page = request.GET.get('page', None)
    if page is None:
        download = index_data.objects.filter(uuid=d_uuid,
                                             ignore=False,
                                             delete_pending=False)[0]
    else:
        print ("Attempting to find page %s in archive" % page)
    print("\tDownloading - %s, %s" % (download.fqpndirectory.lower(),
                                      download.name))
    return respond_as_attachment(request,
                                 "%s%s%s" % (
                                     configdata["locations"]["albums_path"],
                                     os.sep,
                                     download.fqpndirectory),
                                 download.name)

@vary_on_headers('User-Agent', 'Cookie', 'Request')
def new_view_archive(request, i_uuid):
    context = {}
    i_uuid = str(i_uuid).strip().replace("/", "")
    if not is_valid_uuid(i_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    request, context = sort_order(request, context)
    e_uuid = i_uuid
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]
    request, context = sort_order(request, context)
    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    context["webpath"] = ensures_endswith(context["webpath"], "/")
    context["fromtimestamp"] = datetime.datetime.fromtimestamp
    arc_filename = configdata["locations"]["albums_path"] +  \
        context["webpath"].replace("/", os.sep).replace("//", "/") + entry.name
    archive_file = archives.id_cfile_by_sig(arc_filename)
    archive_file.get_listings()
    context["db_entry"] = entry

    context["current_page"] = request.GET.get("page", 1)
    context["pagelist"] = Paginator(archive_file.listings, 30)
#    context["pagecount"] = context["pagelist"].count
    context["pagepop"] = range(1, context["pagelist"].num_pages+1)
    context["page_contents"] = context["pagelist"].page(context["current_page"])
    if context["page_contents"].has_next():
        context["next"] = context["page_contents"].next_page_number()
    else:
        context["next"] = ""
    if context["page_contents"].has_previous():
        context["previous"] = context["page_contents"].previous_page_number()
    else:
        context["previous"] = ""

    context["first"] = "1"
    context["last"] = context["pagelist"].num_pages


    response = render(request,
                      "frontend/archive_gallery.html",
                      context)#,
                      #using="Jinja2")
    patch_vary_headers(response, ["sort-%s" % context["sort_order"]])
    return response


#@vary_on_headers('User-Agent', 'Cookie')
@vary_on_headers('User-Agent', 'Cookie', 'Request')
def new_archive_item(request, i_uuid):
    i_uuid = str(i_uuid).strip().replace("/", "")
    context = {}
    if not is_valid_uuid(i_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    request, context = sort_order(request, context)
    e_uuid = i_uuid
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]
    item_fs = os.path.join(configdata["locations"]["albums_path"],
                           entry.fqpndirectory[1:],
                           entry.name)
    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
#        read_from_disk(context["webpath"].strip())

    context["current_page"] = int(request.GET.get("page", 0))  # 1 based not zero based
    context["page"] = context["current_page"]+1  # 1 based not zero based
#    print (context["current_page"])
    archive_file = archives.id_cfile_by_sig(item_fs)
    archive_file.get_listings()
    context["pagecount"] = len(archive_file.listings)-1
    context["item"] = entry
    item_list = Paginator(archive_file.listings, 1)
    context["page_contents"] = item_list.page(context["current_page"]+1)

    if context["page_contents"].has_next():
        context["next"] = "view_archive_item/%s?page=%s" % (
            entry.uuid, context["page_contents"].next_page_number()-1) #1 based
    else:
        context["next"] = ""

    if context["page_contents"].has_previous():
        context["previous"] = "view_archive_item/%s?page=%s" % (
            entry.uuid, context["page_contents"].previous_page_number()-1) #1 based
    else:
        context["previous"] = ""
#
    context["first"] = "view_archive_item/%s?page=%s" % (entry.uuid, 0)
    context["last"] = "view_archive_item/%s?page=%s" % (entry.uuid, context["pagecount"])

    response = render(request,
                      "frontend/archive_item.html",
                      context)#,
                      #using="Jinja2")
    patch_vary_headers(response, ["sort-%s" % context["sort_order"]])
    return response

@vary_on_headers('User-Agent', 'Cookie')
def viewarchive(request):
    """
    Serve archive files
    """
    context = {}
    paths = {}
    request, context = sort_order(request, context)
    paths["item_fs"] = configdata["locations"]["albums_path"]\
        + unquote(request.path.replace("/", os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(
        paths["item_fs"].lower())   # path to archive
    paths["thumb_path"] = paths["item_path"].replace("%salbums" % os.sep,
                                                     "%sthumbnails" % os.sep)
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["web_thumbpath"] = paths["web_path"].replace("/albums",
                                                       "/thumbnails") + r"/"
    context["current_page"] = request.GET.get("page", 1)

    if "a_item" in request.GET:
        return archive_item(request)

    archive_file = archives.id_cfile_by_sig(paths["item_fs"])
    archive_file.get_listings()
    archive_file.listings.sort()
    global_listings = archive_file.listings

    listings = []
    for count, filename in enumerate(global_listings):
        #               0,          1,          ,2
        #   Listings = filename, zip fqfn, web thumbnail path (Med & Large),

        #       3,                              4
        #   thumbnail fs path (med & large), background color

        fext = os.path.splitext(filename)[1][1:]
        if fext in configdata["filetypes"]:
            if configdata["filetypes"][fext][1].strip() != "None":
                bgcolor = configdata["filetypes"][fext][0]
            else:
                bgcolor = configdata["filetypes"]["none"][0]

        listings.append((filename,
                         paths["item_fs"],
                         paths["web_thumbpath"] + paths["item_name"],
                         paths["web_thumbpath"] + paths["item_name"],
                         bgcolor,
                         count + 1))

    context["current_page"] = request.GET.get("page", 1)
    chk_list = Paginator(listings, 30)
    context["page_cnt"] = list(range(1, chk_list.num_pages + 1))
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    context["all_listings"] = global_listings

    context["prev_uri"], context["next_uri"] = return_prev_next(
        paths["item_path"], paths["web_path"], context["sort_order"])
    context["webpath"] = paths["web_path"] + "/%s" % paths["item_name"]
    template = loader.get_template('frontend/archive_gallery.html')
    return HttpResponse(template.render(context, request))

def new_view_archive_item(request, i_uuid):
    context = {}
    if not is_valid_uuid(i_uuid.strip().replace("/", "")):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    request, context = sort_order(request, context)
    e_uuid = i_uuid.strip().replace("/", "")
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]

    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
#    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["up_uri"] = entry.fqpndirectory.lower()
    read_from_disk(context["webpath"].strip(), skippable=True)

    index_qs = get_db_files(context["sort_order"], context["webpath"]).filter(uuid=e_uuid)
#    arc_qs = Thumbnails_Archives.objects.filter()
    context["page"] = 1
    for counter, data in enumerate(index_qs, start=1):
        if str(data.uuid) == e_uuid:
            context["page"] = counter
            break

    item_list = Paginator(index_qs, 1)
    context["pagecount"] = item_list.count
    context["page_contents"] = item_list.page(context["page"])
    context["item"] = entry

    if context["page_contents"].has_next():
        context["next"] = index_qs[context["page_contents"].next_page_number()-1].uuid
    else:
        context["next"] = ""

    if context["page_contents"].has_previous():
        context["previous"] = index_qs[context["page_contents"].previous_page_number()-1].uuid
    else:
        context["previous"] = ""
#
    context["first"] = index_qs[0].uuid
    context["last"] = index_qs[index_qs.count()-1].uuid
#        context["last"] = catalog_qs[context["page_contents"].page_range[-1]].uuid
    response = render(request,
                      "frontend/archive_item.html",
                      context)#,
                      #using="Jinja2")
    patch_vary_headers(response, ["sort-%s" % context["sort_order"]])
    return response

@vary_on_headers('User-Agent', 'Cookie')
def archive_item(request):
    """
    Serve the gallery items
    """
    context = {}
    paths = {}
    context["mobile"] = detect_mobile(request)
    request, context = sort_order(request, context)
    context["small"] = g_option(request,
                                "size",
                                configdata["configuration"]["small"])
    context["medium"] = g_option(request,
                                 "size",
                                 configdata["configuration"]["medium"])
    context["large"] = g_option(request,
                                "size",
                                configdata["configuration"]["large"])
    paths["archive_item"] = int(g_option(request, "a_item", 1)) - 1
    paths["item_fs"] = configdata["locations"]["albums_path"]\
        + unquote(request.path.replace("/",
                                       os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(
        paths["item_fs"].lower())
    paths["thumb_path"] = paths["item_path"].replace("%salbums" % os.sep,
                                                     "%sthumbnails" % os.sep)
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["web_thumbpath"] = paths["web_path"].replace("/albums",
                                                       "/thumbnails") + r"/"


    archive_file = archives.id_cfile_by_sig(paths["item_fs"])
    archive_file.get_listings()
    archive_file.listings.sort()
    global_listings = archive_file.listings

    listings = []
    for count, filename in enumerate(global_listings):
        #               0,          1,          ,2
        #   Listings = filename, zip fqfn, web thumbnail path (Med & Large),

        #       3,                              4
        #   thumbnail fs path (med & large), background color
        fext = os.path.splitext(filename)[1][1:]
        if fext in configdata["filetypes"]:
            if configdata["filetypes"][fext][1] != "None":
                bgcolor = configdata["filetypes"][fext][0]
            else:
                bgcolor = configdata["filetypes"]["none"][0]

        listings.append((filename,
                         paths["item_fs"],
                         paths["web_thumbpath"] + paths["item_name"],
                         paths["web_thumbpath"] + paths["item_name"],
                         bgcolor,
                         count + 1))

    context["current_page"] = request.GET.get("page", 1)

    context["current_page"] = request.GET.get("a_item")
    chk_list = Paginator(listings, 1)
    context["page_cnt"] = list(range(1, chk_list.num_pages + 1))
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    try:
        context["pagelist"] = chk_list.page(context["current_page"])
    except PageNotAnInteger:
        context["pagelist"] = chk_list.page(1)
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    context["all_listings"] = global_listings

    context["prev_uri"], context["next_uri"] = return_prev_next(
        paths["item_path"], paths["web_path"], context["sort_order"])
    context["webpath"] = paths["web_path"] + "/%s" % paths["item_name"]
    template = loader.get_template('frontend/archive_item.html')
    return HttpResponse(template.render(context, request))


if 'runserver' in sys.argv:
    print("Starting cleanup")
    check_for_deletes()
    print("Cleanup is done.")
#    for prepath in configdata["locations"]["preload"]:
#        print("Pre-Caching: ", prepath)
#        read_from_disk(prepath.strip()) # startup

#         for ignored in configdata["filetypes"]["files_to_ignore"]:
#             test = index_data.objects.filter(name__iexact=ignored.title())
#             if test:
#                 print("%s - %s" % (ignored, test.count()))
#                 test.delete()
