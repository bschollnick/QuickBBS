# -*- coding: utf-8 -*-
"""
Django views for QuickBBS Gallery
"""
# from django.shortcuts import render
from __future__ import absolute_import
from __future__ import print_function
import time
import os
import os.path
import urllib
import sys
# import concurrent.futures as futures
from thumbnails import get_thumbnail

from django.http import HttpResponse, HttpResponseNotFound
# HttpResponseRedirect
from django.template import loader
from django.views.static import serve
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import authenticate, login
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
import scandir
import stat

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

CDL = directory_caching.Cache()
#for prepath in configdata["locations"]["preload"]:
#    print ("Pre-Caching: ", prepath)
#    CDL.smart_read(prepath)

SIZES = ["sm_thumb", "med_thumb", "lg_thumb"]
#THUMBNAIL = thumbnail.Thumbnails()


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


# def is_image(fqfn):
#     # None = not an archive.
#     """
#     Is it an archive?
#     """
#     ext = os.path.splitext(fqfn)[1]
#     return is_file(fqfn) and THUMBNAIL[ext]['IMG_TAG']


def is_archive(fqfn):
    # None = not an archive.
    """
    Is it an archive?
    """
    return is_file(fqfn) and not directory_caching.archives3.id_cfile_by_sig(
        fqfn) is None


def return_directory_tnail_filename(directory_to_use):
    """
    Identify candidate in directory for creating a tnail,
    and then return that filename.
    """
    #
    #   rewrite to use return_directory_contents
    #
    data = CDL.return_sort_name(directory_to_use.lower().strip())[0]
    for thumbname in data:
        if thumbname[1].file_extension in thumbnail.THUMBNAIL_DB:
            if thumbnail.THUMBNAIL_DB[thumbname[1].file_extension]["IMG_TAG"]:
                return os.sep.join([directory_to_use, thumbname[0]])
    return None


def make_thumbnail_fqfns(list_fqfn, size, start=0, end=None):
    """
    list_fqfn is the directory_cache listing of the files that
    need a thumbnail_filename

    return the list of thumbnail_filenames
    """
    if end is None:
        end = len(list_fqfn)
    thumbnail_list = []
    for fqfn in list_fqfn[start:end]:
        thumbnail_list.append(fqfn[1].fq_filename)

    return thumbnail_list


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


def return_prev_next(fqfn, webpath, sortorder):
    """
    Return the previous and next directories for a gallery page
    """
    def get_directory_offset(offset,
                             scan_directory,
                             s_order,
                             current_directory):
        """
        Return the next / previous directory name, per offset
        """
        temp = CDL.return_current_directory_offset(
            scan_directory=scan_directory.lower(),
            current_directory=current_directory,
            sort_type=s_order,
            offset=offset)[1]

        if temp is not None:
            return (os.path.join(scan_directory, temp), temp)
        return ("", "")

    nextd = get_directory_offset(+1,
                                 scan_directory=os.sep.join(
                                     fqfn.split(os.sep)[0:-1]),
                                 s_order=sortorder,
                                 current_directory=fqfn.split(os.sep)[-1])
    next_uri = (r"/".join(["/".join(webpath.split("/")[0:-1]), nextd[1]]),
                nextd[1])

    prev = get_directory_offset(-1,
                                scan_directory=os.sep.join(
                                    fqfn.split(os.sep)[0:-1]),
                                s_order=sortorder,
                                current_directory=fqfn.split(os.sep)[-1])
    prev_uri = (r"/".join(["/".join(webpath.split("/")[0:-1]), prev[1]]),
                prev[1])
    return prev_uri[1], next_uri[1]


def read_from_cdl(dir_path, sort_by):
    """ Read from the cached Directory Listings"""
    CDL.smart_read(dir_path)
    cached_files, cached_dirs = CDL.return_sorted(scan_directory=dir_path,
                                                  sort_by=sort_by)
    return cached_dirs + cached_files


# def create_validate_thumb(src_file, t_file, t_size, archiveitem=0):
#     """
#     Create the thumbnail & validate the thumbnail's modification date
#     """
#     if THUMBNAIL.validate_thumbnail_file(t_file, src_file):
#         return
#
#     if src_file is None:
#         return
#     elif src_file.file_extension == "dir":
#         #    if src_file.file_extension == "dir":
#         #        print (dir(src_file))
#         print ("*", src_file.filename)
#         THUMBNAIL.create_thumbnail_from_file(src_filename=src_file.dir_thumb,
#                                              t_filename=t_file,
#                                              t_size=t_size)
#     elif src_file.file_extension in directory_caching.ARCHIVE_FILE_TYPES:
#         mem_file = src_file.archive_file.extract_mem_file(
#             src_file.archive_file.listings[archiveitem])
#         if mem_file is not None:
#             THUMBNAIL.create_thumbnail_from_memory(memory_image=mem_file,
#                                                    t_filename=t_file,
#                                                    t_size=t_size)
#
#     else:
#         #        print ("creating - ", src_file)
#         THUMBNAIL.create_thumbnail_from_file(src_filename=src_file.fq_filename,
#                                              t_filename=t_file,
#                                              t_size=t_size)


# def return_archive_icon_fn(cdl_entry):
#    pass


def viewgallery(request):
    """
    View the requested Gallery page
    """
    start_time = time.time()
    context = {}
    paths = {}
    context["mobile"] = detect_mobile(request)
    paths["webpath"] = request.path.lower()
    request, context = sort_order(request, context)

    paths["album_viewing"] = configdata["locations"]["albums_path"] +  \
        paths["webpath"].replace("/", os.sep)
    paths["fs_thumbpath"] = paths["album_viewing"].replace(r"%salbums%s" % (
        os.sep, os.sep), r"%sthumbnails%s" % (os.sep, os.sep))
    paths["thumbpath"] = paths["webpath"].replace(r"/albums/", r"/thumbnails/")
    if not paths["thumbpath"].endswith("/"):
        paths["thumbpath"] += "/"
#    tnails = THUMBNAIL.Thumbnails()
#    cr_thumbs = []
    read_from_disk(paths["album_viewing"])
    if not os.path.exists(paths["album_viewing"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')
    elif is_archive(paths["album_viewing"]):
        return viewarchive(request)
    elif is_file(paths["album_viewing"]):
        return galleryitem(request, paths["album_viewing"])
    elif is_folder(paths["album_viewing"]):
        global_listing = read_from_cdl(paths["album_viewing"],
                                       context["sort_order"])
        thumbnail_listings = make_thumbnail_fqfns(global_listing, size="small")
        print(
            "after make_thumbnail fqfns, elapsed after enumerate - %s\r" %
            (time.time() - start_time))
        listings = []
        tools.assure_path_exists(paths["fs_thumbpath"])
        for count, dcache in enumerate(global_listing):
            #               0,          1,          ,2                  , 3
            # Listings = fname, dcache entry, web thmbnailpath, thmbnailfs path
            if dcache[1].file_extension in thumbnail.THUMBNAIL_DB:
                listings.append((dcache[0], dcache[1],
                                 paths["thumbpath"] +
                                 os.path.split(thumbnail_listings[count])[1],
                                 thumbnail_listings[count],
                                 thumbnail.THUMBNAIL_DB[
                                     dcache[1].file_extension]
                                 ["BACKGROUND"]))
            elif dcache[1].file_extension == "dir":
                listings.append((dcache[0], dcache[1],
                                 paths["thumbpath"] +
                                 os.path.split(thumbnail_listings[count])[1],
                                 thumbnail_listings[count],
                                 "#DAEFF5"))
        print(
            "Gallery page, elapsed after enumerate - %s\r" %
            (time.time() - start_time))
        context["current_page"] = request.GET.get("page")
        chk_list = Paginator(listings, 30)
        template = loader.get_template('frontend/gallery_listing.html')
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
        context["all_listings"] = global_listing
        print(
            "Gallery page, elapsed before thumbnails - %s\r" %
            (time.time() - start_time))

        context["prev_uri"], context["next_uri"] = return_prev_next(
            paths["album_viewing"], paths["webpath"], context["sort_order"])
        context["webpath"] = paths["webpath"]
#        thumbnail.pool.shutdown()
        # thumbnail.pool.wait()
#        time.sleep(.25)
        print("\r-------------\r")
        print(
            "Gallery page, elapsed after thumbnails - %s\r" %
            (time.time() - start_time))
        print("\r-------------\r")
        return HttpResponse(template.render(context, request))


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

    def process_dir(album_viewing, thumb_size, mode=""):
        CDL.smart_read(album_viewing.lower().strip())
        thumb_file = return_directory_tnail_filename(album_viewing)
        thumbnailfile = make_thumbnail(thumb_file, thumb_size, mode)
        return thumbnailfile

    def process_pdf(fs_path, thumb_size):
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
                    fileext = translate[fileext.upper()]
                    if mode != "":
                        fileext = mode
                    thumbnailfile = get_thumbnail(
                        file_data, "%sx%s" %
                        (thumb_size, thumb_size), format="%s" %
                        fileext, crop=None, force=False)
                else:
                    return HttpResponseNotFound('<h1>Image not found</h1>')
        return (thumbnailfile, request, context)

    def process_images(fs_path, thumb_size, mode=""):
        if not os.path.exists(fs_path):
            print ("Original File (for Thumbnail) Not Found - %s" % fs_path)

        fext = translate[os.path.splitext(fs_path)[1][1:].upper()]
        if mode != "":
            fext = mode
        if fext.lower() in thumbnail.THUMBNAIL_DB:
            if thumbnail.THUMBNAIL_DB[fext.lower()]["IMG_TAG"]:
                thumbnailfile = get_thumbnail(
                    fs_path, "%sx%s" %
                    (thumb_size, thumb_size), format="%s" %
                    fext, crop=None, force=False)
            elif thumbnail.THUMBNAIL_DB[fext.lower()]["FRAME_TAG"]:
                return HttpResponseNotFound('<h1>Image not found</h1>')
        elif fext is '':
            return HttpResponseNotFound('<h1>Image not found</h1>')
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
            thumbnailfile = process_dir(album_viewing, thumb_size)
        except IOError:
            thumbnailfile = process_dir(album_viewing, thumb_size, mode="PNG")
        if thumbnailfile == None:
            print ("Can't find preview image file")
            thumbnailfile = make_thumbnail(missing_folder,
                                           thumb_size,
                                           mode="PNG")

    elif "pdf" in request.GET:
        thumbnailfile = process_pdf(fs_path, thumb_size)
    elif "arch" in request.GET:
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

def test_extension ( name, ext_list ):
    return os.path.splitext(name)[1].lower() in ext_list

def read_from_disk ( dir_to_scan):

    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
    webpath = fqpn.replace(configdata["locations"]["albums_path"], "")

    if os.path.exists(fqpn) is not True:
        return None

    for entry in scandir.scandir(fqpn):
        print(configdata)
        if os.path.splitext(entry.name.lower().strip())[1] in configdata["filetypes"]["extensions_to_ignore"]:#(".pdf_png_preview"):
            continue
        if entry.name.lower().strip() in configdata["filetypes"]["files_to_ignore"]:
            continue

        entry_fqfn = os.path.join(os.path.realpath(dir_to_scan), entry.name)
        entry_parentdir = os.path.split(dir_to_scan)[0:-1][0]
        if entry.is_file():
            if not FileData.objects.filter(FileName = webpath + entry.name, ParentDirID = 0).exists():
                #
                #   File does not exist
                #
                FileData.objects.create(LastMod = entry.stat()[stat.ST_MTIME],
                                        LastScan = time.time(),
                                        FileName = webpath + entry.name,
                                        SortFileName = webpath + entry.name.title(),
                                        FileSize = entry.stat()[stat.ST_SIZE],
                                        FQPNDirectory = webpath,
                                        ParentDirID = 0,
                                        is_pdf = test_extension(entry.name, ['.pdf']),
                                        is_archive = test_extension(entry.name, ['.cbz', '.cbr', '.zip', '.rar']),
                                        Ignore = False,
                                        DeletePending = False)
            else:
                #
                #   Directory does exist, but may need updating
                #
                changed = False
                Filetemp = FileData.objects.get(FileName = webpath + entry.name, ParentDirID = 0)
                if Filetemp.FileSize != entry.stat()[stat.ST_SIZE]:
                    Filetemp = entry.stat()[stat.ST_SIZE]
                    changed = True
                if Filetemp.LastMod != entry.stat()[stat.ST_MTIME]:
                    Filetemp.LastMod = entry.stat()[stat.ST_MTIME]
                    changed = True
                is_pdf = test_extension(entry.name, ['.pdf'])
                is_archive = test_extension(entry.name, ['.cbz', '.cbr', '.zip', '.rar'])
                if Filetemp.is_pdf != is_pdf:
                    Filetemp.is_pdf = is_pdf
                    Filetemp.is_archive = False
                    changed = True

                if Filetemp.is_archive != is_archive:
                    Filetemp.is_pdf = False
                    Filetemp.is_archive = is_archive
                    changed = True

                if changed:
                    Filetemp.LastMod = entry.stat()[stat.ST_MTIME]
                    Filetemp.LastScan = time.time()
                    Filetemp.save()

        elif entry.is_dir():
            #
            #   The Fully Qualified Pathnames are from the gallery root.  Not from Root
            #   of the drive.
            #
            #   This allows the gallery to be moved, and not have to regenerate all the
            #   paths.
            path, raw_dirc, raw_filec = scandir.walk(entry_fqfn).next() # get directory count, and file count for subdirectory
            if not DirData.objects.filter(DirURL = webpath + entry.name, ParentDirID = 0).exists():
                #
                #   Directory Does not exist
                #
                DirData.objects.create(LastMod = entry.stat()[stat.ST_MTIME], #datetime.datetime.fromtimestamp(entry.stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                                       LastScan = time.time(),#datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                       DirPN = "",
                                       DirURL = webpath + entry.name,
                                       NumFiles = len(raw_filec),
                                       NumDirs = len(raw_dirc),
                                       ParentDirID = 0,
                                       ThumbFQFN = "",
                                       Ignore = False)
            else:
                #
                #   Directory does exist, but may need updating
                #
                changed = False
                Dirtemp = DirData.objects.get(DirURL = webpath + entry.name, ParentDirID = 0)
                if len(raw_dirc) != Dirtemp.NumDirs or len(raw_filec) !=  Dirtemp.NumFiles:
                    Dirtemp.NumDirs = len(raw_dirc)
                    Dirtemp.NumFiles = len(raw_filec)
                    changed = True

                if Dirtemp.LastMod != entry.stat()[stat.ST_MTIME]:
                    Dirtemp.LastMod = entry.stat()[stat.ST_MTIME]
                    changed = True

                if changed:
                    Dirtemp.LastMod = entry.stat()[stat.ST_MTIME]
                    Dirtemp.LastScan = time.time()
                    Dirtemp.save()


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
#             (THUMBNAIL.make_tnail_fsname(dcache[1].fq_filename)["medium"],
#              THUMBNAIL.make_tnail_fsname(dcache[1].fq_filename)["large"]),
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
#    tnails = thumbnail.Thumbnails()
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
#    tnails = thumbnail.Thumbnails()
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

#     if os.path.splitext(listings[paths["archive_item"]][0])[1][1:].lower()\
#             in thumbnail.THUMBNAIL_DB:
#         file_data = archive_file.extract_mem_file(
#             listings[paths["archive_item"]][0])
#         if file_data is not None:
#             THUMBNAIL.create_thumbnail_from_memory(memory_image=file_data,
#                                                    t_filename=listings[paths["archive_item"]][3][1 - (context["mobile"] is True)],
#                                                    t_size=configdata["configuration"][SIZES[1 - (context["mobile"] is True)]])
#
#     futures.wait(workers)

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
