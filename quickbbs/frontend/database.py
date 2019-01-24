# coding: utf-8
"""
Database Specific Functions
"""
from __future__ import absolute_import, print_function, unicode_literals

import os
import sys
from frontend.config import configdata as configdata
from quickbbs.models import (index_data, Thumbnails_Archives, Thumbnails_Files,
                             Thumbnails_Dirs)
from django.core.exceptions import ValidationError


DF_VDBASE = ["sortname", "lastscan", "lastmod", "size"]
def validate_database(dir_to_scan):
    """
    validate the data base
    """
    print (sys._getframe().f_code.co_name)
    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(configdata["locations"]["albums_path"], dir_to_scan)
    fqpn = fqpn.replace("//", "/")
    webpath = fqpn.replace(configdata["locations"]["albums_path"], "")
    temp = get_filtered(index_data.objects,
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

def check_for_deletes():
    """
    Check to see if any deleted items exist, if so, delete them.
    """
    print (sys._getframe().f_code.co_name)
    deleted = index_data.objects.filter(delete_pending=True)
    if deleted.exists():
        print("Deleting old deleted records")
        deleted.delete()


SORT_MATRIX = {0:["-is_dir", "sortname"],
               1:["-is_dir", "lastmod", "sortname"],
               2:["-is_dir", "sortname"],
               }
#SORT_MATRIX = {0:["sortname"],
#               1:["lastmod", "sortname"],
#               2:["sortname"]}

def get_values(database, values):
    """
        Fetch specific database values only from the database
    """
#    print (sys._getframe().f_code.co_name)
    #https://stackoverflow.com/questions/5903384
    return database.objects.values(*values)

# def get_defered(database, defers):
#     """
#         get defered values from the database
#     """
#     #https://stackoverflow.com/questions/5903384
#     return database.objects.defer(*defers)

def get_filtered(queryset, filtervalues):
    """
        Apply a filter to the queryset
    """
#    print (sys._getframe().f_code.co_name)
    #https://stackoverflow.com/questions/5903384
    return queryset.filter(**filtervalues)

def get_db_files(sorder, fpath):
    """
        Fetch specific database values only from the database
    """
 #   print (sys._getframe().f_code.co_name)
    index = index_data.objects.filter(fqpndirectory=fpath.lower().strip(),
                                      ignore=False,delete_pending=False).order_by(
                                          *SORT_MATRIX[sorder])
    return index

#       if index_data.objects.filter(name__iexact=entry.name.title(),
#                                     fqpndirectory=webpath,
#                                     ignore=False).count() > 1:
#            print("Recovery from Multiple starting for %s" % entry.name)
#            recovery_from_multiple(webpath, entry.name)
#            add_entry(entry, webpath)
#            return

def check_dup_thumbs(uuid_to_check, page=0):
    """
    Eliminate any duplicates in the Thumbnail Databases

    Parameters
    ----------
    uuid : str - The uuid of the index Filerec
    page : int - The page number of the archive file that is being examined


    Examples
    --------
    check_dup_thumbs(uuid)

    check_dup_thumbs(uuid, page=4)
    """
    print (sys._getframe().f_code.co_name)
    indexrec = index_data.objects.filter(uuid=str(uuid_to_check).strip(), ignore=False)[0]
    qset = None
    if indexrec.file_tnail != None:
        qset = Thumbnails_Files.objects.filter(uuid=indexrec.uuid).exclude(
            id=indexrec.file_tnail.id)

    if indexrec.directory != None:
        qset = Thumbnails_Dirs.objects.filter(uuid=indexrec.uuid).exclude(
            id=indexrec.directory.id)

    if indexrec.archives != None:
        qset = Thumbnails_Archives.objects.filter(
            uuid=indexrec.uuid,
            page=page).exclude(
                id=indexrec.archives.id)

#    if qset != None and qset.count() > 0:
#        qset.delete()
    if qset.count() > 0:
        qset.delete()
    return None

def get_xth_image(database, positional=0, filters=[]):
    """
    Return the xth image from the database, using the passed filters

    Parameters
    ----------

    database : object - The django database handle

    positional : int - 0 is first, if positional is greater than the # of
                 records, then it is reset to the count of records

    filters : dictionary of filters


    Returns:
        boolean::
            If successful the database record in question,
                    otherwise returns None

    Examples
    --------
    return_img_attach("test.png", img_data)
"""
    count = database.objects.filter(**filters).exclude(file_tnail=None).count()
    if 0 < positional > count:
        # outside of possible ranges
        if positional < 0:
            print ("Setting lower value")
            positional = 0
        else:
            print ("Setting higher value")
            positional = count
    try:
        return database.objects.filter(**filters).exclude(file_tnail=None)[positional]
    except IndexError:
        return None

    #files = database.objects.filter(**filters).exclude(file_tnail=None)
#    if files:
#        if positional > count:
#            positional = count
#        elif positional < 0:
#            positional = 0

#        return files[positional]
#    else:
#        return None
