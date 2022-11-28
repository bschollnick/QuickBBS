# coding: utf-8
"""
Utilities for QuickBBS, the python edition.
"""
from django.db import models
from django.core.exceptions import MultipleObjectsReturned
import sys


class filetypes(models.Model):
    fileext = models.CharField(primary_key=True,
                               db_index=True,
                               max_length=10,
                               unique=True)  # File Extension (eg. html)
    generic = models.BooleanField(default=False, db_index=True)

    icon_filename = models.CharField(db_index=True, max_length=384, default='', blank=True)  # FQFN of the file itself
    color = models.CharField(max_length=7, default="000000")

    # ftypes dictionary in constants / ftypes
    filetype = models.IntegerField(db_index=True,
                                   default=0,
                                   blank=True,
                                   null=True)
    # quick testers.
    # Originally going to be filetype only, but the SQL got too large
    # (eg retrieve all graphics, became is JPEG, GIF, TIF, BMP, etc)
    # so is_image is easier to fetch.
    is_image = models.BooleanField(default=False, db_index=True)
    is_archive = models.BooleanField(default=False, db_index=True)
    is_pdf = models.BooleanField(default=False, db_index=True)
    is_movie = models.BooleanField(default=False, db_index=True)
    is_audio = models.BooleanField(default=False, db_index=True)
    is_dir = models.BooleanField(default=False, db_index=True)

    def __unicode__(self):
        return '%s' % self.fileext

    def return_filetype(self, fileext):
        """
            fileext = gif, jpg, mp4 (lower case, and without prefix .)
        """
        fileext = fileext.lower()

        if fileext.startswith("."):
            fileext = fileext[1:]

        if fileext in ['', None, 'unknown']:
            fileext = ".none"

        return filetypes.objects.filter(fileext=fileext)

    class Meta:
        verbose_name = u'File Type'
        verbose_name_plural = u'File Types'


def return_filetype(fileext):
    """
        Return the filetype data for a particular file extension

        fileext: String, the extension of the file type with ., in lowercase
                eg .doc, .txt
    """
    return filetype.return_filetype(fileext)


def get_ftype_dict():
    """
    Return filetypes information (from table) in an dictionary form.
    """
    # https://stackoverflow.com/questions/21925671/
    # from django.forms.models import model_to_dict
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


def load_filetypes():
    try:
        # refresh_filetypes()
        return get_ftype_dict()
    except :
        print("Unable to validate or create FileType database table.")
        print("\nPlease use manage.py --refresh-filetypes\n")
        print("This will rebuild and/or update the FileType table.")
    #   sys.exit()


def reload_filetypes():
    global FILETYPE_DATA
    FILETYPE_DATA = load_filetypes()


# FILETYPE_DATA = load_filetypes()
reload_filetypes()
