"""
Utilities for QuickBBS, the python edition.
"""
from __future__ import absolute_import, print_function, unicode_literals

import mimetypes
import os
import os.path
from io import BytesIO
import uuid
#import urllib
import re
import stat
import sys
import time

from PIL import Image
import fitz
from django.http import HttpResponse
import scandir
from frontend.database import get_filtered, get_defered, check_for_deletes
from quickbbs.models import index_data

PY2 = sys.version_info[0] < 3

if PY2:
    from exceptions import IOError

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

    Args:
        request (obj) - Django Request object

    Returns:
        boolean::
            `True` if Mobile is found in the request's META headers
            specifically in HTTP USER AGENT.  If not found, returns False.

    Raises:
        None
    """
    return "Mobile" in request.META["HTTP_USER_AGENT"]

def is_valid_uuid(uuid_to_test, version=4):
    """
    Check if uuid_to_test is a valid UUID.
    https://stackoverflow.com/questions/19989481

    Args:
        uuid_to_test (str) - UUID code to validate
        version (int) - UUID version to validate against (eg  1, 2, 3, 4)

    Returns:
        boolean::
            `True` if uuid_to_test is a valid UUID, otherwise `False`.

    Raises:
        None

    Examples
    --------
    >>> is_valid_uuid('c9bf9e57-1685-4c89-bafb-ff5af830be8a')
    True
    >>> is_valid_uuid('c9bf9e58')
    False
    """
    try:
        uuid_obj = uuid.UUID(uuid_to_test, version=version)
    except:
        return False

    return str(uuid_obj) == uuid_to_test


def test_extension(name, ext_list):
    """
    Check if filename has an file extension that is in passed list.

    Args:
        name (str): The Filename to examine
        ext_list (list): ['zip', 'rar', etc] # list of file extensions (w/o .),
            lowercase.

    Returns:
        boolean::
            `True` if name does match an extension passed, otherwise `False`.

    Raises:
        None

    Examples
    --------
    >>> test_extension("test.zip", ['zip', 'cbz'])
    True
    >>> test_extension("test.rar", ['zip', 'cbz'])
    False

    """
    return os.path.splitext(name)[1][1:].lower().strip() in ext_list

def is_archive(fqfn):
    # None = not an archive.
    """
    Check if filename has an file extension that in the archive file types list

    Args:
        fqfn (str): Filename of the file

    Returns:
        boolean::
            `True` if name does match an extension in the archive_fts
            (archive filetypes) list.  Otherwise return none.

    Raises:
        None

    Examples
    --------
    >>> is_archive("test.zip")
    True
    >>> is_archive("test.jpg")
    False

    """
    return test_extension(fqfn, configdata["filetypes"]["archive_fts"])
#                                           ['cbz',
#                                            'cbr',
#                                            'zip',
#                                            'rar'])
def return_inline_attach(filename, binaryblob):
    """
    Output a http response header, for an image attachment.

   Args:
        filename (str): Filename of the file to be sent as the attachment name
        binaryblob (bin): The blob of data that is the image file

    Returns:
        object::
            The Django response object that contains the attachment and header

    Raises:
        None

    Examples
    --------
    return_img_attach("test.png", img_data)


    """
    response = HttpResponse()
    response.write(binaryblob)
    response['Content-Disposition'] = 'inline;filename={%s}' % filename
    return response

def return_img_attach(filename, binaryblob):
    """
    Output a http response header, for an image attachment.

   Args:
        filename (str): Filename of the file to be sent as the attachment name
        binaryblob (bin): The blob of data that is the image file

    Returns:
        object::
            The Django response object that contains the attachment and header

    Raises:
        None

    Examples
    --------
    return_img_attach("test.png", img_data)


    """
    response = HttpResponse()
    response.write(binaryblob)
    response['Content-Disposition'] = 'attachment; filename={%s}' % filename
    return response

def respond_as_attachment(request, file_path, original_filename):
#   https://www.djangosnippets.org/snippets/1710/
#   print ("original filename: ", original_filename)
    filename = os.path.join(file_path, original_filename)
    fp = open(filename, 'rb')
    response = HttpResponse(fp.read())
    fp.close()
    type, encoding = mimetypes.guess_type(original_filename)
    if type is None:
        type = 'application/octet-stream'
    response['Content-Type'] = type
    print(response['Content-Type'])
    response['Content-Length'] = str(os.stat(filename).st_size)
    if encoding is not None:
        response['Content-Encoding'] = encoding
    filename_header = 'filename="%s"' % original_filename
# To inspect details for the below code, see http://greenbytes.de/tech/tc2231/
#     if u'WebKit' in request.META['HTTP_USER_AGENT']:
#         # Safari 3.0 and Chrome 2.0 accepts UTF-8 encoded string directly.
#         filename_header = 'filename=%s' % original_filename.encode('utf-8')
#     elif u'MSIE' in request.META['HTTP_USER_AGENT']:
#         # IE does not support internationalized filename at all.
#         # It can only recognize internationalized URL, so we do the trick
#           via routing rules.
#         filename_header = ''
#     else:
#         # For others like Firefox, we follow RFC2231 (encoding extension
#           in HTTP headers).
#         filename_header = 'filename*=UTF-8\'\'%s' %
#              urllib.quote(original_filename.encode('utf-8'))
    response['Content-Disposition'] = 'attachment; ' + filename_header
    return response

def get_xth_image(database, positional=0, filters=[]):
    """
    Return the xth image from the database, using the passed filters

    Parameters
    ----------

    database : object - The django database handle

    positional : int - 0 is first, if positional is greater than the # of
                 records, then it is reset to the count of records

    filters : dictionary of filters

    Returns
    -------
    If successful the database record in question, otherwise returns None

    Examples
    --------
    return_img_attach("test.png", img_data)
"""
    files = database.objects.filter(**filters)
    if files:
        if positional > files.count():
            positional = files.count()
        elif positional < 0:
            positional = 0
        return files[positional]
    else:
        return None

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

def read_from_disk(dir_to_scan):
    """
    Pass in FQFN, and the database stores the path as the URL path.
    """
    def recovery_from_multiple(fqpndirectory, uname):
        """
        eliminate any duplicates
        """
        dataset = index_data.objects.filter(
            name__iexact=uname, fqpndirectory=fqpndirectory.lower(),
            ignore=False)
        dataset.delete()

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

        index_data.objects.create(
            lastmod=entry.stat()[stat.ST_MTIME],
            lastscan=time.time(),
            name=entry.name.title().replace("#", "").replace("?", "").strip(),
            sortname=naturalize(entry.name.title()),
            size=entry.stat()[stat.ST_SIZE],
            fqpndirectory=webpath.replace(os.sep, r"/").lower(),
            parent_dir_id=0,
            numfiles=len(dirdata[2]),
            # The # of files in this directory
            numdirs=len(dirdata[1]),
            # The # of Children Directories in
            # this directory
            is_dir=entry.is_dir(),
            is_pdf=test_extension(entry.name, ['pdf']),
            is_image=test_extension(entry.name,
                                    configdata["filetypes"]["graphic_fts"]),
            is_archive=test_extension(entry.name,
                                      ['cbz', 'cbr', 'zip', 'rar']),
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
            print("Recovery from Multiple starting for %s" % entry.name)
            recovery_from_multiple(webpath, entry.name)
            add_entry(entry, webpath)
            return

        temp = index_data.objects.filter(
            name__iexact=entry.name.title(),
            fqpndirectory=webpath.replace(os.sep, r"/").lower(),
            ignore=False)
        orig = temp[0]

        changed = {}
        #pkey = id

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
            entry.name, configdata["filetypes"]["graphic_fts"])

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
#            print("Updating - %s" % entry.name)
            changed["lastmod"] = entry.stat()[stat.ST_MTIME]
            changed["lastscan"] = entry.stat()[stat.ST_MTIME]
#           temp.save()
            temp.update(**changed)


###############################
    # Read_from_disk - main
    #
    #
    dir_to_scan = dir_to_scan.strip()

    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
    fqpn = fqpn.replace("//", "/")
    webpath = fqpn.lower().replace(
        configdata["locations"]["albums_path"].lower(),
        "")
    if not os.path.exists(fqpn):
        return None

    count = 0  # Used as sanity check for Validate
    for entry in scandir.scandir(fqpn):

        if (os.path.splitext(entry.name)[1] in\
            configdata["filetypes"]["extensions_to_ignore"]) or\
           (entry.name.lower() in configdata["filetypes"]["files_to_ignore"]):
            continue

        if not index_data.objects.filter(name__iexact=entry.name.title(),
                                         fqpndirectory=webpath.lower(),
                                         ignore=False).exists():
                #   Item does not exist
            add_entry(entry, webpath)
        else:
            update_entry(entry, webpath)

        count += 1

    if index_data.objects.values("id").filter(fqpndirectory=webpath.lower(),
                                              ignore=False).count() != count:
        print("Running Validate")
        validate_database(dir_to_scan)
    return webpath.replace(os.sep, r"/")

DF_VDBASE = ["sortname", "lastscan", "lastmod", "size"]
def validate_database(dir_to_scan):
    """
    validate the data base
    """
    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
    fqpn = fqpn.replace("//", "/")
    webpath = fqpn.replace(configdata["locations"]["albums_path"], "")
    temp = get_filtered(get_defered(index_data, DF_VDBASE),
                        {'fqpndirectory':webpath, 'ignore':False})
    print("validate triggered :", dir_to_scan)
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

if __name__ == '__main__':
    from config import configdata
    import config
    cfg_path = os.path.abspath(r"../cfg")
    config.load_data(os.path.join(cfg_path, "paths.ini"))
    config.load_data(os.path.join(cfg_path, "settings.ini"))
    config.load_data(os.path.join(cfg_path, "filetypes.ini"))
    import doctest
    doctest.testmod()
else:
    from frontend.config import configdata
