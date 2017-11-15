# -*- coding: utf-8 -*-
"""
Django views for QuickBBS Gallery
"""
# from django.shortcuts import render
from __future__ import absolute_import
from __future__ import print_function
import datetime
import time
import os
import os.path
import re
import urllib
import stat
from thumbnails import get_thumbnail

from django.views.decorators.vary import vary_on_headers
from django.db import transaction
from django.http import HttpResponse, HttpResponseNotFound
# HttpResponseRedirect
from django.template import loader
from django.views.static import serve
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import authenticate, login
from django.shortcuts import render
import fastnumbers
import directory_caching
import directory_caching.archives3 as archives
from frontend.config import configdata as configdata
import frontend.thumbnail as thumbnail
import frontend.tools as tools
from six.moves import range
import fitz
from quickbbs.models import *
import scandir

#
#
#   Need to be able to set root path for albums directory
#   Need to be able to set root path for thumbnail directory
#
#
# Sending File or zipfile - https://djangosnippets.org/snippets/365/
# thumbnails - https://djangosnippets.org/snippets/20/
# EXECUTOR = futures.ThreadPoolExecutor(max_workers=10)
# workers = []

#
#   No longer needed.  It'll be cached since it's stored in the database.

CDL = directory_caching.Cache()
#for prepath in configdata["locations"]["preload"]:
#    print ("Pre-Caching: ", prepath)
    #CDL.smart_read(prepath)

#SIZES = ["sm_thumb", "med_thumb", "lg_thumb"]


def is_folder(fqfn):
    """
    Is it a folder?
    """
    return os.path.isdir(fqfn)


def is_file(fqfn):
    """
    Is it a file?
    """
    return os.path.isfile(fqfn)


def is_archive(fqfn):
    # None = not an archive.
    """
    Is it an archive?
    """
    return is_file(fqfn) and test_extension(fqfn,
                                            ['.cbz','.cbr','.zip','.rar'])
#    return is_file(fqfn) and not directory_caching.archives3.id_cfile_by_sig(
#        fqfn) is None


def return_directory_tnail_filename(directory_to_use):
    """
    Identify candidate in directory for creating a tnail,
    and then return that filename.
    """
    #
    #   rewrite to use return_directory_contents
    #
#     read_from_disk(directory_to_use.strip())
#     files = IndexData.objects.filter(FQPNDirectory=directory_to_use,
#                                      is_dir=False,
#                                      Ignore=False)
#     for data in files:
#         fext = os.path.splitext(data.Name)[1][1:].lower()
#         print (fext)
#         if fext in thumbnail.THUMBNAIL_DB:
#             if thumbnail.THUMBNAIL_DB[fext]["IMG_TAG"]:
#                 return os.sep.join([directory_to_use, thumbnail[0]])
    data = CDL.return_sort_name(directory_to_use.lower().strip())[0]
    for thumbname in data:
        if thumbname[1].file_extension in thumbnail.THUMBNAIL_DB:
            if thumbnail.THUMBNAIL_DB[thumbname[1].file_extension]["IMG_TAG"]:
                print (os.sep.join([directory_to_use, thumbname[0]]))
                return os.sep.join([directory_to_use, thumbname[0]])
    return None

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


def option_exists(request, option_name):
    """
    Does the option exist in the request.GET
    """
    return option_name in request.GET


def get_option_value(request, option_name, def_value):
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
        request.session["sort_order"] = fastnumbers.fast_int(
            request.GET["sort"], 0)
        context["sort_order"] = fastnumbers.fast_int(request.GET["sort"], 0)
# pylint: enable=E1101
    else:
        context["sort_order"] = request.session.get("sort_order", 0)
    return request, context


def detect_mobile(request):
    """
    Is this a mobile browser?
    """
    return request.META["HTTP_USER_AGENT"].find("Mobile") != -1


def return_prev_next(parent_path, currentpath, sort_order):
    """
    Read the parent directory, get the index of the current path,
    return the previous & next paths.

    Replace the old system, with Django pagination.
    """
    print ("Currentpath - ", currentpath)
    if currentpath.lower() == (r"/%s/" % "albums").lower():
        return ("", "")
    read_from_disk(parent_path)
    url_parent = parent_path.replace(configdata["locations"]["albums_path"], "")
    if sort_order == 0:
        pagedata = IndexData.objects.filter(FQPNDirectory=url_parent, is_dir=True,
                                         Ignore=False).order_by("-is_dir", "SortName")
    elif sort_order == 1:
        pagedata = IndexData.objects.filter(FQPNDirectory=url_parent,is_dir=True,
                                         Ignore=False).order_by("-is_dir", "LastMod")
    elif sort_order == 2:
        pagedata = IndexData.objects.filter(FQPNDirectory=url_parent,is_dir=True,
                                         Ignore=False).order_by("-is_dir", "SortName")
    found = None
    directories = Paginator(pagedata, 1)
    for count, data in enumerate(pagedata, 1):
        if data.Name.lower() == os.path.split(currentpath)[1].lower():
            found = directories.page(count)
    if found == None:
        found = directories.page(1)

    next = ""
    prev = ""
    print (found.has_next())
    if found.has_next():
        next = pagedata[found.next_page_number()-1].Name#found.next_page_number()

    if found.has_previous():
        #prev = found.previous_page_number()
        prev = pagedata[found.previous_page_number()-1].Name#found.next_page_number()

    return (prev, next)

def read_from_cdl(dir_path, sort_by):
    """ Read from the cached Directory Listings"""
    CDL.smart_read(dir_path)
    cached_files, cached_dirs = CDL.return_sorted(scan_directory=dir_path,
                                                  sort_by=sort_by)
    return cached_dirs + cached_files


def new_viewgallery(request):
    """
    View the requested Gallery page
    """
    import datetime
    start_time = time.time()
    context = {}
    paths = {}
    context["small"] = get_option_value(
        request, "size", configdata["configuration"]["small"])
    context["medium"] = get_option_value(
        request, "size", configdata["configuration"]["medium"])
    context["large"] = get_option_value(
        request, "size", configdata["configuration"]["large"])
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
    paths["thumbpath"] = paths["webpath"].replace(r"/albums/", r"/thumbnails/")
    context["thumbpath"] = paths["webpath"].replace(r"/albums/", r"/thumbnails/")
    if not paths["thumbpath"].endswith("/"):
        paths["thumbpath"] += "/"
    if not os.path.exists(paths["album_viewing"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')
    elif is_archive(paths["album_viewing"]):
        return viewarchive(request)
    elif is_file(paths["album_viewing"]):
        return galleryitem(request, paths["album_viewing"])
    elif is_folder(paths["album_viewing"]):
        read_from_disk(paths["album_viewing"])
        # <option value="0" {% if sort_order == 0 %}selected{% endif %}>A..Z</option>
        # <option value="1" {% if sort_order == 1 %}selected{% endif %}>LastM</option>
        # <option value="2" {% if sort_order == 2 %}selected{% endif %}>CTime</option>
        if context["sort_order"] == 0:
            index = IndexData.objects.filter(FQPNDirectory=paths["webpath"],
                                             Ignore=False).order_by("-is_dir", "SortName")
        elif context["sort_order"] == 1:
            index = IndexData.objects.filter(FQPNDirectory=paths["webpath"],
                                             Ignore=False).order_by("-is_dir", "LastMod")
        elif context["sort_order"] == 2:
            index = IndexData.objects.filter(FQPNDirectory=paths["webpath"],
                                             Ignore=False).order_by("-is_dir", "SortName")

        print(
            "after make_thumbnail fqfns, elapsed after enumerate - %s\r" %
            (time.time() - start_time))
        context["current_page"] = request.GET.get("page")
        chk_list = Paginator(index, 30)
#        template = loader.get_template('frontend/gallery_listing.html')
#        template = loader.get_template('frontend/gallery_listing.jinja')
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
#        context["all_listings"] = index
        print ("Album Viewing - ", os.path.dirname(paths["album_viewing"]))
        context["prev_uri"], context["next_uri"] = return_prev_next(
            os.path.dirname(paths["album_viewing"]), paths["webpath"], context["sort_order"])
        print("\r-------------\r")
        print(
            "Gallery page, elapsed after thumbnails - %s\r" %
            (time.time() - start_time))
        print("\r-------------\r")
#        return HttpResponse(template.render(context, request))
        return render(request, "frontend/gallery_listing.jinja", context, using="Jinja2")

@vary_on_headers('User-Agent', 'Cookie')
def thumbnails(request, T_Url_Name=None):
    """
    Serve the thumbnail resources

    URL -> thumbnails/(?P<T_Url_Name>.*)
    """
    translate = {'JPG': 'JPEG', 'JPEG': 'JPEG',
                 'PNG': 'PNG', 'GIF': 'JPEG',
                 'BMP': 'BMP', 'EPS': 'EPS',
                 'MSP': 'MSP', 'PCX': 'PCX',
                 'PPM': 'PPM', 'TIF': 'TIF',
                 'TIFF': 'TIF'}

    def make_thumbnail(thumb_file, thumb_size, mode=""):
        """
        Wrapper around python-thumbnails get_thumbnail function.
        """
        thumbnailfile = None
        if thumb_file is not None:
            fext = translate[os.path.splitext(thumb_file)[1][1:].upper()]
            if mode != "":
                fext = mode
            thumbnailfile = get_thumbnail(
                thumb_file, "%sx%s" %
                (thumb_size, thumb_size), format="%s" %
                fext, crop=None, force=False)
        return thumbnailfile

    def process_dir(fs_path, thumb_size, mode=""):
        """
        Read directory, and identify the first thumbnailable file.
        Make thumbnail of that file
        Return thumbnail results
        """
        #CDL.smart_read(album_viewing.lower().strip())
        #thumb_file = return_directory_tnail_filename(album_viewing)
        #thumbnailfile = make_thumbnail(thumb_file, thumb_size, mode)
        #return thumbnailfile
#        webpath = read_from_disk(album_viewing.strip())
        webpath = fs_path.replace(configdata["locations"]["albums_path"], "")
        files = IndexData.objects.filter(FQPNDirectory=webpath,
                                         is_dir=False,
                                         Ignore=False)
        if files.count() == 0:
            webpath = read_from_disk(fs_path)
        thumbnailfile = None
        for data in files:
            fext = os.path.splitext(data.Name)[1][1:].lower()
            abs = os.path.abspath(configdata["locations"]["albums_path"])
            if fext in thumbnail.THUMBNAIL_DB and thumbnail.THUMBNAIL_DB[fext]["IMG_TAG"]:
                fqfn = abs + os.sep + os.path.join(data.FQPNDirectory, data.Name)
                thumbnailfile = make_thumbnail(fqfn,
                                               thumb_size,
                                               mode)
                break
        if thumbnailfile != None:
            return thumbnailfile
        else:
            return imageicon("folder-close-icon.png", thumb_size)

    def process_pdf(fs_path, thumb_size):
        """
        Create a PDF image of the cover page.
        Cover page only, since the PDF workflow si to download the entire PDF
        not to view it page by page.
        """
        target_path, target_filename = os.path.split(fs_path)
        target_filename = os.path.join(target_path,
                                       os.path.splitext(target_filename)[0] +
                                       ".pdf_png_preview")
        # No page # is needed, since this is only the first page preview
        #
        if not os.path.exists(target_filename):
            pdf_file = fitz.open(fs_path)
            pdf_page = pdf_file.loadPage(0)
            pix = pdf_page.getPixmap(
                matrix=fitz.Identity,
                colorspace="rgb",
                alpha=True)
            pix.writePNG(target_filename)
        thumbnailfile = get_thumbnail(
            target_filename, "%sx%s" %
            (thumb_size, thumb_size), format="PNG", crop=None, force=False)
        return thumbnailfile

    def process_archive(fs_path, thumb_size, request, context, mode=""):
        """

        """
        compressed_file = configdata["locations"]["resources_path"] + \
            os.sep + "images" + os.sep + "1431973824_compressed.png"

        source_folder, arch_filename = os.path.split(fs_path.lower().strip())
        CDL.smart_read(source_folder)
        request, context = sort_order(request, context)
        folder_listing = read_from_cdl(source_folder,
                                       sort_by=context["sort_order"])
        page = fastnumbers.fast_int(get_option_value(request, "arch", 0))
        if page == "":
            page = 0

        for entry in folder_listing:
            if entry[0].lower() == arch_filename:
                thumb_file = entry[1].archive_file.listings[page]
                file_data = entry[1].archive_file.extract_mem_file64(
                    thumb_file)
                if file_data is not None:
                    fileext = file_data[11:file_data.find(";")]
                    if fileext in translate.keys():
                        fileext = translate[fileext.upper()]
                        if mode != "":
                            fileext = mode
                        thumbnailfile = get_thumbnail(
                            file_data, "%sx%s" %
                            (thumb_size, thumb_size), format="%s" %
                            fileext, crop=None, force=False)
                    else:
                        #
                        #   Archived Image not recognized in translate
                        #
                        thumbnailfile = get_thumbnail(
                            os.path.join(configdata["locations"]["resources_path"], "images",
                                         configdata["filetypes"]["archive"][1]),
                            "%sx%s" % (thumb_size, thumb_size),
                            format="%s" % fileext,
                            crop=None, force=False)

                else:
                    # No archive image, extract gave none result
                    thumbnailfile = get_thumbnail(
                        os.path.join(configdata["locations"]["resources_path"],"images",
                                     configdata["filetypes"]["archive"][1]),
                        "%sx%s" % (thumb_size, thumb_size),
                        format= os.path.splitext(configdata["filetypes"]["archive"][1])[1][1:],
                        crop=None, force=False)
        return (thumbnailfile, request, context)

    def imageicon(icon_file, thumb_size):
        """
        return an thumbnail icon from the resource, images, folder
        """
        fext = os.path.splitext(icon_file)[1][1:].lower()
        if configdata["filetypes"].has_key(fext):
            fext = translate[fext.upper()]
            iconfile = os.path.join(configdata["locations"]["resources_path"],
                                    "images",
                                    icon_file)
        else:
            iconfile = os.path.join(configdata["locations"]["resources_path"],
                                    "images",
                                    configdata["filetypes"]["generic"][1])
        print ("Image File - ", iconfile)
        thumbnailfile = get_thumbnail(iconfile,
                                      "%sx%s" % (thumb_size, thumb_size),
                                      format="%s" % fext.lower(),
                                      crop=None,
                                      force=False)
        print ("After thumbnailfile created")
        return thumbnailfile

    def process_images(fs_path, thumb_size, mode=""):
        if not os.path.exists(fs_path):
            print ("Original File (for Thumbnail) Not Found - %s" % fs_path)

        fext = os.path.splitext(fs_path)[1][1:]
        if translate.has_key(fext.upper()):
            #
            # Known to be imageable via the translate dictionary
            # (Need to replace with another solution)
            #
            fext = translate[fext.upper()]
            if mode != "":
                fext = mode
            if thumbnail.THUMBNAIL_DB[fext.lower()]["IMG_TAG"]:
                thumbnailfile = get_thumbnail(fs_path, "%sx%s" % (thumb_size, thumb_size),
                                              format="%s" % fext, crop=None, force=False)
                #
                #   Created thumbnail, now return it.
                #
                return thumbnailfile
            #
            #   Was not an image tag, return generic
            #
            thumbnailfile = imageicon(configdata["filetypes"]["generic"][1],
                                      thumb_size)
        else:
            #
            #   Falling back to filetypes
            #
            if configdata["filetypes"].has_key(fext.lower()):
                thumbnailfile = imageicon(configdata["filetypes"][fext.lower()][1],
                                          thumb_size)
            else:
                #
                #   Was not listed, create generic
                #
                thumbnailfile = imageicon(configdata["filetypes"]["generic"][1],
                                          thumb_size)
        return thumbnailfile

    context = {}
    missing_folder = configdata["locations"]["resources_path"] + \
        os.sep + "images" + os.sep + "folder-close-icon.png"
    thumb_size = fastnumbers.fast_int(get_option_value(
        request, "size", configdata["configuration"]["small"]))
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
        thumbnailfile = None
        try:
            thumbnailfile = process_dir(fs_path, thumb_size)
        except IOError:
            thumbnailfile = process_dir(fs_path, thumb_size, mode="PNG")
        if thumbnailfile == None:
            print ("Can't find preview image file")
            thumbnailfile = make_thumbnail(missing_folder,
                                           thumb_size,
                                           mode="PNG")

    elif "pdf" in request.GET:
        thumbnailfile = process_pdf(fs_path, thumb_size)
    elif "arch" in request.GET:
        if fs_path.endswith(r"/"):
            fs_path = fs_path[:-1]
        thumbnailfile, request, context = process_archive(fs_path,
                                                          thumb_size,
                                                          request,
                                                          context)
    else:
        try:
            thumbnailfile = process_images(fs_path, thumb_size)
        except IOError:
            thumbnailfile = process_images(fs_path, thumb_size, mode="PNG")

    return serve(request, os.path.basename(thumbnailfile.path),
                 os.path.dirname(thumbnailfile.path))


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
    return os.path.splitext(name)[1].lower() in ext_list

def validate_database(dir_to_scan):
    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
    webpath = fqpn.replace(configdata["locations"]["albums_path"], "")
    temp = IndexData.objects.filter(FQPNDirectory=webpath, Ignore=False)
    #
    #   Optimization?  .values(Name, FQPNDirectory, Ignore, DeletePending)
    #   It's still a majority, but it would more tightly focus the data.
    #
    for entry in temp:
        if not os.path.exists(os.path.join(fqpn, entry.Name)) or \
            os.path.splitext(entry.Name.lower().strip())[1] in\
                configdata["filetypes"]["extensions_to_ignore"] or \
                entry.Name.lower().strip() in\
                configdata["filetypes"]["files_to_ignore"]:
            entry.Ignore = True
            entry.DeletePending = True
            entry.save()

def naturalize(string):
    def naturalize_int_match(match):
        return '%08d' % (int(match.group(0)),)

    string = string.lower()
    string = string.strip()
    string = re.sub(r'^the\s+', '', string)
    string = re.sub(r'\d+', naturalize_int_match, string)

    return string

@transaction.atomic()
def read_from_disk(dir_to_scan):
    """
    Pass in FQFN, and the database stores the path as the URL path.
    """
    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
    webpath = fqpn.replace(configdata["locations"]["albums_path"], "")

    if os.path.exists(fqpn) is not True:
        return None

    scantime = time.time()  # So that we don't have to regenerate the time for each file
    count = 0
    for entry in scandir.scandir(fqpn):
        if (os.path.splitext(entry.name.lower().strip())[1] in\
            configdata["filetypes"]["extensions_to_ignore"]) or\
           (entry.name.lower().strip() in configdata["filetypes"]["files_to_ignore"]):
            continue

        entry_fqfn = os.path.join(os.path.realpath(dir_to_scan), entry.name)
#        entry_parentdir = os.path.split(dir_to_scan)[0:-1][0]

        if not IndexData.objects.filter(Name=entry.name, FQPNDirectory=webpath).exists():
                #
                #   Item does not exist
                #
            if entry.is_dir():
                path, raw_dirs, raw_files = scandir.walk(entry_fqfn).next()
                # get directory count, and file count for subdirectory
            else:
                path, raw_dirs, raw_files = ("", [], [])

            IndexData.objects.create(LastMod=entry.stat()[stat.ST_MTIME],
                                     LastScan=time.time(),
                                     Name=entry.name,
                                     SortName=naturalize(entry.name.title()),
                                     Size=entry.stat()[stat.ST_SIZE],
                                     FQPNDirectory=webpath.replace(os.sep, r"/"),
                                     ParentDirID=0,
                                     NumFiles=len(raw_files),
                                     # The # of files in this directory
                                     NumDirs=len(raw_dirs),
                                     # The # of Children Directories in this directory
                                     is_dir=entry.is_dir(),
                                     is_pdf=test_extension(entry.name, ['.pdf']),
                                     is_archive=test_extension(entry.name,
                                                               ['.cbz',
                                                                '.cbr',
                                                                '.zip',
                                                                '.rar']),
                                     Ignore=False,
                                     DeletePending=False,
                                    )
        else:
            changed = False
            temp = IndexData.objects.get(Name=entry.name,
                                         FQPNDirectory=webpath,
                                         Ignore=False)
            if temp.SortName != naturalize(temp.Name):
                temp.SortName = naturalize(temp.Name.title())
                changed = True

            if scantime > temp.LastMod:
                if temp.Size != entry.stat()[stat.ST_SIZE]:
                    temp.Size = entry.stat()[stat.ST_SIZE]
                    changed = True

            new_pdf = test_extension(entry.name, ['.pdf'])
            new_archive = test_extension(entry.name, ['.cbz', '.cbr', '.zip', '.rar'])
            if temp.is_pdf != new_pdf or temp.is_archive != new_archive:
                temp.is_pdf = new_pdf
                temp.is_archive = new_archive
                changed = True

            if entry.is_dir():
                path, raw_dirs, raw_files = scandir.walk(entry_fqfn).next()
                 # get directory count, and file count for subdirectory
                if len(raw_dirs) != temp.NumDirs or len(raw_files) != temp.NumFiles:
                    temp.NumDirs = len(raw_dirs)
                    temp.NumFiles = len(raw_files)
                    changed = True

            if changed:
                temp.LastMod = entry.stat()[stat.ST_MTIME]
                temp.LastScan = time.time()
                temp.save()
        count += 1
    if IndexData.objects.filter(FQPNDirectory=webpath, Ignore=False).count() != count:
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
    paths["thumbpath"] = paths["webpath"].replace(r"/albums/", r"/thumbnails/")
    context["small"] = get_option_value(
        request, "size", configdata["configuration"]["small"])
    context["medium"] = get_option_value(
        request, "size", configdata["configuration"]["medium"])
    context["large"] = get_option_value(
        request, "size", configdata["configuration"]["large"])
    request, context = sort_order(request, context)
    paths["item_fs"] = configdata["locations"]["albums_path"]\
        + urllib.unquote(request.path.replace("/", os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(
        paths["item_fs"].lower())
    if "download" in request.GET and "page" not in request.GET:
        return serve(request, os.path.basename(paths["item_fs"]),
                     paths["item_path"])
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["web_path"] = paths["web_path"].replace("%salbums" % os.sep,
                                                  "%sthumbnails" % os.sep)
    if not os.path.exists(paths["item_fs"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    CDL.smart_read(paths["item_path"].lower().strip())
    cached_files, cached_dirs = CDL.return_sorted(
        scan_directory=paths["item_path"],
        sort_by=context["sort_order"], reverse=False)

    listings = []
    for count, dcache in enumerate(cached_dirs + cached_files):
        #               0,          1,          ,2                  , 3
        #   Listings = filename, dcache entry, web tnail path, tnail fs path
        #
        #   4
        #  web path to original
        listings.append(
            (dcache[0].split("/")[0],
             dcache[1],
             (paths["web_path"] + r"/%s" % os.path.basename(
                 dcache[1].fq_filename),
              paths["web_path"] + r"/%s" % os.path.basename(
                  dcache[1].fq_filename)),
             (paths["web_path"] + r"/%s" % os.path.basename(
                 dcache[1].fq_filename),
              paths["web_path"] + r"/%s" % os.path.basename(
                  dcache[1].fq_filename)),
             thumbnail.THUMBNAIL_DB.get(dcache[1].file_extension, "#FFFFFF")))
    chk_list = Paginator(listings, 1)
    template = loader.get_template('frontend/gallery_item.html')
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    try:
        context["pagelist"] = chk_list.page(request.GET.get("page"))
        context["page"] = request.GET.get("page")
    except PageNotAnInteger:
        for count, fentry in enumerate(cached_files):
            if fentry[1].filename.lower() == paths["item_name"].lower():
                context["page"] = 1 + count + len(cached_dirs)
                context["pagelist"] = chk_list.page(context["page"])
            else:
                context["pagelist"] = chk_list.page(1)
        context["pagelist"] = chk_list.page(context["page"])
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    if "download" in request.GET and "page" in request.GET:
        return serve(request,
                     os.path.basename(
                         context["pagelist"].object_list[0][1].fq_filename),
                     os.path.dirname(
                         context["pagelist"].object_list[0][1].fq_filename))

    context["all_listings"] = listings
    context["current_page"] = context["page"]
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])

    return HttpResponse(template.render(context, request))


def return_cdl_index(cdl_data, filename):
    """
    Return the index of the archive in the CDL data
    """
    for count, cdl_record in enumerate(cdl_data):
        if cdl_record[0].lower() == filename.lower():
            return count

@vary_on_headers('User-Agent', 'Cookie')
def viewarchive(request):
    """
    Serve archive files
    """
    context = {}
    paths = {}
    request, context = sort_order(request, context)
    if "a_item" in request.GET:
        print("Forwarding to archive_item")
        return archive_item(request)
    paths["item_fs"] = configdata["locations"]["albums_path"]\
        + urllib.unquote(request.path.replace("/", os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(
        paths["item_fs"].lower())
    paths["thumb_path"] = paths["item_path"].replace("%salbums" % os.sep,
                                                     "%sthumbnails" % os.sep)
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["web_thumbpath"] = paths["web_path"].replace("/albums",
                                                       "/thumbnails") + r"/"
    global_listings = read_from_cdl(paths["item_path"],
                                    sort_by=context["sort_order"])
    archive_index = return_cdl_index(global_listings, paths["item_name"])
    tools.assure_path_exists(paths["thumb_path"] + os.sep + paths["item_name"])
    listings = []
    archive_file = archives.id_cfile_by_sig(paths["item_fs"])
    for count, filename in enumerate(global_listings[archive_index][1].
                                     archive_file.listings):
        #               0,          1,          ,2
        #   Listings = filename, zip fqfn, web thumbnail path (Med & Large),

        #       3,                              4
        #   thumbnail fs path (med & large), background color

        listings.append((filename,
                         global_listings[archive_index][1].fq_filename,
                         paths["web_thumbpath"] + paths["item_name"],
                         paths["web_thumbpath"] + paths["item_name"],
                         thumbnail.THUMBNAIL_DB.get(
                             global_listings[archive_index][1].
                             file_extension, "#FFFFFF")['BACKGROUND'],
                         count + 1))

#         if os.path.splitext(filename)[1][1:].lower() in thumbnail.THUMBNAIL_DB:
#             file_data = archive_file.extract_mem_file(filename)
#             if file_data is not None:
#                 workers.append(EXECUTOR.submit(THUMBNAIL.create_thumbnail_from_memory, file_data,
#                                                listings[-1][3],
#                                                configdata["configuration"]["sm_thumb"]))
#
#     futures.wait(workers)

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

    context["prev_uri"], context["next_uri"] = return_prev_next(
        paths["item_path"], paths["web_path"], context["sort_order"])
    context["webpath"] = paths["web_path"] + "/%s" % paths["item_name"]
#    thumbnail.pool.wait()
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
    context["small"] = get_option_value(
        request, "size", configdata["configuration"]["small"])
    context["medium"] = get_option_value(
        request, "size", configdata["configuration"]["medium"])
    context["large"] = get_option_value(
        request, "size", configdata["configuration"]["large"])
    paths["archive_item"] = fastnumbers.fast_int(
        get_option_value(request, "a_item", 1)) - 1
    paths["item_fs"] = configdata["locations"]["albums_path"]\
        + urllib.unquote(request.path.replace("/",
                                              os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(
        paths["item_fs"].lower())
    paths["thumb_path"] = paths["item_path"].replace("%salbums" % os.sep,
                                                     "%sthumbnails" % os.sep)
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["web_thumbpath"] = paths["web_path"].replace("/albums",
                                                       "/thumbnails") + r"/"
    global_listings = read_from_cdl(paths["item_path"],
                                    sort_by=context["sort_order"])
    archive_index = return_cdl_index(global_listings, paths["item_name"])
    tools.assure_path_exists(paths["thumb_path"] + os.sep + paths["item_name"])
    listings = []
    archive_file = archives.id_cfile_by_sig(paths["item_fs"])
    for count, filename in enumerate(global_listings[archive_index][1].
                                     archive_file.listings):
        #               0,          1,          ,2
        #   Listings = filename, zip fqfn, web thumbnail path (Med & Large),

        #       3,                              4
        #   thumbnail fs path (med & large), background color

        listings.append((filename,
                         global_listings[archive_index][1].fq_filename,
                         (paths["web_thumbpath"] + paths["item_name"],
                          paths["web_thumbpath"] + paths["item_name"]),
                         (paths["web_thumbpath"] + paths["item_name"],
                          paths["web_thumbpath"] + paths["item_name"]),
                         thumbnail.THUMBNAIL_DB.get(
                             global_listings[archive_index][1].
                             file_extension, "#FFFFFF")['BACKGROUND'],
                         count + 1))

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
#    thumbnail.pool.wait()
    template = loader.get_template('frontend/archive_item.html')
#        thumbnail.pool.shutdown()
    return HttpResponse(template.render(context, request))
