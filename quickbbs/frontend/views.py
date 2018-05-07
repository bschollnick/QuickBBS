# coding: utf-8
"""
Django views for QuickBBS Gallery
"""
from __future__ import absolute_import, print_function, unicode_literals

import datetime
import os
import os.path
import sys
import time
import warnings
#from os.path import isdir, isfile

#import fitz
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import (HttpResponse, HttpResponseNotFound,
                         HttpResponseBadRequest)
from django.shortcuts import render
from django.template import loader
from django.utils.cache import patch_vary_headers
from django.views.decorators.vary import vary_on_headers
from PIL import Image, ImageFile

import frontend.archives3 as archives
from frontend.config import configdata as configdata
from frontend.utilities import (is_valid_uuid,#test_extension, is_archive,
                                sort_order, read_from_disk, PY2,
                                ensures_endswith)
from frontend.database import (get_filtered, SORT_MATRIX,
                               check_for_deletes, get_db_files,
                               check_dup_thumbs)
from frontend.thumbnail import (new_process_dir, new_process_archive,
                                new_process_img)
from frontend.web import (verify_login_status, detect_mobile,
                          respond_as_attachment, g_option)

from quickbbs.models import index_data

if PY2:
    from exceptions import IOError
    from urllib import unquote
    range = xrange
else:
    from urllib.parse import unquote

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
    if currentpath.lower() == (r"/%s/" % "albums").lower():
        return ("", "")
    url_parent = parent_path.replace(configdata["locations"]["albums_path"], "")
    if url_parent == r"/albums":
        url_parent = url_parent + "/"

#    pagedata = index_data.objects.filter(*DF_PNEXT)
    pagedata = get_filtered(index_data.objects,
                            {'fqpndirectory':url_parent.lower(),
                             'is_dir':True,
                             'ignore':False,
                             'delete_pending':False}).order_by(
                                 *SORT_MATRIX[sorder])

    found = None
    directories = Paginator(pagedata, 1)
    low_path = os.path.split(currentpath)[1].lower().strip()
    try:
        search = next(i for i, v in enumerate(directories.object_list)
                      if v.name.lower() == low_path) + 1
    except StopIteration:
        search = 1

    found = directories.page(search)
    if found.has_next():
        nextdir = pagedata[found.next_page_number()-1].name
    else:
        nextdir = ""

    if found.has_previous():
        prevdir = pagedata[found.previous_page_number()-1].name
    else:
        prevdir = ""

    return (prevdir, nextdir)

@vary_on_headers('User-Agent', 'Cookie', 'Request')
def thumbnails(request, t_url_name=None):
    """
    Serve the thumbnail resources

    URL -> thumbnails/(?P<t_url_name>.*)
    """
#
    if not is_valid_uuid(t_url_name.strip().replace("/", "")):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")
    e_uuid = t_url_name.strip().replace("/", "")
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]
    fs_item = os.path.join(configdata["locations"]["albums_path"],
                           entry.fqpndirectory[1:].lower(),
                           entry.name)
    fs_item = fs_item.replace("//", "/")
    check_dup_thumbs(e_uuid)
    page = int(g_option(request, "page", 0))
    if page == "":
        page = 0
    # entry.fqpndirectory[1:] since a / in the root cancels the configdata
    # albums path

    if entry.directory:
        print ("Directory")
        return new_process_dir(entry)
    elif entry.archives:
        print("is archive")
        return new_process_archive(entry, request, page)
    elif entry.file_tnail:
        print ("file_tnail")
        return new_process_img(entry, request)
    else:
        HttpResponseBadRequest(content="Unidentifable file.")

@vary_on_headers('User-Agent', 'Cookie')
def new_viewgallery(request):
    """
    View the requested Gallery page
    """
    start_time = time.time()
    context = {}
    paths = {}
    context["filetypes"] = configdata["filetypes"]
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
    paths["webpath"] = request.path.lower().replace(os.sep, r"/")
    request, context = sort_order(request, context)
    context["webpath"] = ensures_endswith(request.path.lower(), "/")
#    if not context["webpath"].endswith("/"):
#        context["webpath"] += "/"
    context["fromtimestamp"] = datetime.datetime.fromtimestamp
    paths["album_viewing"] = configdata["locations"]["albums_path"] +  \
        paths["webpath"].replace("/", os.sep).replace("//", "/")
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
    read_from_disk(paths["album_viewing"]) # new_viewgallery

    index = get_db_files(context["sort_order"], paths["webpath"])

    print(
        "after make_thumbnail fqfns, elapsed after enumerate - %s\r" %
        (time.time() - start_time))
    context["current_page"] = request.GET.get("page")
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
    print("Album Viewing - ", os.path.dirname(paths["album_viewing"]))
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

@vary_on_headers('User-Agent', 'Cookie')
def new_viewitem(request, i_uuid):
    context = {}
    if not is_valid_uuid(i_uuid.strip().replace("/", "")):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    request, context = sort_order(request, context)
    e_uuid = i_uuid.strip().replace("/", "")
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]
#        size = g_option(request, "size",
#                        configdata["configuration"]["large"])

    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    read_from_disk(context["webpath"].strip())

    catalog_qs = get_db_files(context["sort_order"], context["webpath"])
    context["page"] = 1
    for counter, data in enumerate(catalog_qs, start=1):
        if str(data.uuid) == e_uuid:
            context["page"] = counter
            break

#        print ("page is %s" % context["page"])
#        for counter, x in enumerate(catalog_qs):
#            print (counter, " ", x.uuid, "  ", x.name, "  ", x.lastmod)
    item_list = Paginator(catalog_qs, 1)
    context["pagecount"] = item_list.count
#        print ("# pages", item_list.num_pages)
    context["page_contents"] = item_list.page(context["page"])
    context["item"] = entry

#        print (context["page_contents"])
    #context["item"] = catalog[context["page"]-1]
#        print ("next: ",context["page_contents"].has_next())
#        print ("prev: ",context["page_contents"].has_previous())
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


# @vary_on_headers('User-Agent', 'Cookie')
# def galleryitem(request, viewitem):
#     """
#     Serve the gallery items
#     """
#     context = {}
#     paths = {}
#     paths["webpath"] = request.path.lower()
#     context["mobile"] = detect_mobile(request)
#     paths["thumbpath"] = paths["webpath"].replace(r"/albums/",
#                                                   r"/thumbnails/")
#     context["small"] = g_option(request,
#                                 "size",
#                                 configdata["configuration"]["small"])
#     context["medium"] = g_option(request,
#                                  "size",
#                                  configdata["configuration"]["medium"])
#     context["large"] = g_option(request,
#                                 "size",
#                                 configdata["configuration"]["large"])
#     request, context = sort_order(request, context)
#     paths["item_fs"] = configdata["locations"]["albums_path"]\
#         + unquote(request.path.replace("/", os.sep))
#     paths["item_fs"] = paths["item_fs"].replace("//", "/")
#     paths["item_path"], paths["item_name"] = os.path.split(
#         paths["item_fs"].lower())
#     paths["web_path"] = paths["item_path"].replace(
#         configdata["locations"]["albums_path"].lower(), "")
#     paths["thumb_path"] = paths["web_path"].replace("%salbums" % os.sep,
#                                                     "%sthumbnails" % os.sep)
#     if not os.path.exists(paths["item_fs"]):
#         #
#         #   Albums doesn't exist
#         return HttpResponseNotFound('<h1>Page not found</h1>')
#
#     read_from_disk(paths["web_path"].strip()) # gallery_item
#
#     if not os.path.exists(paths["item_path"].strip()):
#         #
#         #   Albums doesn't exist
#         return HttpResponseNotFound('<h1>Page not found</h1>')
#
#     index = get_db_files(context["sort_order"], paths["web_path"])
#
#     chk_list = Paginator(index, 1)
#     try:
#         context["page"] = int(request.GET.get("page"))
#         context["pagelist"] = chk_list.page(context["page"])
#         context["item"] = index[context["page"]-1]
#         context["gallery_name"] = os.path.split(request.path_info)[-1]
#         context["current_page"] = context["page"]
# #        print("Integer")
#     except (TypeError, PageNotAnInteger):
# #        print("Not an Integer")
#         litem_name = paths["item_name"].strip().lower()
#         for count, entry in enumerate(index, start=1):
#             if entry.name.lower().strip() == litem_name:
#                 context["page"] = count
#                 context["pagelist"] = chk_list.page(context["page"])
#                 context["item"] = index[context["page"]-1]
#                 break
#     except EmptyPage:
# #        print("Empty Page")
#         context["pagelist"] = chk_list.page(chk_list.num_pages)
#         context["page"] = chk_list.num_pages
#
#
#     context["last_mod"] = datetime.datetime.fromtimestamp(
#         context["item"].lastmod).strftime("%m-%d-%Y %H:%M")
#
#     context["thumb_path"] = paths["thumb_path"]
#     context["web_path"] = paths["web_path"]
#     context["gallery_name"] = os.path.split(request.path_info)[-1]
#     context["current_page"] = context["page"]
#     #context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
#     context["up_uri"] = context["item"].fqpndirectory
#
#     response = render(request,
#                       "frontend/gallery_item.html",
#                       context)#,
#                       #using="Jinja2")
#     patch_vary_headers(response, ["sort-%s" % context["sort_order"]])
#     return response


def new_download(request, d_uuid=None):

    download = index_data.objects.filter(uuid=d_uuid,
                                         ignore=False,
                                         delete_pending=False)[0]

    print("\tDownloading - %s, %s" % (download.fqpndirectory.lower(),
                                      download.name))
    return respond_as_attachment(request,
                                 "%s%s%s" % (
                                     configdata["locations"]["albums_path"],
                                     os.sep,
                                     download.fqpndirectory),
                                 download.name)

@vary_on_headers('User-Agent', 'Cookie')
def new_view_archive(request, i_uuid):
    context = {}
    if not is_valid_uuid(i_uuid.strip().replace("/", "")):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    request, context = sort_order(request, context)
    e_uuid = i_uuid.strip().replace("/", "")
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]

    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
#        read_from_disk(context["webpath"].strip())

    context["current_page"] = request.GET.get("page")
    if context["current_page"] is None:
        context["current_page"] = 1

    response = render(request,
                      "frontend/archive_gallery.html",
                      context)#,
                      #using="Jinja2")
    patch_vary_headers(response, ["sort-%s" % context["sort_order"]])
    return response


@vary_on_headers('User-Agent', 'Cookie')
def new_archive_item(request, i_uuid):
    context = {}
    if not is_valid_uuid(i_uuid.strip().replace("/", "")):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

    request, context = sort_order(request, context)
    e_uuid = i_uuid.strip().replace("/", "")
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]

    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
#        read_from_disk(context["webpath"].strip())

    context["current_page"] = request.GET.get("page")
    if context["current_page"] is None:
        context["current_page"] = 1

    response = render(request,
                      "frontend/gallery_item.html",
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
    context["current_page"] = request.GET.get("page")
    if context["current_page"] is None:
        context["current_page"] = 1

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

    context["current_page"] = request.GET.get("page")
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
#    context["last_mod"] = datetime.datetime.fromtimestamp(
        #context["item"].lastmod).strftime("%m-%d-%Y %H:%M")

    context["prev_uri"], context["next_uri"] = return_prev_next(
        paths["item_path"], paths["web_path"], context["sort_order"])
    context["webpath"] = paths["web_path"] + "/%s" % paths["item_name"]
    template = loader.get_template('frontend/archive_gallery.html')
    return HttpResponse(template.render(context, request))

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

    context["current_page"] = request.GET.get("page")

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
    for prepath in configdata["locations"]["preload"]:
        print("Pre-Caching: ", prepath)
        read_from_disk(prepath.strip()) # startup

#         for ignored in configdata["filetypes"]["files_to_ignore"]:
#             test = index_data.objects.filter(name__iexact=ignored.title())
#             if test:
#                 print("%s - %s" % (ignored, test.count()))
#                 test.delete()
