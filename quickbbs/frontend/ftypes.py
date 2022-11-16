# coding: utf-8
"""
Utilities for QuickBBS, the python edition.
"""
#from _future_ import absolute_import, print_function, unicode_literals

import sys

from django.core.exceptions import MultipleObjectsReturned

from quickbbs.models import filetypes


def return_filetype(fileext):
    """
        Return the filetype data for a particular file extension

        fileext: String, the extension of the file type with ., in lowercase
                eg .doc, .txt
    """
    if fileext in ['', None, 'unknown']:
        fileext = ".none"
    return filetypes.objects.filter(fileext=fileext.lower())

def get_ftype_dict():
    """
    Return filetypes information (from table) in an dictionary form.
    """
    # https://stackoverflow.com/questions/21925671/
    #from django.forms.models import model_to_dict
    data = {}
    dbase = filetypes.objects.values()
    for tabledata in dbase:
        data[tabledata["fileext"]] = tabledata
    return data


def return_identifier(ext):
    """
    Return the extension portion of the filename (minus the .)
    """
    ext = ext.lower().strip()
    if ext.startswith("."):
        ext = ext[1:]
    return ext

def map_ext_to_id(ext):
    """
    Return the extension portion of the filename (minus the .)
    Why is this duplicated?
    """
    return return_identifier(ext)



FILETYPE_DATA = {}
try:
#refresh_filetypes()
    FILETYPE_DATA = get_ftype_dict()
except :
   print("Unable to validate or create FileType database table.")
   print("\nPlease use manage.py --refresh-filetypes\n")
   print("This will rebuild and/or update the FileType table.")
#   sys.exit()
