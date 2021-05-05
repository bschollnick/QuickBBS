# coding: utf-8
"""
Utilities for QuickBBS, the python edition.
"""
#from _future_ import absolute_import, print_function, unicode_literals

from quickbbs.models import (filetypes)
from django.core.exceptions import MultipleObjectsReturned

def return_filetype(fileext):
    if fileext in ['', None, 'unknown']:
        fileext = ".none"
    return filetypes.objects.filter(fileext=fileext)

def get_ftype_dict():
    # https://stackoverflow.com/questions/21925671/
    #from django.forms.models import model_to_dict
    data = {}
    dbase = filetypes.objects.values()
    for x in dbase:
        data[x["fileext"]] = x
    return data


def return_identifier(ext):
    ext = ext.lower().strip()
    if ext.startswith("."):
        ext = ext[1:]
    return ext
    
def map_ext_to_id(ext):
    ext = ext.lower().strip()
    if ext.startswith("."):
        ext = ext[1:]
    return ext
    

FILETYPE_DATA = {}
try:
#     refresh_filetypes()
    FILETYPE_DATA = get_ftype_dict()
except:
    print("Unable to validate or create FileType database table.")
    print("\nPlease use manage.py --refresh-filetypes\n")
    print("This will rebuild and/or update the FileType table.")
    sys.exit()
#     pass

