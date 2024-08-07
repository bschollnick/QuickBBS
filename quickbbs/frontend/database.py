"""
Database Specific Functions
"""

from typing import Iterator  # , Optional, Union, TypeVar, Generic

from quickbbs.models import IndexData

DF_VDBASE = ["sortname", "lastscan", "lastmod", "size"]

# def validate_database(dir_to_scan):
#     """
#     validate the data base
#
#     potentially depreciated due to watchdog and v3
#     """
#     dir_to_scan = dir_to_scan.strip()
#     fqpn = os.path.join(settings.ALBUMS_PATH, dir_to_scan)
#     fqpn = fqpn.replace("//", "/")
#     webpath = fqpn.replace(settings.ALBUMS_PATH, "")
#     temp = get_filtered(IndexData.objects,
#                         {'fqpndirectory': webpath, 'ignore': False})
#     print("validate triggered :", dir_to_scan)
#     for entry in temp:
#         if not os.path.exists(os.path.join(fqpn, entry.name)) or \
#                 os.path.splitext(entry.name.lower().strip())[1] in \
#                 settings.EXTENSIONS_TO_IGNORE or \
#                 entry.name.lower().strip() in \
#                 settings.FILES_TO_IGNORE:
#             entry.ignore = True
#             entry.delete_pending = True
#             entry.save()
#     check_for_deletes()
#
#
# def check_for_deletes():
#     """
#     Check to see if any deleted items exist, if so, delete them.
#
#     potentially depreciated due to watchdog and v3
#     """
#     #    print(sys._getframe().f_code.co_name)
#     deleted = IndexData.objects.filter(delete_pending=True)
#     if deleted.exists():
#         print("Deleting old deleted records")
#         deleted.delete()


SORT_MATRIX = {
    0: ["-filetype__is_dir", "name_sort", "lastmod"],
    1: ["-filetype__is_dir", "lastmod", "name_sort"],
    2: ["-filetype__is_dir", "name_sort"],
}


def get_db_files(sorder, fpath) -> Iterator[IndexData]:
    """
    Fetch the data from the database, and then order by the current users sort
    """
    index = (
        IndexData.objects.select_related("filetype")
        .exclude(ignore=True)
        .exclude(delete_pending=True)
        .filter(fqpndirectory=fpath.lower().strip())
        .order_by(*SORT_MATRIX[sorder])
    )
    return index


# def return_offset_uuid(sorder, fpath, tuuid):
#     """
#         Fetch specific database values only from the database
#
#             potentially depreciated due to watchdog and v3
#     """
#     entries = IndexData.objects.exclude(ignore=True).exclude(delete_pending=True).filter(
#         fqpndirectory=fpath.lower().strip()).order_by(*SORT_MATRIX[sorder])
#     tpk = entries.filter(uuid=tuuid.strip())[0].pk
#     count = entries.filter(pk__lte=tpk).count() - 1
#     return count


# def check_dup_thumbs(uuid_to_check, page=0):
#     """
#     Eliminate any duplicates in the Thumbnail Databases
#
#     potentially depreciated with watchdog and v3 design.
#
#     Parameters
#     ----------
#     uuid_to_check : str - The uuid of the index Filerec
#     page : int - The page number of the archive file that is being examined
#
#
#     Examples
#     --------
#     check_dup_thumbs(uuid)
#
#     check_dup_thumbs(uuid, page=4)
#     """
#     indexrec = (
#         IndexData.objects.exclude(delete_pending=True)
#         .exclude(ignore=True)
#         .filter(uuid=str(uuid_to_check).strip())[0]
#     )
#     qset = None
#     if indexrec.file_tnail is None:
#         qset = Thumbnails_Files.objects.filter(uuid=indexrec.uuid).exclude(
#             id=indexrec.file_tnail_id
#         )
#
#     if indexrec.directory is None:
#         qset = Thumbnails_Dirs.objects.filter(uuid=indexrec.uuid).exclude(
#             id=indexrec.directory_id
#         )
#
#     if indexrec.archives is None:
#         qset = Thumbnails_Archives.objects.filter(
#             uuid=indexrec.uuid, page=page
#         ).exclude(id=indexrec.archives_id)
#
#     if qset is None and qset.count() > 0:
#         qset.delete()


def get_xth_image(database, positional=0, filters=None) -> Iterator[IndexData]:
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

        boolean::
            If successful the database record in question,
                    otherwise returns None

    Examples
    --------
    return_img_attach("test.png", img_data)
    """
    if filters is None:
        filters = []

    data = (
        database.objects.select_related("filetype")
        .filter(**filters)
        .exclude(filetype__is_image=False)
        .exclude(ignore=True)
        .exclude(delete_pending=True)
    )
    try:
        # exact match
        return data[positional]
    except IndexError:  # No matching position was found
        # it has to be either too high (greater than length), or less than 0.
        count = data.count()
        if positional > count:  # The requested index is too high
            return data[count]
        # else, return None, because positional has to be 0 or less.
    return None
