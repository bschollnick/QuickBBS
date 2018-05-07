# coding: utf-8
"""
Utilities for QuickBBS, the python edition.
"""
from __future__ import absolute_import, print_function, unicode_literals

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
import scandir

from frontend.database import check_dup_thumbs
from frontend.database import (validate_database)
from quickbbs.models import (index_data, Thumbnails_Files, Thumbnails_Archives,
                             Thumbnails_Dirs)
from django.core.exceptions import MultipleObjectsReturned

PY2 = sys.version_info[0] < 3

if PY2:
    from exceptions import IOError


def ensures_endswith(string_to_check, value):
    if not string_to_check.endswith(value):
        string_to_check = "%s%s" % (string_to_check, value)
    return string_to_check

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
        uuid_obj = uuid.UUID(uuid_to_test.strip(), version=version)
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


    def link_arc_rec(fs_name, webpath, uuid_entry, page=0):
        if test_extension(fs_name,
                          configdata["filetypes"]["archive_fts"]):
            fname = os.path.basename(fs_name).title().replace("#", "").\
                replace("?", "").strip()
            try:
                db_entry = Thumbnails_Archives.objects.update_or_create(
                    uuid=uuid_entry,
                    FilePath=webpath,
                    FileName=fname,
                    page=page,
                    defaults={"uuid":uuid_entry, "FilePath":webpath,
                              "FileName":fname, "page":page})[0]
            except MultipleObjectsReturned:
                check_dup_thumbs(uuid_entry, page)
                db_entry = Thumbnails_Archives.objects.update_or_create(
                    uuid=uuid_entry,
                    FilePath=webpath,
                    FileName=fname,
                    page=page,
                    defaults={"uuid":uuid_entry, "FilePath":webpath,
                              "FileName":fname, "page":page})[0]
            return db_entry
        return None

    def link_dir_rec(sd_entry, webpath, uuid_entry):
        fs_name = os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               sd_entry.name)
        if sd_entry.is_dir():
            fname = os.path.basename(fs_name).title().replace("#", "").\
                replace("?", "").strip()
            db_entry = Thumbnails_Dirs.objects.update_or_create(
                uuid=uuid_entry, FilePath=webpath, DirName=fname,
                defaults={"uuid":uuid_entry,
                          "FilePath":webpath,
                          "DirName":fname})[0]
            return db_entry
        return None

    def link_file_rec(sd_entry, webpath, uuid_entry):
        fs_name = os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               sd_entry.name)
        if (test_extension(fs_name,
                           configdata["filetypes"]["graphic_fts"]) or\
                           test_extension(fs_name,
                                          configdata["filetypes"]["pdf_fts"])\
                                          and sd_entry.is_file() and not\
                                          sd_entry.is_dir()):
            fname = os.path.basename(fs_name).title().replace("#", "").\
                replace("?", "").strip()
            db_entry = Thumbnails_Files.objects.update_or_create(
                uuid=uuid_entry,
                FilePath=webpath,
                FileName=fname,
                defaults={"uuid":uuid_entry, "FilePath":webpath,
                          "FileName":fname})[0]
            return db_entry
        return None

    def add_entry(disk_entry, webpath):
        """
        Add entry to the database
        """
#        print ("Add Entry, %s" % entry.name)
        if disk_entry.is_dir():
            # dir[0] = Path, dir[1] = dirs, dir[2] = files
            if PY2:
                dirdata = scandir.walk(disk_entry.path).next()
            else:
                dirdata = next(os.walk(disk_entry.path))
            # get directory count, and file count for subdirectory
        else:
            dirdata = ("", [], [])
        new_uuid = uuid.uuid4()
        webpath = webpath.replace(os.sep, r"/").lower()
#        fs_item = os.path.join(configdata["locations"]["albums_path"],
#                               webpath[1:],
#                               entry.name)
        index_data.objects.create(
            lastmod=disk_entry.stat()[stat.ST_MTIME],
            lastscan=time.time(),
            name=disk_entry.name.title().replace("#", "").replace("?", "").strip(),
            sortname=naturalize(disk_entry.name.title()),
            size=disk_entry.stat()[stat.ST_SIZE],
            fqpndirectory=webpath.replace(os.sep, r"/").lower(),
            parent_dir_id=0,
            numfiles=len(dirdata[2]),
            # The # of files in this directory
            numdirs=len(dirdata[1]),
            # The # of Children Directories in
            # this directory
            is_dir=disk_entry.is_dir(),
            is_pdf=test_extension(disk_entry.name.lower(), ['pdf']),
            is_image=test_extension(disk_entry.name.lower(),
                                    configdata["filetypes"]["graphic_fts"]),
            is_archive=test_extension(disk_entry.name.lower(),
                                      ['cbz', 'cbr', 'zip', 'rar']),
            uuid=new_uuid,
            ignore=False,
            delete_pending=False,
            file_tnail=link_file_rec(disk_entry, webpath, new_uuid),
            directory=link_dir_rec(disk_entry, webpath, new_uuid),
            archives=link_arc_rec(disk_entry.name, webpath, new_uuid)
            )

    def verify_value(original, new, change_dict, key):
        if original != new:
            change_dict[key] = new
        return change_dict

    def update_entry(disk_entry, webpath):
        """
        Update the existing entry in the database
        """
        #entry_fqfn = os.path.join(os.path.realpath(dir_to_scan), uname)
        #changed = False
        if index_data.objects.filter(name__iexact=disk_entry.name.title(),
                                     fqpndirectory=webpath,
                                     ignore=False).count() > 1:
            print("Recovery from Multiple starting for %s" % disk_entry.name)
            recovery_from_multiple(webpath, disk_entry.name)
            add_entry(disk_entry, webpath)
            return

        # temp = index_data.objects.get_or_create()
        temp = index_data.objects.filter(
            name__iexact=disk_entry.name.title(),
            fqpndirectory=webpath.replace(os.sep, r"/").lower(),
            ignore=False)
        orig = temp[0]

        fs_item = os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               disk_entry.name)

        changed = {}
        #pkey = id

        # verify_value(original, new, change_dict, key):
        changed = verify_value(orig.name, disk_entry.name.title(), changed, "name")
        changed = verify_value(orig.sortname,
                               naturalize(disk_entry.name.title()),
                               changed,
                               "sortname")

        if orig.uuid is None:
            changed["uuid"] = uuid.uuid4()
            orig.uuid = changed["uuid"]

        if not os.path.exists(disk_entry.path):
            changed["delete_pending"] = True
            changed["ignore"] = True

        changed = verify_value(orig.size, disk_entry.stat()[stat.ST_SIZE],
                               changed, "size")

        changed = verify_value(orig.lastmod, disk_entry.stat()[stat.ST_MTIME], changed, "lastmod")
        changed = verify_value(orig.lastmod, disk_entry.stat()[stat.ST_MTIME], changed, "lastscan")

        t_ext = test_extension(
            disk_entry.name, configdata["filetypes"]["graphic_fts"])

        changed = verify_value(orig.is_image, t_ext, changed, "is_image")

        archive = test_extension(disk_entry.name.lower(),
                                 ['cbz',
                                  'cbr',
                                  'zip',
                                  'rar'])
        changed = verify_value(orig.is_archive, archive, changed, "is_archive")

        if disk_entry.is_dir():
            # dir[0] = Path, dir[1] = dirs, dir[2] = files
            if PY2:
                dirdata = scandir.walk(disk_entry.path).next()
            else:
                dirdata = next(os.walk(disk_entry.path))
                # get directory count, and file count for subdirectory

            changed = verify_value(orig.numdirs, len(dirdata[1]), changed, "numdirs")
            changed = verify_value(orig.numfiles, len(dirdata[2]), changed, "numfiles")


        if not orig.file_tnail:
            changed["file_tnail"] = link_file_rec(disk_entry, webpath, orig.uuid)

        if not orig.directory:
            changed["directory"] = link_dir_rec(disk_entry, webpath, orig.uuid)

        if not orig.archives:
            changed["archives"] = link_arc_rec(fs_item, webpath, orig.uuid)

        if changed != {}:
            changed["lastmod"] = disk_entry.stat()[stat.ST_MTIME]
            changed["lastscan"] = disk_entry.stat()[stat.ST_MTIME]
            temp.update(**changed)

###############################
    # Read_from_disk - main
    #
    # rewrite to use update_or_create? - No the logic doesn't work.

    # Get_or_create, could work for the read_from_disk main.

    # if .count() > 1:
        # validate_database
    # entry = get_or_create(defaults)
    # update_entry(entry)

    # Would reduce the # of database searches / retrievals.
    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
    fqpn = fqpn.replace("//", "/")
    webpath = fqpn.lower().replace(
        configdata["locations"]["albums_path"].lower(),
        "")
    if not os.path.exists(fqpn):
        print ("%s does not exist" % fqpn)
        return None

    count = 0  # Used as sanity check for Validate
    for disk_data in scandir.scandir(fqpn):

        if (os.path.splitext(disk_data.name)[1] in\
            configdata["filetypes"]["extensions_to_ignore"]) or\
           (disk_data.name.lower() in configdata["filetypes"]["files_to_ignore"]):
            continue

        index_qs = index_data.objects.filter(name__iexact=disk_data.name.title(),
                                             fqpndirectory=webpath.lower(),
                                             ignore=False)
#         if not index_data.objects.filter(name__iexact=entry.name.title(),
#                                          fqpndirectory=webpath.lower(),
#                                          ignore=False).exists():
        if not index_qs:
            #   Item does not exist
            add_entry(disk_data, webpath)
        else:
            try:
                update_entry(disk_data, webpath)
            except MultipleObjectsReturned:
                if index_qs[0].archives != None:
                    print ("\nMultiples detected--A\n")
                    check_dup_thumbs(index_qs[0].uuid, 0)
                else:
                    print ("\nMultiples detected--B\n")
                    check_dup_thumbs(index_qs[0].uuid, 0)
                update_entry(disk_data, webpath)

        count += 1

    if index_data.objects.values("id").filter(fqpndirectory=webpath.lower(),
                                              ignore=False).count() != count:
        print("Running Validate")
        validate_database(dir_to_scan)
    return webpath.replace(os.sep, r"/")


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
