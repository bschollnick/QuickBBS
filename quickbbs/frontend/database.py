"""
Database Specific Functions
"""
import os
from frontend.config import configdata as configdata
from quickbbs.models import index_data


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

def check_for_deletes():
    """
    Check to see if any deleted items exist, if so, delete them.
    """
    deleted = index_data.objects.filter(delete_pending=True)
    if deleted.exists():
        print("Deleting old deleted records")
        deleted.delete()


SORT_MATRIX = {0:["-is_dir", "sortname"],
               1:["-is_dir", "lastmod"],
               2:["-is_dir", "sortname"]}

def get_values(database, values):
    """
        Fetch specific database values only from the database
    """
    #https://stackoverflow.com/questions/5903384
    return database.objects.values(*values)

def get_defered(database, defers):
    """
        get defered values from the database
    """
    #https://stackoverflow.com/questions/5903384
    return database.objects.defer(*defers)

def get_filtered(queryset, filtervalues):
    """
        Apply a filter to the queryset
    """
    #https://stackoverflow.com/questions/5903384
    return queryset.filter(**filtervalues)

def get_db_files(sorder, fpath):
    """
        Fetch specific database values only from the database
    """
    index = index_data.objects.filter(fqpndirectory=fpath.lower().strip(),
                                      ignore=False).order_by(
                                          *SORT_MATRIX[sorder])
    return index
