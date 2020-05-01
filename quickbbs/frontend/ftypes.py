# coding: utf-8
"""
Utilities for QuickBBS, the python edition.
"""
#from _future_ import absolute_import, print_function, unicode_literals

from quickbbs.models import (filetypes)
from django.core.exceptions import MultipleObjectsReturned
#from django.db.utils import ProgrammingError

#import logging
#log = logging.getLogger(_name_)
from frontend.constants import ftypes
import frontend.constants as constants

def refresh_filetypes():
    for ext in constants._movie:
        filetypes.objects.update_or_create(fileext=ext,
                                           defaults={"generic":True,
                                                     "icon_filename":"MovieIcon100.jpg",
                                                     "color":"CCCCCC",
                                                     "filetype":ftypes['movie'],
                                                     "is_movie":True}
                                                     )

    for ext in constants._archives:
        filetypes.objects.update_or_create(fileext=ext,
                                           defaults={"generic":True,
                                                     "icon_filename":"1431973824_compressed.png",
                                                     "color":"b2dece",
                                                     "filetype":ftypes['archive'],
                                                     "is_archive":True})

    for ext in constants._html:
        filetypes.objects.update_or_create(fileext=ext,
                                           defaults={"generic":True,
                                           "icon_filename":"1431973779_html.png",
                                           "color":"fef7df", "filetype":ftypes['html']})

    for ext in constants._graphics:
        filetypes.objects.update_or_create(fileext=ext,
                                           defaults={"generic":False,
                                           "color":"FAEBF4", "filetype":ftypes['image'],
                                           "is_image":True})

    for ext in constants._text:
        filetypes.objects.update_or_create(fileext=ext,
                                           defaults={"generic":True,
                                           "icon_filename":"1431973815_text.PNG",
                                           "color":"FAEBF4", "filetype":ftypes['image']})

    filetypes.objects.update_or_create(fileext=".pdf",
                                       defaults={"generic":False,
                                       "color":"FDEDB1", "filetype":ftypes['image'],
                                       "is_pdf":True})

    filetypes.objects.update_or_create(fileext=".epub",
                                       defaults={"generic":True,
                                       "icon_filename":"epub-logo.gif",
                                       "color":"FDEDB1", "filetype":ftypes['epub']})

    filetypes.objects.update_or_create(fileext=".dir",
                                        defaults={"generic":False,
                                       "color":"DAEFF5", "filetype":ftypes['dir'],
                                       "is_dir":True})

    filetypes.objects.update_or_create(fileext=".none", defaults={"generic":True,
                                       "icon_filename":"1431973807_fileicon_bg.png",
                                       "color":"FFFFFF", "filetype":ftypes['unknown']})

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

def map_ext_to_id(ext):
    ext = ext.lower().strip()
    if ext.startswith("."):
        ext = ext[1:]

try:
    refresh_filetypes()
    FILETYPE_DATA = get_ftype_dict()
except:
    print("Unable to validate or create FileType database table.")
    pass

#print ("# of FileTypes: ",len(FILETYPES))
# class filetypes(models.Model):
    # id = models.AutoField(primary_key=True)
    # fileext = models.CharField(db_index=True,
                               # max_length=10,
                               # unique=True,
                               # blank=False) # File ext (eg. html)
    # filesize = models.BigIntegerField(default=-1)
    # generic = models.BooleanField(default=False, db_index=True)

    # filename = models.CharField(db_index=True,
                                # max_length=512,
                                # default=None,
                                # unique=False,
                                # blank=True)   # FQFN of the file itself
    # color = models.CharField(max_length=7, default="000000")
    # imageformat = models.BooleanField(default=False, db_index=True)
    # textformat = models.BooleanField(default=False, db_index=True)
    # archive = models.BooleanField(default=False, db_index=True)
    # smallthumb = models.BinaryField(default=b"")
    # largethumb = models.BinaryField(default=b"")

    # class Meta:
        # verbose_name = u'File Type'
        # verbose_name_plural = u'File Types'
