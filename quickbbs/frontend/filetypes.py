# coding: utf-8
"""
Utilities for QuickBBS, the python edition.
"""
from __future__ import absolute_import, print_function, unicode_literals

from quickbbs.models import (filetypes)
#from django.core.exceptions import MultipleObjectsReturned
import logging
log = logging.getLogger(__name__)

ftypes = {'unknown':0,
         'dir':1,
         'pdf':2,
         'archive':3,
         'image':4,
         'movie':5,
         'text':6,
         'html':7,
         'epub':8,
         'flash':9}

__archives = [".zip", ".rar", ".cbz", ".cbr"]
__html = [".htm", ".html"]
__graphics = [".bmp", ".gif", "jpg", "jpeg", "png"]
__text = [".txt", ".md", ".markdown"]
__movie = [".mp4", ".m4v", ".mpg", ".mpg4", ".mpeg",
           ".mpeg4", ".wmv", ".flv", ".avi"]

def refresh_filetypes():
    for ext in __movie:
        filetypes.objects.update_or_create(fileext=ext, generic=True,
                                           filename="MovieIcon100.jpg",
                                           color="CCCCCC", filetype=ftypes['movie'])

    for ext in __archives:
        filetypes.objects.update_or_create(fileext=ext, generic=True,
                                           filename="1431973824_compressed.png",
                                           color="b2dece",
                                           filetype=ftypes['archive'])

    for ext in __html:
        filetypes.objects.update_or_create(fileext=ext, generic=True,
                                           filename="1431973779_html.png",
                                           color="fef7df", filetype=ftypes['html'])

    for ext in __graphics:
        filetypes.objects.update_or_create(fileext=ext, generic=False,
                                           color="FAEBF4", filetype=ftypes['image'])

    for ext in __text:
        filetypes.objects.update_or_create(fileext=ext, generic=True,
                                           filename="1431973815_text.PNG",
                                           color="FAEBF4", filetype=ftypes['image'])

    filetypes.objects.update_or_create(fileext=".pdf", generic=False,
                                       color="FDEDB1", filetype=ftypes['image'])

    filetypes.objects.update_or_create(fileext=".epub", generic=True,
                                       filename="epub-logo.gif",
                                       color="FDEDB1", filetype=ftypes['epub'])

    filetypes.objects.update_or_create(fileext=".dir", generic=False,
                                       color="DAEFF5", filetype=ftypes['dir'])

    filetypes.objects.update_or_create(fileext=".none", generic=True,
                                       filename="1431973807_fileicon_bg.png",
                                       color="FFFFFF", filetype=ftypes['unknown'])

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

refresh_filetypes()
FILETYPES = get_ftype_dict()
print ("# of FileTypes: ",len(FILETYPES))
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
