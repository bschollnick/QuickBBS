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
import frontend.constants as constants
import fitz
import scandir
import frontend
import frontend.ftypes as ftypes
from frontend.database import check_dup_thumbs
from frontend.database import (validate_database)
from quickbbs.models import (index_data, Thumbnails_Files, Thumbnails_Archives,
                             Thumbnails_Dirs, filetypes)
from django.core.exceptions import MultipleObjectsReturned
#from constants import *
import logging
log = logging.getLogger(__name__)

import frontend.archives3 as archives

def rename_file(old_filename, new_filename):
    try:
        os.rename(old_filename, new_filename)
    except OSError:
        pass

def get_lm_in_dir(fqpn):
    """
    return the directory listing in reverse last modified (oldest -> Newest)
    as list of scandir items.
    """
    lastmod_list = sorted(scandir.scandir(fqpn),
                          key=lambda x: x.stat().st_mtime,
                          reverse=True)
#    print(dir(lastmod_list))
    for data in lastmod_list:
        if not data.name.startswith("."):
            return data.name.title()

def ensures_endswith(string_to_check, value):
    if not string_to_check.endswith(value):
        string_to_check = "%s%s" % (string_to_check, value)
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
#    print ("test_ext: ",os.path.splitext(name)[1].lower() in ext_list, os.path.splitext(name)[1].lower(), ext_list)
    return os.path.splitext(name)[1].lower() in ext_list

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


def multiple_replace(dict, text):#, compiled):
    # Create a regular expression  from the dictionary keys

    # For each match, look-up corresponding value in dictionary
    return constants.regex.sub(lambda mo: dict[mo.string[mo.start():mo.end()]], text)

def return_disk_listing(fqpn, enable_rename = False):

    data = {}
    data_list = []
    webpath = (fqpn.lower().replace(configdata["locations"]["albums_path"].lower(),
                                    "")).replace("//", "/")
    for entry in scandir.scandir(fqpn):
        titlecase = entry.name.title()#.strip()
        unescaped = html.unescape(titlecase)
        lower_filename = entry.name.lower()#.strip()
        animated = False
        if entry.is_dir():
            fext = ".dir"
        else:
            fext = os.path.splitext(lower_filename)[1]
#                try:
#                    if ftypes.FILETYPE_DATA[fext]["is_image"]:
#                        animated = Image.open(os.path.join(fqpn, entry.name)).is_animated
#                except:
#                    pass

        if fext == "":
            fext = ".none"
#        print (dir(ftypes))
        if fext not in ftypes.FILETYPE_DATA:
#            print ("Skipping, not in filetypes - ", titlecase)
            continue
        elif (fext in configdata["filetypes"]["extensions_to_ignore"]) or\
           (lower_filename in configdata["filetypes"]["files_to_ignore"]):
            continue
#            elif not fext[1:] in configdata["filetypes"].keys() and not entry.is_dir():
#                print (fext)
#                continue

        elif configdata["filetypes"]["ignore_dotfiles"] and lower_filename.startswith("."):
            continue

        if enable_rename:
            original_filename = titlecase
            if titlecase != unescaped:
                lower_filename = unescaped.lower()
                titlecase = unescaped.title()

            after_filename = multiple_replace(constants.replacements, lower_filename)#, regex)
            if after_filename != lower_filename:
                lower_filename = after_filename
                titlecase = after_filename.title()

            if titlecase != original_filename:
                rename_file(os.path.join(fqpn, original_filename),
                            os.path.join(fqpn, titlecase))

            data[titlecase] = {"filename":titlecase,
#        data_list.append( {"filename":titlecase,
                           "lower_filename":lower_filename,
 #                          "fqpndirectory":webpath,
                           "path":os.path.join(fqpn, titlecase),
                           'sortname':naturalize(titlecase),
                           'size':entry.stat()[stat.ST_SIZE],
                           'lastmod':entry.stat()[stat.ST_MTIME],
#                               'numfiles':numfiles,
#                               'numdirs':numdirs,
                           'is_dir':fext == ".dir",
                           'is_file':fext != ".dir",
                           'is_archive':ftypes.FILETYPE_DATA[fext]["is_archive"],
                           'is_image':ftypes.FILETYPE_DATA[fext]["is_image"],
#                              'is_animated':animated

#                           'lastscan':time.time(),
#                           'filetype':filetypes(fileext=fext)
                           }
                    #)
    return data
    return #data_list

def read_from_disk(dir_to_scan, skippable=True):
    """
    Pass in FQFN, and the database stores the path as the URL path.
    """

#     def recovery_from_multiple(fqpndirectory, uname):
#         """
#         eliminate any duplicates
#         """
#         dataset = index_data.objects.filter(
#             name=uname.title(), fqpndirectory=fqpndirectory.lower(),
#             ignore=False)
#         dataset.delete()

    def link_arc_rec(fs_name, webpath, uuid_entry, page=0):
        if test_extension(fs_name,
                          configdata["filetypes"]["archive_fts"]):
            fname = os.path.basename(fs_name).title()#.replace("#", "").\
#                replace("?", "").strip()
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
                               sd_entry[filename]["filename"])#.name)
        if sd_entry[filename]["is_dir"]:
            fname = os.path.basename(fs_name).title()#.replace("#", "").\
#                replace("?", "").strip()
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
                               sd_entry[filename]["filename"])#.name)
        if (test_extension(fs_name,
                           configdata["filetypes"]["graphic_fts"]) or\
                           test_extension(fs_name,
                                          configdata["filetypes"]["pdf_fts"])\
                                          and sd_entry[filename]["is_file"] and not\
                                          sd_entry[filename]["is_dir"]):
            fname = os.path.basename(fs_name).title()#.replace("#", "").\
#                replace("?", "").strip()

            db_entry = Thumbnails_Files.objects.update_or_create(
                uuid=uuid_entry,
                FilePath=webpath,
                FileName=fname,
                defaults={"uuid":uuid_entry,
                          "FilePath":webpath,
                          "FileName":fname,
                          "is_pdf":test_extension(fname, ['.pdf']),
                          "is_image":test_extension(fname,
                                    configdata["filetypes"]["graphic_fts"]),
                          })[0]
            return db_entry
        return None

###############################
    # Read_from_disk - main
    #
    # rewrite to use update_or_create? - No the logic doesn't work.

    # Get_or_create, could work for the read_from_disk main.

    # get all the filenames, and pass into update.

    # so that update can if not filename in listing, to check for deleted files.
    lastmoded = ""
    dir_to_scan = dir_to_scan.strip().lower()
    fqpn = (configdata["locations"]["albums_path"] + dir_to_scan).replace("//", "/")
    webpath = fqpn.lower().replace(
        configdata["locations"]["albums_path"].lower(),
        "")
    if not os.path.exists(fqpn):
        print ("%s does not exist" % fqpn)
        return None

    loaded = False
    while not loaded:
        try:
            diskstore = return_disk_listing(fqpn, enable_rename=True)
            disk_count = len(diskstore)
            loaded = True
        except StopIteration:
            pass

    # existing_data is from the database
    existing_data = index_data.objects.filter(fqpndirectory=dir_to_scan)
    existing_data_size = existing_data.count()

    if existing_data_size > disk_count:
        #print ("existing size %s       on disk %s" % (existing_data_size,
        #                                              disk_count))
        for entry in existing_data:
            if not entry.name in diskstore:    # name is already title cased
                 print("Deleting %s" % entry.name)
                 entry.delete()
        skippable = False
    #    print ("existing size, skippable > disk data scan = False")
    #    print ("Existing # %s, disk scan %s" % (existing_data_size, disk_count))

    elif disk_count > existing_data_size:
     #   print ("Disk data scan > existing size, skippable = False")
      #  print ("Existing # %s, disk scan %s" % (existing_data_size, disk_count))
        skippable = False

    if existing_data_size > 0 and existing_data_size is not None:
        try:
            lastmoded = existing_data.order_by("-lastmod")[0].name
            if not lastmoded == get_lm_in_dir(fqpn):
                #print ("Unable to skip")
                skippable = False
        except IndexError:
            lastmoded = ""
            skippable = False
            print ("Setting skipable to False")
#    print ("Database, last mod - ", lastmoded)
#    print ("disk, last mod - ", get_lm_in_dir(fqpn))
    if skippable:
        return webpath.replace(os.sep, r"/")

    for filename, filedata in diskstore.items():
        disk_data = {}
        disk_data[filename] = filedata
        animated = False
        if disk_data[filename]["is_dir"]:
            fext = ".dir"
        else:
            fext = os.path.splitext(disk_data[filename]["lower_filename"])[1]
            if fext == "":
                fext = ".none"
            if ftypes.FILETYPE_DATA[fext]["is_image"]:
                try:
                    animated = Image.open(os.path.join(fqpn, filename)).is_animated
                except AttributeError:
                    pass
        fs_item = os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               filename)

        force_save = False
        numdirs = 0
        numfiles = 0
        if (disk_data[filename]["is_dir"]):
            dirdata = next(os.walk(disk_data[filename]["path"]))
                # dir[0] = Path, dir[1] = dirs, dir[2] = files
                # get directory count, and file count for subdirectory
#            fext = '.dir'
            numdirs = len(dirdata[1])
            numfiles = len(dirdata[2])

        new_uuid = uuid.uuid4()
        try:
            ind_data, created = index_data.objects.update_or_create(
                name=filename,#.replace("#", "").strip(),
                fqpndirectory=webpath,
                ignore=False,
                defaults={'name':filename,#.replace("#", "").strip(),
#                          'file_ext':fext,
                          'fqpndirectory':webpath,
                          'sortname':naturalize(filename),
                          'size':disk_data[filename]["size"],
                          'lastmod':disk_data[filename]["lastmod"],
                          'numfiles':numfiles,
                          'numdirs':numdirs,
                          'is_dir':disk_data[filename]["is_dir"],
                          'is_archive':disk_data[filename]["is_archive"],
                          'is_image':ftypes.FILETYPE_DATA[fext]["is_image"],
                          'is_pdf':ftypes.FILETYPE_DATA[fext]["is_image"],
                          'lastscan':time.time(),
                          'filetype':filetypes(fileext=fext),
                          'is_animated':animated
                          }
                )
        except MultipleObjectsReturned:
            print ("Multiple Objects Returned")
            index_data.objects.filter(
                name=filename,
                fqpndirectory=webpath).delete()
            ind_data, created = index_data.objects.update_or_create(
                name=filename,
                fqpndirectory=webpath,
                ignore=False,
                defaults={'name':filename,#.replace("#", "").strip(),
#                          'file_ext':fext,
                          'fqpndirectory':webpath,
                          'sortname':naturalize(filename),
                          'size':disk_data[filename]["size"],
                          'lastmod':disk_data[filename]["lastmod"],
                          'numfiles':numfiles,
                          'numdirs':numdirs,
#                          'is_dir':disk_data.is_dir(),
                          'is_dir':fext == ".dir",
                          'is_archive':disk_data[filename]["is_archive"],
                          'is_image':ftypes.FILETYPE_DATA[fext]["is_image"],
                          'lastscan':time.time(),
                          'filetype':filetypes(fileext=fext),
                          'is_animated':animated
                          }
                )
        if ind_data.filetype == filetypes(fileext=None):
            #print ("Updating due to file_ext")
            force_save = True

        if ind_data.lastmod != disk_data[filename]["lastmod"]:#.stat()[stat.ST_MTIME]:
            ind_data.lastmod = disk_data[filename]["lastmod"]
            #print ("LastMod update")
            force_save = True

#        print("file_tnail is %s" % disk_data.name)
#        print (fext)
        if ind_data.file_tnail is None and (ftypes.FILETYPE_DATA[fext]["is_image"] or
            fext in ['.pdf', '.Pdf']):
            # if is image or PDF, then link to file rec
            ind_data.file_tnail = link_file_rec(disk_data, webpath, new_uuid)
#            force_save = force_save or not ind_data.file_tnail is None
            #print ("Tnail update")
            force_save = True
        elif ind_data.directory is None and fext==".dir":
            # is directory link as directory
            ind_data.directory = link_dir_rec(disk_data, webpath, new_uuid)
            #print ("dir update")
            force_save = True
        elif ind_data.archives is None and ftypes.FILETYPE_DATA[fext]["is_archive"]:
            # is archive, link as archive
            ind_data.archives = link_arc_rec(fs_item, webpath, new_uuid)
            #print ("archives update")
            force_save = True
        elif ind_data.archives is not None:
            # There is an archive, and the subfile count does not match, update count
            # and listings
            ta_listings = Thumbnails_Archives.objects.filter(uuid=ind_data.uuid)
            if ta_listings.count() != ind_data.count_subfiles:
                archive_file = archives.id_cfile_by_sig(os.path.join(configdata["locations"]["albums_path"],
                               webpath[1:],
                               filename))
                archive_file.get_listings()
                ind_data.count_subfiles = ta_listings.count()
                for zipcount, entry in enumerate(archive_file.listings):
                    if not ta_listings.filter(page = zipcount).exists():
                        Thumbnails_Archives.objects.create(uuid = ind_data.uuid,
                            FileName = filename,#.replace("#",""),
                            FilePath = webpath,
                            page = zipcount,
                            FileSize = -1)

#         elif ind_data.count_subfiles == 0 and ftypes.FILETYPE_DATA[fext]["is_archive"]:
#             # it's an archive, with no files listed, get count of files
#             archive_file = archives.id_cfile_by_sig(fs_item)
#             archive_file.get_listings()
#             ind_data.count_subfiles = len(archive_file.listings)
#             #print ("subfiles update")
#             force_save = True

        if created or ind_data.uuid is None:
            ind_data.uuid = new_uuid
            #print ("Created update")
            force_save = True


        if force_save:
#            print ("Force saving")
            ind_data.save()

        if fext in configdata["filetypes"]["image_safe_files"] and skippable:
            break
        #count += 1
#    if index_data.objects.values("id").filter(fqpndirectory=webpath.lower(),
#                                              ignore=False).count() != count:
#        print("Running Validate")
#        validate_database(dir_to_scan)
    return webpath.replace(os.sep, r"/")


if __name__ == '__main__':
    from config import configdata, load_data
#    import config
    cfg_path = os.path.abspath(r"../../cfg")
    config.load_data(os.path.join(cfg_path, "paths.ini"))
    config.load_data(os.path.join(cfg_path, "settings.ini"))
    config.load_data(os.path.join(cfg_path, "filetypes.ini"))
    import doctest
    doctest.testmod()
else:
    from frontend.config import configdata
    print(sys.version)
