# coding: utf-8
"""
Django views for QuickBBS Gallery
"""
from __future__ import absolute_import, print_function, unicode_literals
import quickbbs.settings
if quickbbs.settings.SILK:
    from silk.profiling.profiler import silk_profile
#else:
#    from frontend.utilities import silk_profile

import datetime
from itertools import chain
import os
import os.path
from pathlib import Path
import sys
import time
import uuid
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
import frontend.ftypes as ftypes
#from frontend.constants import *
import frontend.constants as constants

from frontend.utilities import (is_valid_uuid,
                                sort_order,
                                read_from_disk,
                                ensures_endswith, test_extension)
from frontend.database import (SORT_MATRIX,
                               check_for_deletes, get_db_files,
                               check_dup_thumbs)
from frontend.thumbnail import (new_process_dir, new_process_archive,
                                new_process_img)
from frontend.web import (verify_login_status, detect_mobile,
                          respond_as_attachment, respond_as_inline, g_option)

from quickbbs.models import index_data, Thumbnails_Dirs, Thumbnails_Files#, Thumbnails_Archives

from urllib.parse import unquote
import django_icons.templatetags.icons
import bleach

import logging
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
    Parent_path = Path(fqpn).parent
    current_folder_name = os.path.basename(Path(fqpn)).lower()
    prevdir = ""
    nextdir = ""
    currentpath = currentpath.lower().strip()
    if currentpath == (r"/albums/"):
        return ("", "")
    url_parent = fqpn.replace(configdata["locations"]["albums_path"], "").lower()
    url_parent = os.path.split(url_parent)[0]
#    print("parentPath - ",Parent_path.as_posix())
#    print ("currentpath - ",currentpath)
#    print("url_parent - ", url_parent)
    read_from_disk(url_parent, skippable=True)
#    print (*SORT_MATRIX[sorder])
    index = get_db_files(sorder, url_parent)#.order_by("lastmod")
    #dirs_only = index.filter(ignore=False, file_tnail=None, archives=None).exclude(is_dir=False)
    dirs_only = index.filter(ignore=False, filetype__is_dir=True)#file_tnail=None, archives=None).exclude(is_dir=False)
    found = None
    directories = Paginator(dirs_only, 1)
    low_path = current_folder_name
    try:
        search = next(i for i, v in enumerate(directories.object_list)
                      if v.name.lower() == low_path) + 1
    except StopIteration:
        search = 1
    found = directories.page(search)
    if found.has_next():
        nextdir = dirs_only[found.next_page_number()-1].name

    if found.has_previous():
        prevdir = dirs_only[found.previous_page_number()-1].name

    return (prevdir, nextdir)

@vary_on_headers('User-Agent', 'Cookie', 'Request')
#@silk_profile(name='views.thumbnails')
def thumbnails(request, t_url_name=None):
    """
    Serve the thumbnail resources

    URL -> thumbnails/(?P<t_url_name>.*)
    """
#
    t_url_name = str(t_url_name).strip().replace("/", "")
    if is_valid_uuid(t_url_name):
        index_qs = index_data.objects.filter(uuid=t_url_name,
                                             ignore=False, delete_pending=False)
        if index_qs.count() > 1:
            check_dup_thumbs(t_url_name)
            index_qs = index_data.objects.filter(uuid=t_url_name)
        entry = index_qs[0]

        fs_item = os.path.join(configdata["locations"]["albums_path"],
                               entry.fqpndirectory[1:].lower(),
                               entry.name)

        fqpn = fs_item #(configdata["locations"]["albums_path"] + dir_to_scan).replace("//", "/")
        webpath = os.path.join(configdata["locations"]["albums_path"],
                               entry.fqpndirectory[1:].lower())

        fs_name = os.path.join(configdata["locations"]["albums_path"],
                               entry.fqpndirectory[1:],
                               entry.name)
        fname = os.path.basename(fs_name).title()
        if entry.filetype.is_dir:
            if entry.directory == None:
                entry.directory = Thumbnails_Dirs.objects.update_or_create(
                    uuid=entry.uuid, FilePath=webpath, DirName=fname,
                    defaults={"uuid":entry.uuid,
                              "FilePath":webpath,
                              "DirName":fname})[0]
                entry.save()
            return new_process_dir(entry)
        elif entry.filetype.is_pdf or entry.filetype.is_image:
            if entry.file_tnail == None:
                entry.file_tnail = Thumbnails_Files.objects.update_or_create(
                    uuid=entry.uuid,
                    FilePath=webpath,
                    FileName=fname,
                    defaults={"uuid":entry.uuid,
                              "FilePath":webpath,
                              "FileName":fname,
                              })[0]
                entry.save()
            return new_process_img(entry, request)
        elif entry.archives:
            page = int(g_option(request, "page", 0))
            return new_process_archive(entry, request, page)

    return HttpResponseBadRequest(content="Bad UUID or %s Unidentifable file." % fs_item)

@vary_on_headers('User-Agent', 'Cookie', 'Request')
#@silk_profile(name='View new_Viewgallery')
def new_viewgallery(request):
    """
    View the requested Gallery page
    """
   # start_time = time.time()
    context = {}
    paths = {}
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
    paths["webpath"] = ensures_endswith(request.path, "/")

    request, context = sort_order(request, context)
    context["webpath"] = paths["webpath"]
    context["fromtimestamp"] = datetime.datetime.fromtimestamp
    paths["album_viewing"] = configdata["locations"]["albums_path"] + paths["webpath"]

    paths["fs_thumbpath"] = paths["album_viewing"].replace(r"%salbums%s" % (
        os.sep, os.sep), r"%sthumbnails%s" % (os.sep, os.sep))
    paths["thumbpath"] = paths["webpath"].replace(r"/albums/",
                                                  r"/thumbnails/")
    paths["thumbpath"] = ensures_endswith(paths["thumbpath"], "/")
    context["thumbpath"] = paths["thumbpath"]
#    print(context["sort"])
    if not os.path.exists(paths["album_viewing"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    #elif isdir(paths["album_viewing"]):
    #
    # The only thing left is a directory.
    read_from_disk(paths["webpath"], skippable=True) # new_viewgallery
    index = get_db_files(context["sort"], paths["webpath"])

#    index = list(index.order_by(*SORT_MATRIX[context["sort"]]))
#   already sorted by get_db_files call.

    context["current_page"] = request.GET.get("page", 1)
    chk_list = Paginator(index, 30)
    context["page_cnt"] = list(range(1, chk_list.num_pages + 1))

    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
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
    patch_vary_headers(response, ["sort-%s" % context["sort"]])
    return response

#@vary_on_headers('User-Agent', 'Cookie')
@vary_on_headers('User-Agent', 'Cookie', 'Request')
#@silk_profile(name='View new_Viewitem')
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
    if entry.filetype.fileext == ".html":
        html_filename = configdata["locations"]["albums_path"] +  \
            context["webpath"].replace("/", os.sep).replace("//", "/") + entry.name
        context["html"] = bleach.linkify("\n".join(open(html_filename).readlines()))
#    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    context["up_uri"] = entry.fqpndirectory.lower()
    read_from_disk(context["webpath"].strip(), skippable=True)
    catalog_qs = get_db_files(context["sort"], context["webpath"])
    context["page"] = 1
    for counter, data in enumerate(catalog_qs, start=1):
        if str(data.uuid) == e_uuid:
            context["page"] = counter
            break

    item_list = Paginator(catalog_qs, 1)
    context["pagecount"] = item_list.count
    context["page_contents"] = item_list.page(context["page"])
    context["item"] = entry
    #print(entry.filetype.is_movie)
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
    patch_vary_headers(response, ["sort-%s" % context["sort"]])
    return response


@vary_on_headers('User-Agent', 'Cookie', 'Request')
#@silk_profile(name='View new_download')
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
    return respond_as_inline(request,
                                 "%s%s%s" % (
                                     configdata["locations"]["albums_path"],
                                     os.sep,
                                     download.fqpndirectory),
                                 download.name)
#    return respond_as_attachment(request,
#                                 "%s%s%s" % (
#                                     configdata["locations"]["albums_path"],
#                                     os.sep,
#                                     download.fqpndirectory),
#                                 download.name)


@vary_on_headers('User-Agent', 'Cookie', 'Request')
#@silk_profile(name='View new_view_archive')
def new_view_archive(request, i_uuid):
    context = {}
    i_uuid = str(i_uuid).strip().replace("/", "")
    if not is_valid_uuid(i_uuid):
        return HttpResponseBadRequest(content="Non-UUID thumbnail request.")

#    request, context = sort_order(request, context)
    e_uuid = i_uuid
    index_qs = index_data.objects.filter(uuid=e_uuid)
    entry = index_qs[0]
    request, context = sort_order(request, context)
    context["next"] = ""
    context["previous"] = ""
    context["webpath"] = entry.fqpndirectory.lower().replace("//", "/")
    context["webpath"] = ensures_endswith(context["webpath"], "/")
    context["fromtimestamp"] = datetime.datetime.fromtimestamp
    context["djicons"] = django_icons.templatetags.icons.icon
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
    if context["page_contents"].has_previous():
        context["previous"] = context["page_contents"].previous_page_number()

    context["first"] = "1"
    context["last"] = context["pagelist"].num_pages


    response = render(request,
                      "frontend/archive_gallery.html",
                      context)#,
                      #using="Jinja2")
    patch_vary_headers(response, ["sort-%s" % context["sort"]])
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
#    context["pagecount"] = archive_file.listings.count()-1
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
    patch_vary_headers(response, ["sort-%s" % context["sort"]])
    return response



if 'runserver' in sys.argv:
    print("Starting cleanup")
    check_for_deletes()
    print("Cleanup is done.")
    try:
        ftypes.refresh_filetypes()
        ftypes.FILETYPE_DATA = ftypes.get_ftype_dict()
        for prepath in configdata["locations"]["preload"]:
            print("Pre-Caching: ", prepath)
            read_from_disk(prepath.strip()) # startup

            for ignored in configdata["filetypes"]["files_to_ignore"]:
                test = index_data.objects.filter(name__iexact=ignored.title())
                if test:
                    print("%s - %s" % (ignored, test.count()))
                    test.delete()
    except:
        pass
