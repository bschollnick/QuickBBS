# coding: utf-8
"""
Django views for QuickBBS Gallery
"""
# from django.shortcuts import render
from __future__ import absolute_import, print_function
from __future__ import unicode_literals

import datetime
import os
import os.path
from os.path import isdir, isfile
import re
import stat
import sys
import time
import warnings
from io import BytesIO
import mimetypes
import uuid

import fitz
import scandir
from django.http import HttpResponse
from wsgiref.util import FileWrapper
from django.contrib.auth import authenticate, login
from django.core.exceptions import MultipleObjectsReturned
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import HttpResponse, HttpResponseNotFound
from django.shortcuts import render
from django.template import loader
from django.utils.cache import patch_vary_headers
from django.views.decorators.vary import vary_on_headers
from django.views.static import serve
from django.http import StreamingHttpResponse
from PIL import Image, ImageFile

import frontend.archives3 as archives
from frontend.config import configdata as configdata
from quickbbs.models import *

PY2 = sys.version_info[0] < 3

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


def is_archive(fqfn):
    # None = not an archive.
    """
    Is it an archive?
    """
#    return is_file(fqfn) and test_extension(fqfn,
    return isfile(fqfn) and test_extension(fqfn,
                                           ['cbz',
                                            'cbr',
                                            'zip',
                                            'rar'])

def verify_login_status(request, force_login=False):
    """
    Verify login status
    """
    username = request.POST['username']
    password = request.POST['password']
    user = authenticate(username=username, password=password)
    if user is not None:
        if user.is_active:
            login(request, user)
            # Redirect to a success page.
        else:
            print("disabled account")
            # Return a 'disabled account' error message
    else:
        print("Invalid login")
        # Return an 'invalid login' error message.


def g_option(request, option_name, def_value):
    """
    Return the option from the request.get?
    """
    return request.GET.get(option_name, def_value)


def sort_order(request, context):
    """
    Return the query'd sort order from the web page
    """
    if "sort" in request.GET:
        #   Set sort_order, since there is a value in the post
        # pylint: disable=E1101
        request.session["sort_order"] = int(request.GET["sort"], 0)
        context["sort_order"] = int(request.GET["sort"], 0)
# pylint: enable=E1101
    else:
        context["sort_order"] = request.session.get("sort_order", 0)
    return request, context


def detect_mobile(request):
    """
    Is this a mobile browser?
    """
    return "Mobile" in request.META["HTTP_USER_AGENT"]

sort_matrix = {0:["-is_dir", "sortname"],
               1:["-is_dir", "lastmod"],
               2:["-is_dir", "sortname"]}

def get_values(database, values):
    #https://stackoverflow.com/questions/5903384
    return database.objects.values(*values)

def get_defered(database, defers):
    #https://stackoverflow.com/questions/5903384
    return database.objects.defer(*defers)

def get_filtered(queryset, filtervalues):
    #https://stackoverflow.com/questions/5903384
    return queryset.filter(**filtervalues)

def get_db_files(sorder, fpath):
    index = index_data.objects.filter(fqpndirectory=fpath,
                                      ignore=False).order_by(*sort_matrix[sorder])
    return index


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

    pagedata = get_defered(index_data, DF_PNEXT)
    pagedata = get_filtered(pagedata,
                            {'fqpndirectory':url_parent,#url_parent,
                             'is_dir':True,
#                             'is_image':False,
                             'ignore':False,
                             'delete_pending':False}).order_by(*sort_matrix[sorder])

    found = None
    directories = Paginator(pagedata, 1)
    low_path = os.path.split(currentpath)[1].lower().strip()
    try:
        search = next(i for i, v in enumerate(directories.object_list) if v.name.lower() == low_path) + 1
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


def check_for_deletes():
    """
    Check to see if any deleted items exist, if so, delete them.
    """
    deleted = index_data.objects.filter(delete_pending=True)
    if deleted.exists():
        print ("Deleting old deleted records")
        deleted.delete()


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
    context["webpath"] = request.path.lower()
    context["fromtimestamp"] = datetime.datetime.fromtimestamp
    paths["album_viewing"] = configdata["locations"]["albums_path"] +  \
        paths["webpath"].replace("/", os.sep)
    paths["fs_thumbpath"] = paths["album_viewing"].replace(r"%salbums%s" % (
        os.sep, os.sep), r"%sthumbnails%s" % (os.sep, os.sep))
    paths["thumbpath"] = paths["webpath"].replace(r"/albums/",
                                                  r"/thumbnails/")
    context["thumbpath"] = paths["webpath"].replace(r"/albums/",
                                                    r"/thumbnails/")
    if not paths["thumbpath"].endswith("/"):
        paths["thumbpath"] += "/"
    if not os.path.exists(paths["album_viewing"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')
    elif is_archive(paths["album_viewing"]):
        return viewarchive(request)
    elif isfile(paths["album_viewing"]):
        return galleryitem(request, paths["album_viewing"])
    elif isdir(paths["album_viewing"]):
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
        print ("Album Viewing - ", os.path.dirname(paths["album_viewing"]))
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

def thumbnails(request, t_url_name=None):
    """
    Serve the thumbnail resources

    URL -> thumbnails/(?P<t_url_name>.*)
    """

    sizes = {
        "small":configdata["configuration"]["small"],
        "medium":configdata["configuration"]["medium"],
        "large":configdata["configuration"]["large"],
        "unknown":configdata["configuration"]["small"]
    }

    V_DIRS = ["size", "fqpndirectory", "name", "is_dir", "ignore", "is_image"]
    def process_dir(fs_path):
        """
        input:
            fs_path - File System path of the directory in question

        Read directory, and identify the first thumbnailable file.
        Make thumbnail of that file
        Return thumbnail results

        Since we are just looking for a thumbnailable image, it doesn't have
        to be the most up to date, nor the most current.  Cached is fine.

        As long as it exists.
        """
        #
        #   webpath contains the URL equivalent to the file system path (fs_path)
        #
        webpath = fs_path.replace(configdata["locations"]["albums_path"], "")
        files = None
#        try:
        #   What files exist in this directory?
        files = None
#        try:
        #   What files exist in this directory?
        if not get_filtered(get_values(index_data, V_DIRS),
                            {'fqpndirectory':webpath, 'is_dir':False,
                             'ignore':False, 'delete_pending':False}):
            # No files exist in the database for this directory
            print ("* No files exist, %s" % fs_path)
            read_from_disk(fs_path) # process_dir
        files = get_filtered(get_values(index_data, V_DIRS),
                             {'fqpndirectory':webpath, 'is_dir':False,
                              'ignore':False, 'delete_pending':False,
                              'is_image':True, 'is_archive':False})
        thumbdata = get_filtered(Thumbnails_Dirs.objects, {'FilePath':webpath})
        if not thumbdata:
            #
            #   There is no Thumbnail data for this Directory
            #   So we Create a new entry
            new_entry = Thumbnails_Dirs.objects.create(SmallThumb=b"",
                                                       FilePath=webpath)
            thumbdata = new_entry
        else:
            thumbdata = thumbdata[0]


        if files:
            files = files[0]

#            if files:
            fext = os.path.splitext(files["name"])[1][1:].lower()

            if fext in configdata["filetypes"]:
                if configdata["filetypes"][fext][1].strip() != "None":
                    fs_path = os.path.join(
                        configdata["locations"]["resources_path"],
                        "images", configdata["filetypes"][fext][1])


            thumbfilename = configdata["locations"]["albums_path"]+\
                    os.path.join(files["fqpndirectory"], files["name"])

#            if thumbdata.FileSize == -1 or
#                    thumbdata.FileSize != os.path.getsize(thumbfilename)):
            if thumbdata.FileSize != os.path.getsize(thumbfilename):
               #
                #   The cached data is invalidated since the filesize is inaccurate
                #   Reset the existing thumbnails to ensure that they will be
                #   regenerated
                #
                thumbdata.SmallThumb = b""
                thumbdata.MediumThumb = b""
                thumbdata.LargeThumb = b""
                thumbdata.FileSize = os.path.getsize(thumbfilename)
                thumbdata.save()

            if not thumbdata.SmallThumb:# and files:
                temp = return_image_obj(thumbfilename)
                thumbdata.SmallThumb = cr_tnail_img(temp,
                                                    sizes["small"],
                                                    fext=fext)
                thumbdata.save()
#                thumbdata.save()
        else:
#        if thumbdata.SmallThumb == b"":
            temp = return_image_obj(configdata["locations"]["images_path"]+\
                os.sep + configdata["filetypes"]["dir"][1])
            thumbdata.SmallThumb = cr_tnail_img(
                temp, sizes["small"], configdata["filetypes"]["dir"][2])

        response = HttpResponse()
        response.write(thumbdata.SmallThumb)
        response['Content-Disposition'] = \
            'attachment; filename={0}'.format(os.path.basename(fs_path))
        return response


    def process_archive(fs_path, thumb_size, request, context, mode=""):
        """
        Process an archive, and return the thumbnail
        """
#        compressed_file = configdata["locations"]["resources_path"] + \
#            os.sep + "images" + os.sep + "1431973824_compressed.png"

        source_folder, arch_filename = os.path.split(fs_path.lower().strip())

        archive_file = archives.id_cfile_by_sig(fs_path)
        page = int(g_option(request, "arch", 0))
        if page == "":
            page = 0
        archive_file.get_listings()
        fn_to_extract = archive_file.listings[page]
        data = archive_file.extract_mem_file(fn_to_extract)
        thumbdata = Thumbnails_Archives.objects.filter(
            FilePath=source_folder,
            FileName=arch_filename,
            page=page)
        if not thumbdata:
            #
            #   There is no Thumbnail data for this file
            #
            new_entry = Thumbnails_Archives.objects.create(SmallThumb=b"",
                                                           MediumThumb=b"",
                                                           LargeThumb=b"",
                                                           FilePath=source_folder,
                                                           FileName=arch_filename,
                                                           FileSize=-1,
                                                           page=0)
            thumbdata = new_entry
        else:
            thumbdata = thumbdata[0]

        if (thumbdata.FileSize == -1 or
                thumbdata.FileSize != os.path.getsize(fs_path)):
            #
            #   The cached data is invalidated since the filesize is inaccurate
            #   Reset the existing thumbnails to ensure that they will be
            #   regenerated
            #
            thumbdata.SmallThumb = b""
            thumbdata.MediumThumb = b""
            thumbdata.LargeThumb = b""
            thumbdata.FileSize = os.path.getsize(fs_path)
#            thumbdata.save()
            #
            #  Clear the django cache here

        fext = os.path.splitext(archive_file.listings[page])[1][1:].lower()
                                       # ".pdf_png_preview")

        if fext in configdata["filetypes"]:
            if configdata["filetypes"][fext][1].strip() != "None":
                fs_path = os.path.join(
                    configdata["locations"]["resources_path"],
                    "images",
                    configdata["filetypes"][fext][1])

        response = HttpResponse()
        thumbsize = thumb_size.lower().strip()
        if thumbsize == "large":
            if not thumbdata.LargeThumb:
                try:
                    im_data = return_image_obj(data, memory=True)
                except IOError:
                    im_data = return_image_obj(os.path.join(
                        configdata["locations"]["resources_path"],
                        "images", configdata["filetypes"]["archive"][1]), memory=True)

                thumbdata.LargeThumb = cr_tnail_img(im_data,
                                                    sizes[thumbsize],
                                                    fext=fext)
                thumbdata.save()
            response.write(thumbdata.LargeThumb)
        elif thumbsize == "medium":
            if not thumbdata.MediumThumb:
#                print ("Creating Med Thumb for %s" % os.path.basename(fs_path))
                try:
                    im_data = return_image_obj(data, memory=True)
                except IOError:
                    im_data = return_image_obj(os.path.join(
                        configdata["locations"]["resources_path"],
                        "images",
                        configdata["filetypes"]["archive"][1]),
                                               memory=True)
                thumbdata.MediumThumb = cr_tnail_img(im_data,
                                                     sizes[thumbsize],
                                                     fext=fext)
                thumbdata.save()
            response.write(thumbdata.MediumThumb)
        elif thumbsize == "small":
            if not thumbdata.SmallThumb:
#                print ("Creating Small Thumb for %s" % os.path.basename(fs_path))
                try:
                    im_data = return_image_obj(data, memory=True)
                except IOError:
                    im_data = return_image_obj(os.path.join(
                        configdata["locations"]["resources_path"],
                        "images",
                        configdata["filetypes"]["archive"][1]),
                                               memory=True)
                thumbdata.SmallThumb = cr_tnail_img(im_data,
                                                    sizes[thumbsize],
                                                    fext=fext)
                thumbdata.save()
            response.write(thumbdata.SmallThumb)
        else:
            print ("Undeclared size")
        att_str = 'attachment; filename={0}'.format(os.path.basename(fs_path))
        response['Content-Disposition'] = att_str
        return response


    def return_image_obj(fs_path, memory=False):
        """
        Given a Fully Qualified FileName/Pathname, open the image
        (or PDF) and return the PILLOW object for the image
        Fitz == py
        """
        if os.path.splitext(fs_path)[1][1:].lower() == u"pdf":
            pdf_file = fitz.open(fs_path)
            pdf_page = pdf_file.loadPage(0)
            pix = pdf_page.getPixmap(matrix=fitz.Identity,
#                                     colorspace="rgb",
                                     alpha=True)

            source_image = Image.open(BytesIO(pix.getPNGData()))
        else:
            if not memory:
                source_image = Image.open(fs_path)
            else:
                # fs_path is a byte stream
                source_image = Image.open(BytesIO(fs_path))
#        if source_image.mode != "RGB":
#            source_image = source_image.convert('RGB')
        return source_image

    def cr_tnail_img(source_image, size, fext):
        """
        Given the PILLOW object, resize the image to <SIZE>
        and return the saved version of the file (using FEXT
        as the format to save as [eg. PNG])

        Return the binary representation of the file that
        was saved to memory
        """
        image_data = BytesIO()
        source_image.thumbnail((size, size), Image.ANTIALIAS)
        try:
            source_image.save(fp=image_data,
                              format=configdata["filetypes"][fext][2].strip(),
                              optimize=True)
        except IOError:
            source_image = source_image.convert('RGB')
            source_image.save(fp=image_data,
                              format=configdata["filetypes"][fext][2].strip(),
                              optimize=True)

        image_data.seek(0)
        return image_data.getvalue()

#
#   Processing Images - Start
#
    context = {}
    #missing_folder = configdata["locations"]["resources_path"] + \
        #os.sep + "images" + os.sep + "folder-close-icon.png"
    thumb_size = g_option(request, "size", "small").lower().strip()
    webpath = request.path_info
    if webpath.endswith("/"):
        #
        #   Not sure why a / is being appended on windows systems.
        #   Need to investigate further.
        #
        webpath = webpath[:-1]
    album_viewing = configdata["locations"]["albums_path"] + webpath.replace(
        "/",
        os.sep).replace(r"%sthumbnails%s" % (os.sep,
                                             os.sep),
                        r"%salbums%s" % (os.sep,
                                         os.sep))
    fs_path = album_viewing.replace(r"%sthumbnails%s" % (os.sep, os.sep),
                                    r"%salbums%s" % (os.sep, os.sep))
    if "dir" in request.GET:
        return process_dir(fs_path)
    elif "arch" in request.GET:
#        if fs_path.endswith(r"/"):
#            fs_path = fs_path[:-1]
        return process_archive(fs_path,
                               thumb_size,
                               request,
                               context)

    else:
        sourcepath = request.path.lower().replace(os.sep,
                                                  r"/").replace(r"/thumbnails/",
                                                                r"/albums/")
        sourcepath = os.path.split(sourcepath)[0]
        thumbdata = Thumbnails_Files.objects.filter(
            FilePath=os.path.split(fs_path)[0],
            FileName=os.path.split(fs_path)[1])
        if not thumbdata:
            #   There is no Thumbnail data for this file
            fpaths, fname = os.path.split(fs_path)
            new_entry = Thumbnails_Files.objects.create(SmallThumb=b"",
                                                        MediumThumb=b"",
                                                        LargeThumb=b"",
                                                        FilePath=fpaths,
                                                        FileName=fname,
                                                        FileSize=-1)
            thumbdata = new_entry
        else:
            thumbdata = thumbdata[0]

        if thumbdata.FileSize != os.path.getsize(fs_path):
            #   The cached data is invalidated since the filesize is inaccurate
            #   Reset the existing thumbnails to ensure that they will be
            #   regenerated
            thumbdata.SmallThumb = b""
            thumbdata.MediumThumb = b""
            thumbdata.LargeThumb = b""
            thumbdata.FileSize = os.path.getsize(fs_path)
#            thumbdata.save()
            #
            #  Clear the django cache here

        fext = os.path.splitext(fs_path)[1][1:].lower()
                                       # ".pdf_png_preview")

        if fext in configdata["filetypes"]:
            if configdata["filetypes"][fext][1].strip() != "None":
                fs_path = os.path.join(
                    configdata["locations"]["resources_path"],
                    "images",
                    configdata["filetypes"][fext][1])


        # Conditions:
            # 1 - thumbnail(s) do not exist
            # 2 -
        response = HttpResponse()
        if thumb_size == "small":
            if not thumbdata.SmallThumb:
                thumbdata.SmallThumb = cr_tnail_img(return_image_obj(fs_path),
                                                    sizes[thumb_size],
                                                    fext=fext)
                thumbdata.save()
            response.write(thumbdata.SmallThumb)
        elif thumb_size == "large":
            if not thumbdata.LargeThumb:
                thumbdata.LargeThumb = cr_tnail_img(return_image_obj(fs_path),
                                                    sizes[thumb_size],
                                                    fext=fext)
                thumbdata.save()
            response.write(thumbdata.LargeThumb)
        elif thumb_size == "medium":
            if not thumbdata.MediumThumb:
                thumbdata.MediumThumb = cr_tnail_img(return_image_obj(fs_path),
                                                     sizes[thumb_size],
                                                     fext=fext)
                thumbdata.save()
            response.write(thumbdata.MediumThumb)
        else:
            print ("Undeclared size")
        att_str = 'attachment; filename={0}'.format(os.path.basename(fs_path))
        response['Content-Disposition'] = att_str
        return response

def resources(request):
    """
    Serve the resources
    """
    webpath = request.path_info
    album_viewing = configdata["locations"]["resources_path"] +  \
        webpath.replace(r"/resources/", r"/").replace("/", os.sep)
    if not os.path.exists(album_viewing):
        print ("File Not Found - %s" % album_viewing)
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))

def test_extension(name, ext_list):
    """
    return TRUE if name is contained in the extensions list
    """
    return os.path.splitext(name)[1][1:].lower().strip() in ext_list

DF_VDBASE = ["sortname", "lastscan", "lastmod", "size"]
def validate_database(dir_to_scan):
    """
    validate the data base
    """
    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
    webpath = fqpn.replace(configdata["locations"]["albums_path"], "")
    temp = get_filtered(get_defered(index_data, DF_VDBASE), {'fqpndirectory':webpath,
                                                 'ignore':False})
    print ("validate triggered :",dir_to_scan)
    for entry in temp:
        if not os.path.exists(os.path.join(fqpn, entry.name)) or \
            os.path.splitext(entry.name.lower().strip())[1] in\
                configdata["filetypes"]["extensions_to_ignore"] or \
                entry.name.lower().strip() in\
                configdata["filetypes"]["files_to_ignore"]:
            entry.ignore = True
            entry.delete_pending = True
            entry.save()
    check_for_deletes()

def naturalize(string):
    """
        return <STRING> as a english sortable <STRING>
    """
    def naturalize_int_match(match):
        """ reformat as a human sortable number
        """
        return '%08d' % (int(match.group(0)),)

    string = string.lower().strip()
    string = re.sub(r'^the\s+', '', string)
    string = re.sub(r'\d+', naturalize_int_match, string)
    return string

def read_from_disk(dir_to_scan):
    """
    Pass in FQFN, and the database stores the path as the URL path.
    """
    def recovery_from_multiple(fqpndirectory, uname):
        """
        eliminate any duplicates
        """
        dataset = index_data.objects.filter(name__iexact=uname,
                                           fqpndirectory=webpath,
                                           ignore=False)
        dataset.delete()


    def add_entry(entry, webpath):
        """
        Add entry to the database
        """
        if entry.is_dir():
            # dir[0] = Path, dir[1] = dirs, dir[2] = files
            if PY2:
                dirdata = scandir.walk(entry.path).next()
            else:
                dirdata = next(os.walk(entry.path))
            # get directory count, and file count for subdirectory
        else:
            dirdata = ("", [], [])

        index_data.objects.create(lastmod=entry.stat()[stat.ST_MTIME],
                                 lastscan=time.time(),
                                 name=entry.name.title().replace("#", "").replace("?","").strip(),
                                 sortname=naturalize(entry.name.title()),
                                 size=entry.stat()[stat.ST_SIZE],
                                 fqpndirectory=webpath.replace(os.sep, r"/"),
                                 parent_dir_id=0,
                                 numfiles=len(dirdata[2]),
                                 # The # of files in this directory
                                 numdirs=len(dirdata[1]),
                                 # The # of Children Directories in this directory
                                 is_dir=entry.is_dir(),
                                 is_pdf=test_extension(entry.name, ['pdf']),
                                 is_image=test_extension(entry.name,
                                                         configdata["filetypes"]["graphic_file_types"]),
                                 is_archive=test_extension(entry.name,
                                                           ['cbz',
                                                            'cbr',
                                                            'zip',
                                                            'rar']),
                                 uuid=uuid.uuid4(),
                                 ignore=False,
                                 delete_pending=False,
                                )


    def update_entry(entry, webpath):
        """
        Update the existing entry in the database
        """
        #entry_fqfn = os.path.join(os.path.realpath(dir_to_scan), uname)
        changed = False
        if index_data.objects.filter(name__iexact=entry.name.title(),
                                     fqpndirectory=webpath,
                                     ignore=False).count() > 1:
            print ("Recovery from Multiple starting for %s" % entry.name)
            recovery_from_multiple(webpath, entry.name)
            add_entry(entry, webpath)
            return

        temp = index_data.objects.filter(name__iexact=entry.name.title(),
                                      fqpndirectory=webpath,
                                      ignore=False)
        orig = temp[0]

        changed = {}
        pkey = id

        if orig.name != entry.name.title() or orig.sortname == '':
            changed["name"] = entry.name.title()
            changed["sortname"] = naturalize(entry.name.title())

        if orig.uuid is None:
            changed["uuid"] = uuid.uuid4()

        if not os.path.exists(entry.path):
            changed["delete_pending"] = True
            changed["ignore"] = True

        if orig.size != entry.stat()[stat.ST_SIZE]:
            changed["size"] = entry.stat()[stat.ST_SIZE]

        if entry.stat()[stat.ST_MTIME] != orig.lastmod:
            changed["lastmod"] = entry.stat()[stat.ST_MTIME]
            changed["lastscan"] = entry.stat()[stat.ST_MTIME]

        t_ext = test_extension(
            entry.name, configdata["filetypes"]["graphic_file_types"])

        if orig.is_image != t_ext:
            changed["is_image"] = t_ext

        archive = test_extension(entry.name,
                                 ['cbz',
                                  'cbr',
                                  'zip',
                                  'rar'])
        if orig.is_archive != archive:
            changed["is_archive"] = archive

        if entry.is_dir():
            # dir[0] = Path, dir[1] = dirs, dir[2] = files
            if PY2:
                dirdata = scandir.walk(entry.path).next()
            else:
                dirdata = next(os.walk(entry.path))
                # get directory count, and file count for subdirectory
            if (len(dirdata[1]) != orig.numdirs or
                    len(dirdata[2]) != orig.numfiles):
                changed["numdirs"] = len(dirdata[1])
                changed["numfiles"] = len(dirdata[2])

        if changed:
#            print ("Updating - %s" % entry.name)
            changed["lastmod"] = entry.stat()[stat.ST_MTIME]
            changed["lastscan"] = entry.stat()[stat.ST_MTIME]
#           temp.save()
            print (changed)
            temp.update(**changed)


###############################
    # Read_from_disk - main
    #
    #
    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
#    print ("fqpn - ", fqpn)
    webpath = fqpn.replace(configdata["locations"]["albums_path"], "")
#    print ("Webpath - ", webpath)
    if not os.path.exists(fqpn):
        return None

    count = 0  # Used as sanity check for Validate
    for entry in scandir.scandir(fqpn):

        if (os.path.splitext(entry.name)[1] in\
            configdata["filetypes"]["extensions_to_ignore"]) or\
           (entry.name.lower() in configdata["filetypes"]["files_to_ignore"]):
            continue

        if not index_data.objects.filter(name__iexact=entry.name.title(),
                                        fqpndirectory=webpath,
                                        ignore=False).exists():
                #   Item does not exist
            add_entry(entry, webpath)
        else:
            update_entry(entry, webpath)

        count += 1

    if index_data.objects.values("id").filter(fqpndirectory=webpath,
                                             ignore=False).count() != count:
        print ("Count : %s,    %s - %s" % (count, index_data.objects.values("id").filter(fqpndirectory=webpath,
                                             ignore=False).count(), webpath))
        print ("Running Validate")
        validate_database(dir_to_scan)
    return webpath.replace(os.sep, r"/")


@vary_on_headers('User-Agent', 'Cookie')
def galleryitem(request, viewitem):
    """
    Serve the gallery items
    """
    context = {}
    paths = {}
    paths["webpath"] = request.path.lower()
    context["mobile"] = detect_mobile(request)
    paths["thumbpath"] = paths["webpath"].replace(r"/albums/",
                                                  r"/thumbnails/")
    context["small"] = g_option(request,
                                "size",
                                configdata["configuration"]["small"])
    context["medium"] = g_option(request,
                                 "size",
                                 configdata["configuration"]["medium"])
    context["large"] = g_option(request,
                                "size",
                                configdata["configuration"]["large"])
    request, context = sort_order(request, context)
    paths["item_fs"] = configdata["locations"]["albums_path"]\
        + unquote(request.path.replace("/", os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(
        paths["item_fs"].lower())
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["thumb_path"] = paths["web_path"].replace("%salbums" % os.sep,
                                                    "%sthumbnails" % os.sep)
    if not os.path.exists(paths["item_fs"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    read_from_disk(paths["item_path"].strip()) # gallery_item
    if not os.path.exists(paths["item_path"].strip()):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    index = get_db_files(context["sort_order"], paths["item_path"])

    chk_list = Paginator(index, 1)
    try:
        context["page"] = int(request.GET.get("page"))
        context["pagelist"] = chk_list.page(context["page"])
        context["item"] = index[context["page"]-1]
#        print (context["item"].Name)
#        print ("Integer")
    except (TypeError, PageNotAnInteger):
#        print ("Not an Integer")
        litem_name = paths["item_name"].strip().lower()
        for count, entry in enumerate(index, start=1):
            if entry.name.lower().strip() == litem_name:
                context["page"] = count
                context["pagelist"] = chk_list.page(context["page"])
                context["item"] = index[context["page"]-1]
                break
    except EmptyPage:
#        print ("Empty Page")
        context["pagelist"] = chk_list.page(chk_list.num_pages)
        context["page"] = chk_list.num_pages


    context["last_mod"] = datetime.datetime.fromtimestamp(context["item"].lastmod).strftime("%m-%d-%Y %H:%M")
    context["thumb_path"] = paths["thumb_path"]
    context["web_path"] = paths["web_path"]
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    context["current_page"] = context["page"]
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])

    response = render(request,
                      "frontend/gallery_item.html",
                      context)#,
                      #using="Jinja2")
    patch_vary_headers(response, ["sort-%s" % context["sort_order"]])
    return response


def new_download(request, uuid=None):

    download = index_data.objects.filter(uuid=uuid,
                                         ignore=False,
                                         delete_pending=False)[0]

    return serve(request,
                 download.name,
                 download.fqpndirectory)

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
#    context["last_mod"] = datetime.datetime.fromtimestamp(context["item"].lastmod).strftime("%m-%d-%Y %H:%M")

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
    print ("Starting cleanup")
    check_for_deletes()
    print ("Cleanup is done.")
    for prepath in configdata["locations"]["preload"]:
        print ("Pre-Caching: ", prepath)
        read_from_disk(prepath.strip()) # startup

        for ignored in configdata["filetypes"]["files_to_ignore"]:
            test = index_data.objects.filter(name__iexact=ignored.title())
            if test:
                print ("%s - %s" % (ignored, test.count()))
                test.delete()
