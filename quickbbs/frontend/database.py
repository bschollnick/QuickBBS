"""
Database Specific Functions
"""
import os
#sdimport sys
#from django.core.exceptions import ValidationError
# from frontend.config import configdata
from quickbbs.models import (index_data, Thumbnails_Archives, Thumbnails_Files,
                             Thumbnails_Dirs)
from django.conf import settings


DF_VDBASE = ["sortname", "lastscan", "lastmod", "size"]

def validate_database(dir_to_scan):
    """
    validate the data base
    """
#    print(sys._getframe().f_code.co_name)
    dir_to_scan = dir_to_scan.strip()
    fqpn = os.path.join(settings.ALBUMS_PATH, dir_to_scan)
    fqpn = fqpn.replace("//", "/")
    webpath = fqpn.replace(settings.ALBUMS_PATH, "")
    temp = get_filtered(index_data.objects,
                        {'fqpndirectory':webpath, 'ignore':False})
    print("validate triggered :", dir_to_scan)
    for entry in temp:
        if not os.path.exists(os.path.join(fqpn, entry.name)) or \
            os.path.splitext(entry.name.lower().strip())[1] in\
                settings.EXTENSIONS_TO_IGNORE or \
                entry.name.lower().strip() in\
                settings.FILES_TO_IGNORE:
            entry.ignore = True
            entry.delete_pending = True
            entry.save()
    check_for_deletes()

def check_for_deletes():
    """
    Check to see if any deleted items exist, if so, delete them.
    """
#    print(sys._getframe().f_code.co_name)
    deleted = index_data.objects.filter(delete_pending=True)
    if deleted.exists():
        print("Deleting old deleted records")
        deleted.delete()


SORT_MATRIX = {0:["-filetype__is_dir", "sortname", "lastmod"],
               1:["-filetype__is_dir", "lastmod", "sortname"],
               2:["-filetype__is_dir", "sortname"],
               }

def get_values(database, values):
    """
        Fetch specific database values only from the database
    """
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
    #https://stackoverflow.com/questions/5903384
    return queryset.exclude(ignore=True).exclude(delete_pending=True).filter(**filtervalues)

def get_db_files(sorder, fpath):
    """
        Fetch specific database values only from the database
    """
    index = index_data.objects.exclude(ignore=True).exclude(delete_pending=True).filter(
        fqpndirectory=fpath.lower().strip()).order_by(*SORT_MATRIX[sorder])
    return index

def return_offset_uuid(sorder, fpath, tuuid):
    """
        Fetch specific database values only from the database
    """
    entries = index_data.objects.exclude(ignore=True).exclude(delete_pending=True).filter(
        fqpndirectory=fpath.lower().strip()).order_by(*SORT_MATRIX[sorder])
    tpk = entries.filter(uuid=tuuid.strip())[0].pk
    count = entries.filter(pk__lte=tpk).count() - 1
        #answer = user.answer_set.filter(question=question).get()
    # return user.answer_set.filter(pk__lte=answer.pk).count() - 1

    return count

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
#    print(sys._getframe().f_code.co_name)
    indexrec = index_data.objects.filter(uuid=str(uuid_to_check).strip(), ignore=False)[0]
    qset = None
    if indexrec.file_tnail is None:
        qset = Thumbnails_Files.objects.filter(uuid=indexrec.uuid).exclude(
            id=indexrec.file_tnail_id)

    if indexrec.directory is None:
        qset = Thumbnails_Dirs.objects.filter(uuid=indexrec.uuid).exclude(
            id=indexrec.directory_id)

    if indexrec.archives is None:
        qset = Thumbnails_Archives.objects.filter(
            uuid=indexrec.uuid,
            page=page).exclude(
                id=indexrec.archives_id)

    if qset is None and qset.count() > 0:
        qset.delete()

#    if qset.count() > 0:
#        qset.delete()
    #return None

def get_xth_image(database, positional=0, filters=None):
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
    if filters is None:
        filters = []
    try:
        # exact match
        return database.objects.filter(**filters).exclude(filetype__is_image=False).exclude(ignore=True).exclude(delete_pending=True)[positional]
    except IndexError: # No matching position was found
        # it has to be either too high (greater than length), or less than 0.
        count = database.objects.filter(**filters).exclude(filetype__is_image=False).exclude(ignore=True).exclude(delete_pending=True).count()
        if positional > count:    # The requested index is too high
            return database.objects.filter(**filters).exclude(filetype__is_image=False).exclude(ignore=True).exclude(delete_pending=True)[count]
        #else, return None, because positional has to be 0 or less.
    return None
