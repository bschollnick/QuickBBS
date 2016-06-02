#from django.shortcuts import render
import os, os.path
import urllib
#from threading import Thread
from django.http import HttpResponse, HttpResponseRedirect, HttpResponseNotFound
from django.template import loader
from django.views.static import serve
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import authenticate, login
import fastnumbers
import directory_caching
import frontend.config as config
import frontend.thumbnail as thumbnail
import frontend.tools as tools
#
#   Need to be able to set root path for albums directory
#   Need to be able to set root path for thumbnail directory
#
#
# Sending File or zipfile - https://djangosnippets.org/snippets/365/
# thumbnails - https://djangosnippets.org/snippets/20/

cdl = directory_caching.Cache()


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
    return not directory_caching.archives3.id_cfile_by_sig(fqfn) is None

def return_directory_tnail_filename(directory_to_use):
    """
    Identify candidate in directory for creating a tnail,
    and then return that filename.
    """
    #
    #   rewrite to use return_directory_contents
    #
    data = cdl.return_sort_name(directory_to_use.lower().strip())[0]
    for thumbname in data:
        if thumbname[1].file_extension.upper() in thumbnail.THUMBNAIL_DB:
            return os.sep.join([directory_to_use, thumbname[0]])
    return None

def     make_thumbnail_fqfns(list_fqfn, size, start=0, end=None):
    """
    list_fqfn is the directory_cache listing of the files that
    need a thumbnail_filename

    return the list of thumbnail_filenames
    """
    if end is None:
        end = len(list_fqfn)
    thumbnail_obj = thumbnail.Thumbnails()
    thumbnail_list = []
    for fqfn in list_fqfn[start:end]:
        thumbnail_list.append(thumbnail_obj.make_tnail_fsname(
            fqfn[1].fq_filename)[size])
    return thumbnail_list

def     verify_login_status(request, force_login=False):
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
            print "disabled account"
            # Return a 'disabled account' error message
    else:
        print "Invalid login"
        # Return an 'invalid login' error message.

def     option_exists(request, option_name):
    """
    Does the option exist in the request.GET
    """
    return option_name in request.GET

def     get_option_value(request, option_name, def_value):
    """
    Return the option from the request.get?
    """
    return request.GET[option_name, def_value]

def     sort_order(request, context):
    if "sort" in request.GET:
        #
        #   Set sort_order, since there is a value in the post
# pylint: disable=E1101
        request.session["sort_order"] = fastnumbers.fast_int(
            request.GET["sort"], 0)
        context["sort_order"] = fastnumbers.fast_int(request.GET["sort"], 0)
# pylint: enable=E1101
    else:
        if "sort_order" in request.session:
            context["sort_order"] = request.session["sort_order"]
        else:
            context["sort_order"] = 0
    return request, context

def detect_mobile(request):
    return request.META["HTTP_USER_AGENT"].find("Mobile") != -1

def return_prev_next(fqfn, webpath, sort_order):
    def get_directory_offset(offset,
                             scan_directory,
                             s_order,
                             current_directory):
        """
        Return the next / previous directory name, per offset
        """
        temp = cdl.return_current_directory_offset(
            scan_directory=scan_directory.lower(),
            current_directory=current_directory,
            sort_type=s_order,
            offset=offset)[1]

        if temp is not None:
            return (os.path.join(scan_directory, temp), temp)
        else:
            return ("", "")

    nextd = get_directory_offset(+1,
                                 scan_directory=os.sep.join(fqfn.split(os.sep)[0:-1]),
                                 s_order=sort_order,
                                 current_directory=fqfn.split(os.sep)[-1])
    next_uri = (r"/".join(["/".join(webpath.split("/")[0:-1]), nextd[1]]),
                nextd[1])

    prev = get_directory_offset(-1,
                                scan_directory=os.sep.join(fqfn.split(os.sep)[0:-1]),
                                s_order=sort_order,
                                current_directory=fqfn.split(os.sep)[-1])
    prev_uri = (r"/".join(["/".join(webpath.split("/")[0:-1]), prev[1]]),
                prev[1])
    return prev_uri[1], next_uri[1]

def     viewgallery(request):
    """
    View the requested Gallery page
    """
    context = {}
    paths = {}
    paths["webpath"] = request.path.lower()
    request, context = sort_order(request, context)

    paths["album_viewing"] = config.configdata["locations"]["albums_path"] +  \
        paths["webpath"].replace("/", os.sep)
    paths["fs_thumbpath"] = paths["album_viewing"].replace(r"%salbums%s" % (
        os.sep, os.sep), r"%sthumbnails%s" % (os.sep, os.sep))
    paths["thumbpath"] = paths["webpath"].replace(r"/albums/", r"/thumbnails/")
    if not paths["thumbpath"].endswith("/"):
        paths["thumbpath"] += "/"
    tnails = thumbnail.Thumbnails()

    if not os.path.exists(paths["album_viewing"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')
    elif is_archive(paths["album_viewing"]):
        return viewarchive(request, paths["album_viewing"])
    elif is_file(paths["album_viewing"]):
        return galleryitem(request, paths["album_viewing"])
    elif is_folder(paths["album_viewing"]):
        cdl.smart_read(paths["album_viewing"])
        cached_files, cached_dirs = cdl.return_sorted(
            scan_directory=paths["album_viewing"],
            sort_by=context["sort_order"])
        global_listing = cached_dirs + cached_files
        thumbnail_listings = make_thumbnail_fqfns(global_listing, size="small")
        listings = []
        tools.assure_path_exists(paths["fs_thumbpath"])
        for count, dcache in enumerate(global_listing):
#               0,          1,          ,2                  , 3
#   Listings = filename, dcache entry, web thumbnail path, thumbnail fs path
            if dcache[1].file_extension.upper() in thumbnail.THUMBNAIL_DB:
                tnails.create_thumbnail_from_file(
                    src_filename=dcache[1].fq_filename,
                    t_filename=thumbnail_listings[count],
                    t_size=config.configdata["configuration"]["sm_thumb"])
                listings.append((dcache[0], dcache[1],
                                 paths["thumbpath"] +
                                 os.path.split(thumbnail_listings[count])[1],
                                 thumbnail_listings[count],
                                 thumbnail.THUMBNAIL_DB[dcache[1].file_extension.upper()]\
                                 ["BACKGROUND"]))
            elif dcache[1].file_extension == "dir":
                cdl.smart_read(dcache[1].fq_filename.lower())
                dir_fname = return_directory_tnail_filename(
                    dcache[1].fq_filename.lower())
                if not dir_fname is None:
                    tfile = os.path.join(
                        os.path.split(dcache[1].fq_filename.lower())[0],
                        os.path.split(dcache[1].fq_filename.lower())[1])
                    thumbname = tnails.make_tnail_fsname(tfile)["small"]
                    tnails.timecheck_thumbnail_file(thumbname)
                    tnails.create_thumbnail_from_file(
                        src_filename=dir_fname,
                        t_filename=thumbname,
                        t_size=config.configdata["configuration"]\
                            ["sm_thumb"])
                    listings.append(
                        (dcache[0], dcache[1],
                         paths["thumbpath"] +\
                             os.path.split(thumbnail_listings[count])[1],
                         thumbnail_listings[count],
                         "#DAEFF5"))
                else:
                    listings.append(
                        (dcache[0], dcache[1],
                         r"/resources/images/folder-close-icon.png",
                         thumbnail_listings[count],
                         "#DAEFF5"))

        page_number = request.GET.get("page")
        chk_list = Paginator(listings, 30)
        template = loader.get_template('frontend/gallery_listing.html')
        context["page_cnt"] = range(1, chk_list.num_pages+1)
        context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
        context["gallery_name"] = os.path.split(request.path_info)[-1]
        try:
            context["pagelist"] = chk_list.page(page_number)
        except PageNotAnInteger:
            context["pagelist"] = chk_list.page(1)
        except EmptyPage:
            context["pagelist"] = chk_list.page(chk_list.num_pages)
        context["current_page"] = page_number
        context["all_listings"] = global_listing

        context["prev_uri"], context["next_uri"] = return_prev_next(
            paths["album_viewing"], paths["webpath"], context["sort_order"])
        context["webpath"] = paths["webpath"]
        return HttpResponse(template.render(context, request))


def thumbnails(request):
    webpath = request.path_info
    album_viewing = config.configdata["locations"]["albums_path"] +  \
        webpath.replace("/", os.sep)
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))

def resources(request):
    webpath = request.path_info
    album_viewing = config.configdata["locations"]["resources_path"] +  \
        webpath.replace(r"/resources/", r"/").replace("/", os.sep)
    return serve(request, os.path.basename(album_viewing),
                 os.path.dirname(album_viewing))


def galleryitem(request, viewitem):
    #
    #   rename album_viewing.  Is misleading.
    #
    context = {}
    paths = {}
    if "sort" in request.POST:
        #
        #   Set sort_order, since there is a value in the post
# pylint: disable=E1101
        request.session["sort_order"] = fastnumbers.fast_int(
            request.POST["sort"], 0)
        context["sort_order"] = fastnumbers.fast_int(request.POST["sort"], 0)
# pylint: enable=E1101
    else:
        if "sort_order" in request.session:
            context["sort_order"] = request.session["sort_order"]
        else:
            context["sort_order"] = 0

    paths["item_fs"] = config.configdata["locations"]["albums_path"]\
                       + urllib.unquote(request.path.replace("/", os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(paths["item_fs"].lower())
    tnails = thumbnail.Thumbnails()
    paths["web_path"] = paths["item_path"].replace(config.configdata["locations"]\
        ["albums_path"].lower(), "")
    paths["web_thumbpath"] = paths["web_path"].replace("/albums", "/thumbnails")+r"/"
    if not os.path.exists(paths["item_fs"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    cdl.smart_read(paths["item_path"].lower().strip())
    cached_files, cached_dirs = cdl.return_sorted(
        scan_directory=paths["item_path"],
        sort_by=context["sort_order"], reverse=False)

    listings = []
    for count, dcache in enumerate(cached_dirs + cached_files):
#               0,          1,          ,2                  , 3
#   Listings = filename, dcache entry, web thumbnail path, thumbnail fs path
#
#   4
#  web path to original
        listings.append((dcache[0].split("/")[0], dcache[1],
                         (paths["web_thumbpath"] +
                          tnails.make_tnail_name(filename=dcache[0])["medium"],
                          paths["web_thumbpath"] +
                          tnails.make_tnail_name(filename=dcache[0])["large"]),
                         (tnails.make_tnail_fsname(dcache[1].fq_filename)["medium"],
                          tnails.make_tnail_fsname(dcache[1].fq_filename)["large"]),
                         thumbnail.THUMBNAIL_DB.get(dcache[1].file_extension.upper(),
                                                    "#FFFFFF")))
#                         background))
    #page_number = request.GET.get("page")
    chk_list = Paginator(listings, 1)
    template = loader.get_template('frontend/gallery_item.html')
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    try:
        context["pagelist"] = chk_list.page(request.GET.get("page"))
        context["page"] = request.GET.get("page")
    except PageNotAnInteger:
        for count, fentry in enumerate(cached_files):
            if fentry[1].filename.lower() == paths["item_name"].lower():
                context["page"] = 1+count+len(cached_dirs)
                print "found, ", context["page"]
            else:
                context["pagelist"] = chk_list.page(1)
        context["pagelist"] = chk_list.page(context["page"])
    except EmptyPage:
        context["pagelist"] = chk_list.page(chk_list.num_pages)
    if "download" in request.GET:
        return serve(request,
                     os.path.basename(context["pagelist"].object_list[0][1].fq_filename),
                     os.path.dirname(context["pagelist"].object_list[0][1].fq_filename))

    context["all_listings"] = listings
    context["current_page"] = context["page"]
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])
    for entry in context["pagelist"]:
        tnails.create_thumbnail_from_file(src_filename=entry[1].fq_filename,
                                          t_filename=entry[3][0],
                                          t_size=config.configdata["configuration"]["med_thumb"])
        tnails.create_thumbnail_from_file(src_filename=entry[1].fq_filename,
                                          t_filename=entry[3][1],
                                          t_size=config.configdata["configuration"]["lg_thumb"])
    return HttpResponse(template.render(context, request))

def viewarchive(request, viewitem):
    return HttpResponse("""Hello, world. <br>
    You're viewing the view archive.
    %s<hr>
    %s<hr>
    %s<hr>
    %s<hr>
    %s""" % (dir(request),
             request.path_info,
             request.get_full_path(),
             request.session,
             request.user))

