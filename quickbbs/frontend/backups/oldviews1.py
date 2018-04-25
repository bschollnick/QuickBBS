"""
Django views for QuickBBS Gallery
"""
# from django.shortcuts import render
from __future__ import absolute_import
from __future__ import print_function
from io import BytesIO
import datetime
import time
import os
import os.path
import re
import stat
import warnings
from PIL import Image
import six
from django.views.decorators.vary import vary_on_headers
from django.template import loader
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpResponse, HttpResponseNotFound
from django.views.static import serve
from django.contrib.auth import authenticate, login
from django.shortcuts import render
from django.core.exceptions import MultipleObjectsReturned
from six.moves import range
import fitz
import scandir
from thumbnails import get_thumbnail
from quickbbs.models import *
import fastnumbers
import directory_caching
import directory_caching.archives3 as archives
from frontend.config import configdata as configdata
import frontend.thumbnail as thumbnail
if six.PY2:
    from exceptions import IOError
    from urllib import unquote
else:
    from urllib.parse import unquote

warnings.simplefilter('ignore', Image.DecompressionBombWarning)

#
# Sending File or zipfile - https://djangosnippets.org/snippets/365/
#
#   No longer needed.  It'll be cached since it's stored in the database.

CDL = directory_caching.Cache()



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
                                            ['.cbz',
                                             '.cbr',
                                             '.zip',
                                             '.rar'])


def return_directory_tnail_filename(directory_to_use):
    """
    Identify candidate in directory for creating a tnail,
    and then return that filename.
    """
    #
    #   rewrite to use return_directory_contents
    #
    files = IndexData.objects.filter(FQPNDirectory=directory_to_use,
                                     is_dir=False,
                                     Ignore=False)
    for data in files:
        fext = os.path.splitext(data.Name)[1][1:].lower()
        if  fext in thumbnail.THUMBNAIL_DB:
            if thumbnail.THUMBNAIL_DB[fext]["IMG_TAG"]:
                return os.sep.join([directory_to_use, thumbnail[0]])
    #data = CDL.return_sort_name(directory_to_use.lower().strip())[0]
    #for thumbname in data:
        #if thumbname[1].file_extension in thumbnail.THUMBNAIL_DB:
            #if thumbnail.THUMBNAIL_DB[thumbname[1].file_extension]["IMG_TAG"]:
#                print (os.sep.join([directory_to_use, thumbname[0]]))
                #return os.sep.join([directory_to_use, thumbname[0]])
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


def return_prev_next(parent_path, currentpath, sorder):
    """
    Read the parent directory, get the index of the current path,
    return the previous & next paths.

    Replace the old system, with Django pagination.
    """
#    print ("Currentpath - ", currentpath)
    if currentpath.lower() == (r"/%s/" % "albums").lower():
        return ("", "")
#    read_from_disk(parent_path)
    url_parent = parent_path.replace(configdata["locations"]["albums_path"], "")
    if sorder == 0:
        pagedata = IndexData.objects.filter(FQPNDirectory=url_parent,
                                            is_dir=True,
                                            Ignore=False).order_by("-is_dir",
                                                                   "SortName")
    elif sorder == 1:
        pagedata = IndexData.objects.filter(FQPNDirectory=url_parent,
                                            is_dir=True,
                                            Ignore=False).order_by("-is_dir",
                                                                   "LastMod")
    elif sorder == 2:
        pagedata = IndexData.objects.filter(FQPNDirectory=url_parent,
                                            is_dir=True,
                                            Ignore=False).order_by("-is_dir",
                                                                   "SortName")
    found = None
    directories = Paginator(pagedata, 1)
    for count, data in enumerate(pagedata, 1):
        if data.Name.lower() == os.path.split(currentpath)[1].lower():
            found = directories.page(count)
    if found is None:
        found = directories.page(1)

    nextdir = ""
    prevdir = ""
    if found.has_next():
        nextdir = pagedata[found.next_page_number()-1].Name

    if found.has_previous():
        #prev = found.previous_page_number()
        prevdir = pagedata[found.previous_page_number()-1].Name

    return (prevdir, nextdir)

def read_from_cdl(dir_path, sort_by):
    """ Read from the cached Directory Listings"""
    CDL.smart_read(dir_path)
    cached_files, cached_dirs = CDL.return_sorted(scan_directory=dir_path,
                                                  sort_by=sort_by)
    return cached_dirs + cached_files

def check_for_deletes():
    """
    Check to see if any deleted items exist, if so, delete them.
    """
    deleted = IndexData.objects.filter(DeletePending=True)
    if deleted.count() != 0:
        print ("Deleting old deleted records")
        deleted.delete()


@vary_on_headers('User-Agent', 'Cookie')
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
    elif is_file(paths["album_viewing"]):
        return galleryitem(request, paths["album_viewing"])
    elif is_folder(paths["album_viewing"]):
        read_from_disk(paths["album_viewing"])
        if context["sort_order"] == 0:
            index = IndexData.objects.filter(FQPNDirectory=paths["webpath"],
                                             Ignore=False).order_by("-is_dir",
                                                                    "SortName")
        elif context["sort_order"] == 1:
            index = IndexData.objects.filter(FQPNDirectory=paths["webpath"],
                                             Ignore=False).order_by("-is_dir",
                                                                    "LastMod")
        elif context["sort_order"] == 2:
            index = IndexData.objects.filter(FQPNDirectory=paths["webpath"],
                                             Ignore=False).order_by("-is_dir",
                                                                    "SortName")

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
            os.path.dirname(paths["album_viewing"]),
            paths["webpath"], context["sort_order"])
        print("\r-------------\r")
        print(
            "Gallery page, elapsed after thumbnails - %s\r" %
            (time.time() - start_time))
        print("\r-------------\r")
#        return HttpResponse(template.render(context, request))
        return render(request,
                      "frontend/gallery_listing.jinja",
                      context,
                      using="Jinja2")

@vary_on_headers('User-Agent', 'Cookie')
def thumbnails(request, t_url_name=None):
    """
    Serve the thumbnail resources

    URL -> thumbnails/(?P<t_url_name>.*)
    """
    translate = {'jpg': 'JPEG', 'jpeg': 'JPEG',
                 'png': 'PNG', 'gif': 'JPEG',
                 'bmp': 'BMP', 'eps': 'EPS',
                 'msp': 'MSP', 'pcx': 'PCX',
                 'ppm': 'PPM', 'tif': 'TIF',
                 'tiff': 'TIF', 'pdf':'JPEG'}

    sizes = {
        "small":configdata["configuration"]["small"],
        "medium":configdata["configuration"]["medium"],
        "large":configdata["configuration"]["large"],
        "unknown":configdata["configuration"]["small"]
    }

    def make_thumbnail(thumb_file, thumb_size, mode=""):
        """
        Wrapper around python-thumbnails get_thumbnail function.
        """
        px_size = sizes[thumb_size]
        thumbnailfile = None
        if thumb_file is not None:
            if mode == "":
                fext = translate[os.path.splitext(thumb_file)[1][1:].lower()]
            else:
                fext = mode

            try:
                thumbnailfile = get_thumbnail(thumb_file,
                                              "%sx%s" % (px_size, px_size),
                                              format="%s" % fext,
                                              crop=None, force=False)
            except IOError:
                thumbnailfile = get_thumbnail(thumb_file,
                                              "%sx%s" % (px_size, px_size),
                                              format="PNG",
                                              crop=None, force=False)

        return thumbnailfile

    def process_dir(fs_path):
        """
        Read directory, and identify the first thumbnailable file.
        Make thumbnail of that file
        Return thumbnail results
        """
        webpath = fs_path.replace(configdata["locations"]["albums_path"], "")
        files = None
        try:
            files = IndexData.objects.filter(FQPNDirectory=webpath,
                                             is_dir=False,
                                             Ignore=False, is_image=True)[0]
        except IndexError:
            webpath = read_from_disk(fs_path)
            try:
                files = IndexData.objects.filter(FQPNDirectory=webpath,
                                                 is_dir=False,
                                                 Ignore=False,
                                                 is_image=True)[0]
            except IndexError:
                files = None


        thumbdata = Thumbnails_Dirs.objects.filter(FilePath=webpath)
        if not thumbdata:
            #
            #   There is no Thumbnail data for this file
            #
            new_entry = Thumbnails_Dirs.objects.create(SmallThumb=b"",
                                                       FilePath=webpath)
            thumbdata = new_entry
        else:
            thumbdata = thumbdata[0]

        if files is not None:
            fext = os.path.splitext(files.Name)[1][1:].lower()

            if fext in configdata["filetypes"]:
                if configdata["filetypes"][fext][1].strip() != "None":
                    fs_path = os.path.join(
                        configdata["locations"]["resources_path"],
                        "images", configdata["filetypes"][fext][1])


        if thumbdata.FileSize == -1 or thumbdata.FileSize != os.path.getsize(fs_path):
            #
            #   The cached data is invalidated since the filesize is inaccurate
            #   Reset the existing thumbnails to ensure that they will be regenerated
            #
            thumbdata.SmallThumb = b""
            thumbdata.MediumThumb = b""
            thumbdata.LargeThumb = b""
            thumbdata.FileSize = os.path.getsize(fs_path)
            thumbdata.save()

        if len(thumbdata.SmallThumb) == 0 and files is not None:
            temp = return_image_obj(configdata["locations"]["albums_path"]+\
                os.path.join(files.FQPNDirectory, files.Name))
            thumbdata.SmallThumb = create_tnail_img(temp,
                                                    sizes["small"],
                                                    fext=fext)

        if files is None:
            temp = return_image_obj(configdata["locations"]["images_path"]+\
                os.sep + configdata["filetypes"]["dir"][1])
            thumbdata.SmallThumb = create_tnail_img(
                temp, sizes["small"], configdata["filetypes"]["dir"][2])

        thumbdata.save()
        response = HttpResponse()
        response.write(thumbdata.SmallThumb)
        response['Content-Disposition'] = \
            'attachment; filename={0}'.format(os.path.basename(fs_path))
        return response

    def process_archive(fs_path, thumb_size, request, context, mode=""):
        """
        Process an archive, and return the thumbnail
        """
        print ("process archive : thumb_size,", thumb_size)
#        compressed_file = configdata["locations"]["resources_path"] + \
#            os.sep + "images" + os.sep + "1431973824_compressed.png"

        source_folder, arch_filename = os.path.split(fs_path.lower().strip())
        CDL.smart_read(source_folder)
        request, context = sort_order(request, context)
        folder_listing = read_from_cdl(source_folder,
                                       sort_by=context["sort_order"])
        page = fastnumbers.fast_int(get_option_value(request, "arch", 0))
        if page == "":
            page = 0
        print ("fs_path ", fs_path)
        print ("archive :", arch_filename)
        print ("Page - ", page)
        for entry in folder_listing:
            if entry[0].lower() == arch_filename:
                thumb_file = entry[1].archive_file.listings[page]
                file_data = entry[1].archive_file.extract_mem_file64(
                    thumb_file)
                print ("Thumb File : ", thumb_file, file_data[0:15])
                if file_data is not None:
                    #
                    #   Successful extraction of data for file[page]
                    fileext = file_data[11:file_data.find(";")]
                    #print (fileext, fileext in translate.keys())
                    if fileext.lower() in translate.keys():
                        fileext = translate[fileext.lower()]
                        if mode != "":
                            fileext = mode
                        thumbnailfile = make_thumbnail(file_data,
                                                       thumb_size,
                                                       fileext)
                    else:
                        #
                        #   Archived Image not recognized in translate
                        #
                        thumbnailfile = imageicon(os.path.join(
                            configdata["locations"]["resources_path"],
                            "images", configdata["filetypes"]["archive"][1]),
                                                  thumb_size)
                else:
                    # No archive image, extract gave none result
                    thumbnailfile = imageicon(os.path.join(
                        configdata["locations"]["resources_path"],
                        "images", configdata["filetypes"]["archive"][1]),
                                              thumb_size)
        return (thumbnailfile, request, context)

    def imageicon(icon_file, thumb_size):
        """
        return an thumbnail icon from the resource, images, folder
        """
        px_size = sizes[thumb_size]
        fext = os.path.splitext(icon_file)[1][1:].lower()
        if fext in configdata["filetypes"]:
            fext = translate[fext.lower()]
            iconfile = os.path.join(configdata["locations"]["resources_path"],
                                    "images",
                                    icon_file)
        else:
            iconfile = os.path.join(configdata["locations"]["resources_path"],
                                    "images",
                                    configdata["filetypes"]["generic"][1])
        thumbnailfile = get_thumbnail(iconfile,
                                      "%sx%s" % (px_size, px_size),
                                      format="%s" % fext.lower(),
                                      crop=None,
                                      force=False)
        return thumbnailfile

    def return_image_obj(fs_path):
        """
        Given a Fully Qualified FileName/Pathname, open the image
        (or PDF) and return the PILLOW object for the image
        """
        fext = os.path.splitext(fs_path)[1][1:].lower()

        if fext == "pdf":
            pdf_file = fitz.open(fs_path)
            pdf_page = pdf_file.loadPage(0)
            pix = pdf_page.getPixmap(matrix=fitz.Identity,
                                     colorspace="rgb",
                                     alpha=True)
            source_image = Image.open(BytesIO(pix.getPNGData()))
        else:
            source_image = Image.open(fs_path)

#        if source_image.mode != "RGB":
#            source_image = source_image.convert('RGB')
        return source_image

    def create_tnail_img(source_image, size, fext):
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

    context = {}
    #missing_folder = configdata["locations"]["resources_path"] + \
        #os.sep + "images" + os.sep + "folder-close-icon.png"
    thumb_size = get_option_value(request, "size", "small").lower().strip()
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
        print ("Processing Archive:")
#        if fs_path.endswith(r"/"):
#            fs_path = fs_path[:-1]
        thumbnailfile, request, context = process_archive(fs_path,
                                                          thumb_size,
                                                          request,
                                                          context)

    else:
        sourcepath = request.path.lower().replace(os.sep,
                                                  r"/").replace(r"/thumbnails/",
                                                                r"/albums/")
        sourcepath = os.path.split(sourcepath)[0]
        #thumb_fn = os.path.basename(request.path.strip())
        thumbdata = Thumbnails_Files.objects.filter(
            FilePath=os.path.split(fs_path)[0],
            FileName=os.path.split(fs_path)[1])
        if not thumbdata:
            #
            #   There is no Thumbnail data for this file
            #
            new_entry = Thumbnails_Files.objects.create(SmallThumb=b"",
                                                        MediumThumb=b"",
                                                        LargeThumb=b"",
                                                        FilePath=os.path.split(fs_path)[0],
                                                        FileName=os.path.split(fs_path)[1],
                                                        FileSize=-1)
            thumbdata = new_entry
        else:
            thumbdata = thumbdata[0]

        if thumbdata.FileSize == -1 or thumbdata.FileSize != os.path.getsize(fs_path):
            #
            #   The cached data is invalidated since the filesize is inaccurate
            #   Reset the existing thumbnails to ensure that they will be regenerated
            #
            thumbdata.SmallThumb = b""
            thumbdata.MediumThumb = b""
            thumbdata.LargeThumb = b""
            thumbdata.FileSize = os.path.getsize(fs_path)
            thumbdata.save()

        fext = os.path.splitext(fs_path)[1][1:].lower()
                                       # ".pdf_png_preview")

        if fext in configdata["filetypes"]:
            if configdata["filetypes"][fext][1].strip() != "None":
                fs_path = os.path.join(configdata["locations"]["resources_path"],
                                       "images",
                                       configdata["filetypes"][fext][1])

        if len(thumbdata.LargeThumb) == 0 and thumb_size.lower().strip() == "large":
            thumbdata.LargeThumb = create_tnail_img(return_image_obj(fs_path),
                                                    sizes["large"],
                                                    fext=fext)
            thumbdata.save()
            #source_image = return_image_obj(fs_path)
            #source_image.thumbnail((sizes["large"],
                                    #sizes["large"]), Image.ANTIALIAS)
            #source_image.save(fp=image_data, format=translate[fext], optimize=True)
            #image_data.seek(0)
            #thumbdata.LargeThumb = image_data.getvalue()
            #thumbdata.save()

        if len(thumbdata.MediumThumb) == 0 and thumb_size.lower().strip() == "medium":
            thumbdata.MediumThumb = create_tnail_img(return_image_obj(fs_path),
                                                     sizes["medium"],
                                                     fext=fext)
            thumbdata.save()

        if len(thumbdata.SmallThumb) == 0 and thumb_size.lower().strip() == "small":
            thumbdata.SmallThumb = create_tnail_img(return_image_obj(fs_path),
                                                    sizes["small"],
                                                    fext=fext)
            thumbdata.save()

        response = HttpResponse()
        if thumb_size.upper().strip() == "SMALL":
            response.write(thumbdata.SmallThumb)
        elif thumb_size.upper().strip() == "MEDIUM":
            response.write(thumbdata.MediumThumb)
        else:
#            thumb_size.upper().strip() == "LARGE":
            response.write(thumbdata.LargeThumb)

        response['Content-Disposition'] = 'attachment; filename={0}'.format(os.path.basename(fs_path))
        return response


#response = HttpResponse()
#response.write(docfile)
#response['Content-Disposition'] = 'attachment; filename={0}'.format(os.path.basename(thumbnailfile.path))
#return response
#    return serve(request, os.path.basename(thumbnailfile.path),
#                 os.path.dirname(thumbnailfile.path))


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

def validate_database(dir_to_scan):
    """
    validate the data base
    """
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
    """
        return <STRING> as a english sortable <STRING>
    """
    def naturalize_int_match(match):
        """ reformat as a human sortable number
        """
        return '%08d' % (int(match.group(0)),)

    string = string.lower()
    string = string.strip()
    string = re.sub(r'^the\s+', '', string)
    string = re.sub(r'\d+', naturalize_int_match, string)

    return string

def read_from_disk(dir_to_scan):
    """
    Pass in FQFN, and the database stores the path as the URL path.
    """
    def recovery_from_multiple(entry, FQPNDirectory):
        """
        eliminate any duplicates
        """
        dataset = IndexData.objects.filter(Name=entry.name, FQPNDirectory=webpath, Ignore=False)
        dataset.delete()

    def add_entry(entry, webpath):
        """
        Add entry to the database
        """
        if entry.is_dir():
            if six.PY2:
                path, raw_dirs, raw_files = scandir.walk(entry_fqfn).next()
            else:
                path, raw_dirs, raw_files = next(os.walk(entry_fqfn))

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
                                 is_image=test_extension(entry.name,
                                                         configdata["filetypes"]["graphic_file_types"]),
                                 is_archive=test_extension(entry.name,
                                                           ['.cbz',
                                                            '.cbr',
                                                            '.zip',
                                                            '.rar']),
                                 Ignore=False,
                                 DeletePending=False,
                                )


    def update_entry(entry, webpath):
        """
        Update the existing entry in the database
        """
        entry_fqfn = os.path.join(os.path.realpath(dir_to_scan), entry.name)
        changed = False
        try:
            temp = IndexData.objects.get(Name=entry.name,
                                         FQPNDirectory=webpath,
                                         Ignore=False)
        except MultipleObjectsReturned:
            recovery_from_multiple(entry, entry_fqfn)
            add_entry(entry, webpath)
            return

        if temp.SortName != naturalize(temp.Name):
            temp.SortName = naturalize(temp.Name.title())
            changed = True

        if temp.Size != entry.stat()[stat.ST_SIZE]:
            temp.Size = entry.stat()[stat.ST_SIZE]
            changed = True

        if entry.stat()[stat.ST_MTIME] != temp.LastMod:
            temp.LastMod = entry.stat()[stat.ST_MTIME]
            changed = True

        if temp.is_image != test_extension(
                entry.name, configdata["filetypes"]["graphic_file_types"]):
            temp.is_image = test_extension(
                entry.name, configdata["filetypes"]["graphic_file_types"])
            changed = True
#        new_pdf = test_extension(entry.name, ['.pdf'])
#        new_archive = test_extension(entry.name, ['.cbz', '.cbr', '.zip', '.rar'])
#        if temp.is_pdf != new_pdf or temp.is_archive != new_archive:
#            temp.is_pdf = new_pdf
#            temp.is_archive = new_archive
#            changed = True

        if entry.is_dir():
            if six.PY2:
                path, raw_dirs, raw_files = scandir.walk(entry_fqfn).next()
            else:
                path, raw_dirs, raw_files = next(os.walk(entry_fqfn))
                # get directory count, and file count for subdirectory
            if len(raw_dirs) != temp.NumDirs or len(raw_files) != temp.NumFiles:
                temp.NumDirs = len(raw_dirs)
                temp.NumFiles = len(raw_files)
                changed = True

        if changed:
#            print ("Updating - %s" % entry.name)
            temp.LastMod = entry.stat()[stat.ST_MTIME]
            temp.LastScan = time.time()
            temp.save()

    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
    webpath = fqpn.replace(configdata["locations"]["albums_path"], "")
    if os.path.exists(fqpn) is not True:
        return None

#    scantime = time.time()  # So that we don't have to regenerate the time for each file
    count = 0
    for entry in scandir.scandir(fqpn):
        if (os.path.splitext(entry.name.lower().strip())[1] in\
            configdata["filetypes"]["extensions_to_ignore"]) or\
           (entry.name.lower().strip() in configdata["filetypes"]["files_to_ignore"]):
            continue

        entry_fqfn = os.path.join(os.path.realpath(dir_to_scan), entry.name)
#        entry_parentdir = os.path.split(dir_to_scan)[0:-1][0]

        if not IndexData.objects.filter(Name=entry.name,
                                        FQPNDirectory=webpath, Ignore=False).exists():
                #
                #   Item does not exist
                #
            add_entry(entry, webpath)
        else:
            update_entry(entry, webpath)
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
        + unquote(request.path.replace("/", os.sep))
    paths["item_path"], paths["item_name"] = os.path.split(
        paths["item_fs"].lower())
    if "download" in request.GET and "page" not in request.GET:
        return serve(request, os.path.basename(paths["item_fs"]),
                     paths["item_path"])
    paths["web_path"] = paths["item_path"].replace(
        configdata["locations"]["albums_path"].lower(), "")
    paths["thumb_path"] = paths["web_path"].replace("%salbums" % os.sep,
                                                  "%sthumbnails" % os.sep)
    if not os.path.exists(paths["item_fs"]):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    read_from_disk(paths["item_path"].strip())
    if not os.path.exists(paths["item_path"].strip()):
        #
        #   Albums doesn't exist
        return HttpResponseNotFound('<h1>Page not found</h1>')

    if context["sort_order"] == 0:
        index = IndexData.objects.filter(FQPNDirectory=paths["item_path"].strip(),
                                         Ignore=False).order_by("-is_dir",
                                                                "SortName")
    elif context["sort_order"] == 1:
        index = IndexData.objects.filter(FQPNDirectory=paths["item_path"].strip(),
                                         Ignore=False).order_by("-is_dir",
                                                                "LastMod")
    elif context["sort_order"] == 2:
        index = IndexData.objects.filter(FQPNDirectory=paths["item_path"].strip(),
                                         Ignore=False).order_by("-is_dir",
                                                                "SortName")

    chk_list = Paginator(index, 1)
    try:
#        context["pagelist"] = chk_list.page(request.GET.get("page"))
        context["page"] = int(request.GET.get("page"))
        context["pagelist"] = chk_list.page(context["page"])
        context["item"] = index[context["page"]-1]
        print (context["item"].Name)
        print ("Integer")
    except TypeError, PageNotAnInteger:
        print ("Not an Integer")
        for count, entry in enumerate(index, start=1):
            if entry.Name.lower().strip() == paths["item_name"].strip().lower():
                context["page"] = count
                context["pagelist"] = chk_list.page(context["page"])
                context["item"] = index[context["page"]-1]
                break
    except EmptyPage:
        print ("Empty Page")
        context["pagelist"] = chk_list.page(chk_list.num_pages)
        context["page"] = chk_list.num_pages


    template = loader.get_template('frontend/gallery_item.html')
    context["last_mod"] = datetime.datetime.fromtimestamp(context["item"].LastMod).strftime("%m-%d-%Y %H:%M")
    context["thumb_path"] = paths["thumb_path"]
    context["web_path"] = paths["web_path"]
    context["gallery_name"] = os.path.split(request.path_info)[-1]
    if "download" in request.GET and "page" in request.GET:
        return serve(request,
                     os.path.basename(index[int(context["page"])-1].Name),
                     index[int(context["page"])-1].FQPNDirectory)

    context["current_page"] = context["page"]
    context["up_uri"] = "/".join(request.get_raw_uri().split("/")[0:-1])

    return HttpResponse(template.render(context, request))
#        return render(request,
#                      "frontend/gallery_listing.jinja",
#                      context,
#                      using="Jinja2")


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
        + unquote(request.path.replace("/", os.sep))
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
    listings = []
    #archive_file = archives.id_cfile_by_sig(paths["item_fs"])
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
    global_listings = read_from_cdl(paths["item_path"],
                                    sort_by=context["sort_order"])
    archive_index = return_cdl_index(global_listings, paths["item_name"])
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



check_for_deletes()
for prepath in configdata["locations"]["preload"]:
    print ("Pre-Caching: ", prepath)
    read_from_disk(prepath.strip())
