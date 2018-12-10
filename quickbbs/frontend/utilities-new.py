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
import html

from PIL import Image
import fitz
import scandir

from frontend.database import check_dup_thumbs
from frontend.database import (validate_database)
from quickbbs.models import (index_data, Thumbnails_Files, Thumbnails_Archives,
                             Thumbnails_Dirs)
from django.core.exceptions import MultipleObjectsReturned
import logging
log = logging.getLogger(__name__)

import frontend.archives3 as archives

PY2 = sys.version_info[0] < 3

if PY2:
    from exceptions import IOError


def ensures_endswith(string_to_check, value):
    if not string_to_check.endswith(value):
        #string_to_check = "%s%s" % (string_to_check, value)
        string_to_check += value
    return string_to_check

def sort_order(request, context):
    """
    Grab the sort order from the request (cookie)
    and apply it to the session, and to the context for the web page.

    Args:
        request (obj) - The request object
        context (dict) - The dictionary for the web page template

    Returns:
        obj::
            The request object
        dict::
            The context dictionary

    Raises:
        None

    Examples
    --------
    """
    if "sort" in request.GET:
        #   Set sort_order, since there is a value in the post
        # pylint: disable=E1101
        sort_value = int(request.GET["sort"], 0)
        request.session["sort_order"] = sort_value
        context["sort_order"] = sort_value
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
        uuid_obj = uuid.UUID(uuid_to_test, version=version)
    except :
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


def return_image_obj(fs_path, memory=False):
    """
    Given a Fully Qualified FileName/Pathname, open the image
    (or PDF) and return the PILLOW object for the image
    Fitz == py


    Args:
        fs_path (str) - File system path
        memory (bool) - Is this to be mapped in memory

    Returns:
        boolean::
            `True` if uuid_to_test is a valid UUID, otherwise `False`.

    Raises:
        obj::
            Pillow image object

    Examples
    --------
    """
    source_image = None
    if os.path.splitext(fs_path)[1][1:].lower() == u"pdf":
        pdf_file = fitz.open(fs_path)
        pdf_page = pdf_file.loadPage(0)
        pix = pdf_page.getPixmap(matrix=fitz.Identity,
                                 alpha=True)

        try:
            source_image = Image.open(BytesIO(pix.getPNGData()))
        except UserWarning:
            print ("UserWarning!")
            source_image = None
    else:
        if not memory:
            source_image = Image.open(fs_path)
        else:
            try:# fs_path is a byte stream
                source_image = Image.open(BytesIO(fs_path))
            except IOError:
                print("IOError")
                log.debug("PIL was unable to identify as an image file")
            except UserWarning:
                print ("UserWarning!")
                source_image = None
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
    if source_image == None:
        return None

    image_data = BytesIO()
    source_image.thumbnail((size, size), Image.ANTIALIAS)
    try:
        source_image.save(fp=image_data,
                          format=configdata["filetypes"][fext][2].strip(),
                          optimize=True)
    except IOError:
        source_image = source_image.convert('RGB')
        source_image.save(fp=image_data,
                          format="JPEG",#configdata["filetypes"][fext][2].strip(),
                          optimize=True
                          )

    image_data.seek(0)
    return image_data.getvalue()

def read_from_disk(dir_to_scan, skippable=False):
    """
    Pass in FQFN, and the database stores the path as the URL path.
    """
    def recovery_from_multiple(fqpndirectory, uname):
        """
        eliminate any duplicates
        """
        dataset = index_data.objects.filter(
            name=uname.title(), fqpndirectory=fqpndirectory.lower(),
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
        fname_lower = sd_entry.name.lower()
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
                defaults={"uuid":uuid_entry,
                          "FilePath":webpath,
                          "FileName":fname,
                          "is_pdf":test_extension(fname_lower, ['pdf']),
                          "is_image":test_extension(fname_lower,
                                    configdata["filetypes"]["graphic_fts"]),
                          })[0]
            return db_entry
        return None

    def return_disk_listing(fqpn):
        data = []
        for entry in scandir.scandir(fqpn):

            titlecase = entry.name.title()#.strip()
            unescaped = html.unescape(titlecase)
            lower_filename = entry.name.lower()#.strip()

            if (lower_filename in configdata["filetypes"]["files_to_ignore"]):
                continue

            if (not entry.is_dir and
                not(os.path.splitext(lower_filename)[1][1:] in configdata["filetypes"].keys())):
                print ("Unidentified File Type: %s" % entry.name)

            if titlecase != unescaped:
               new_lower_filename = unescaped.lower()
               new_titlecase = unescaped.title()
               os.rename(os.path.join(fqpn, titlecase), os.path.join(fqpn, new_titlecase))
               lower_filename = new_lower_filename
               titlecase = new_titlecase


            if '/' in titlecase:
               new_lower_filename = lower_filename.replace("/", "_")
               new_titlecase = titlecase.replace("/", "_")
               os.rename(os.path.join(fqpn, titlecase), os.path.join(fqpn, new_titlecase))
               lower_filename = new_lower_filename
               titlecase = new_titlecase

            if ':' in titlecase:
               new_lower_filename = lower_filename.replace(":", "_")
               new_titlecase = titlecase.replace(":", "_")
               os.rename(os.path.join(fqpn, titlecase), os.path.join(fqpn, new_titlecase))
               lower_filename = new_lower_filename
               titlecase = new_titlecase

            if '#' in titlecase:
               new_lower_filename = lower_filename.replace("#", "_")
               new_titlecase = titlecase.replace("#", "_")
               os.rename(os.path.join(fqpn, titlecase), os.path.join(fqpn, new_titlecase))
               lower_filename = new_lower_filename
               titlecase = new_titlecase


#            if entry.is_dir():
#                data.append(titlecase)
#            elif os.path.splitext(lower_filename)[1][1:] in configdata["filetypes"].keys():
            data.append(titlecase)
        return data

###############################
    # Read_from_disk - main
    #
    # rewrite to use update_or_create? - No the logic doesn't work.

    # Get_or_create, could work for the read_from_disk main.

    # get all the filenames, and pass into update.

    # so that update can if not filename in listing, to check for deleted files.
    print ("Skippable - ", skippable)
    dir_to_scan = dir_to_scan.strip()
    fqpn = (configdata["locations"]["albums_path"] + dir_to_scan).replace("//", "/")
    webpath = fqpn.lower().replace(
        configdata["locations"]["albums_path"].lower(),
        "")
    if not os.path.exists(fqpn):
        print ("%s does not exist" % fqpn)
        return None

    rawdir = webpath.lower().replace(configdata["locations"]["albums_path"]+"/albums","")
    dirpath = os.path.split(rawdir)[0:-1][0]
    dirname = rawdir.lower().replace(dirpath,"")[1:]
    dirdata = index_data.objects.filter(fqpndirectory=dirpath.lower(), name=dirname.title(), ignore=False).exclude(directory=None, file_tnail=None, archives=None)

    existing_data = index_data.objects.filter(fqpndirectory=dir_to_scan.lower())

    loaded = False
    while not loaded:
        try:
            disk_data_scan = return_disk_listing(fqpn)
            loaded = True
        except StopIteration:
            pass

    existing_data_size = index_data.objects.filter(fqpndirectory=dir_to_scan.lower()).count()
    if existing_data_size > len(disk_data_scan):
        print ("existing size %s       on disk %s" % (existing_data_size, len(disk_data_scan)))
        for entry in existing_data:
            if not entry.name.title().strip() in disk_data_scan:
                 print("Deleting %s" % entry.name)
                 entry.delete()
        skippable = False
        print ("existing size, skippable > disk data scan = False")
    elif len(disk_data_scan) > existing_data_size:
        print ("Disk data scan > existing size, skippable = False")
        skippable = False

#     if (existing_data == len(disk_data_array) and (time.time() - dirdata[0].lastscan < 60)):
#         print ("Existing Data appears to be same size as current record")
#     else:
#         print ("Count mismatch, or expired [%s, %s)" % (existing_data, len(disk_data_array)))
    # if dirdata:
#         if (existing_data != 0 and (time.time() - dirdata[0].lastscan < 60)):
#             print ("Existing Data %s" % existing_data)
#             print ("Time %s, lastscan %s, Time-lastscan %s" % (time.time(), dirdata[0].lastscan, time.time() - dirdata[0].lastscan))
#             return
#     else:
#         print ("No dirdata")
    #
    # Test with and without prefetch_related
    #
#    path_index_qs = index_data.objects.prefetch_related(
#        'archives', 'directory',
#        'file_tnail').filter(fqpndirectory=webpath.lower(),
#                             ignore=False)


#    count = 0  # Used as sanity check for Validate
#    for count, disk_data in enumerate(scandir.scandir(fqpn)):#disk_data_scan:#scandir.scandir(fqpn):
    for disk_data in scandir.scandir(fqpn):#disk_data_scan:#scandir.scandir(fqpn):
        filename = disk_data.name.title()
        lower_filename = disk_data.name.lower()
        fext = os.path.splitext(filename)[1].lower()

        if not fext[1:] in configdata["filetypes"].keys() and not disk_data.is_dir():
            print (fext[1:])
            continue
        elif configdata["filetypes"]["ignore_dotfiles"] and filename.startswith("."):
            continue
        elif (fext in configdata["filetypes"]["extensions_to_ignore"]) or\
           (lower_filename in configdata["filetypes"]["files_to_ignore"]):
            continue

        fs_item = os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               filename)

        if disk_data.is_dir():
            # dir[0] = Path, dir[1] = dirs, dir[2] = files
            if PY2:
                dirdata = scandir.walk(disk_data.path).next()
            else:
                #print (disk_data.path)
                dirdata = next(os.walk(disk_data.path))
                # get directory count, and file count for subdirectory

            numdirs = len(dirdata[1])
            numfiles = len(dirdata[2])
        else:
            numdirs = 0
            numfiles = 0

        force_save = False
        new_uuid = uuid.uuid4()
        try:
            ind_data, created = index_data.objects.update_or_create(
                name=filename,#.replace("#", "").strip(),
                fqpndirectory=webpath,
                ignore=False,
                defaults={'name':filename,#.replace("#", "").strip(),
                          'fqpndirectory':webpath,
                          'sortname':naturalize(filename),
                          'size':disk_data.stat()[stat.ST_SIZE],
                          'lastmod':disk_data.stat()[stat.ST_MTIME],
                          'numfiles':numfiles,
                          'numdirs':numdirs,
                          'lastscan':time.time()#disk_data.stat()[stat.ST_MTIME],
                          }
                )
        except MultipleObjectsReturned:
            print ("Multiple Objects Returned")
            index_data.objects.filter(
                name=filename,#.replace("#", ""),
                fqpndirectory=webpath).delete()
            ind_data, created = index_data.objects.update_or_create(
                name=filename,#.replace("#", ""),
                fqpndirectory=webpath,
                ignore=False,
                defaults={'name':filename,#.replace("#", ""),
                          'fqpndirectory':webpath,
                          'sortname':naturalize(filename),
                          'size':disk_data.stat()[stat.ST_SIZE],
                          'lastmod':disk_data.stat()[stat.ST_MTIME],
                          'numfiles':numfiles,
                          'numdirs':numdirs,
                          'lastscan':time.time()#disk_data.stat()[stat.ST_MTIME],
                          }
                )

        if ind_data.lastmod != disk_data.stat()[stat.ST_MTIME]:
            ind_data.lastmod = disk_data.stat()[stat.ST_MTIME]
            force_save = True

        if ind_data.file_tnail is None:
            ind_data.file_tnail = link_file_rec(disk_data, webpath, new_uuid)
            force_save = force_save or not ind_data.file_tnail is None

        if ind_data.directory is None:
            ind_data.directory = link_dir_rec(disk_data, webpath, new_uuid)
            force_save = force_save or not ind_data.directory is None

        if ind_data.archives is None:
            ind_data.archives = link_arc_rec(fs_item, webpath, new_uuid)
            force_save = force_save or not ind_data.archives is None

        if ind_data.count_subfiles == 0 and not ind_data.archives is None:
            archive_file = archives.id_cfile_by_sig(fs_item)
            archive_file.get_listings()
            ind_data.count_subfiles = len(archive_file.listings)
            force_save = True

        if created:
            ind_data.uuid = new_uuid
            force_save = True

        if not ind_data.archives is None:# and ind_data.directory is None and ind_data.file_tnail is None:
            # There is an archive
            ta_listings = Thumbnails_Archives.objects.filter(uuid=ind_data.uuid)
            if not ta_listings.count() == ind_data.count_subfiles:
                archive_file = archives.id_cfile_by_sig(os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               disk_data.name))
                archive_file.get_listings()
                for zipcount, entry in enumerate(archive_file.listings):
                    if not ta_listings.filter(page = zipcount).exists():
                        Thumbnails_Archives.objects.create(uuid = ind_data.uuid,
                            FileName = filename,#.replace("#",""),
                            FilePath = webpath,
                            page = zipcount,
                            FileSize = -1)


        if force_save:
            ind_data.save()

        if fext[1:] in configdata["filetypes"]["image_safe_files"] and skippable:
            break
        #count += 1
#    if index_data.objects.values("id").filter(fqpndirectory=webpath.lower(),
#                                              ignore=False).count() != count:
#        print("Running Validate")
#        validate_database(dir_to_scan)
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
