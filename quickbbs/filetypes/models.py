"""
Utilities for QuickBBS, the python edition.
"""

import os

from django.apps import AppConfig
from django.conf import settings
from django.db import models

FILETYPE_DATA = {}


class filetypes(models.Model):
    fileext = models.CharField(
        primary_key=True, db_index=True, max_length=10, unique=True
    )  # File Extension (eg. .html, is lowercase, and includes the DOT)
    generic = models.BooleanField(default=False, db_index=True)

    icon_filename = models.CharField(
        db_index=True, max_length=384, default="", blank=True
    )  # FQFN of the file itself
    color = models.CharField(max_length=7, default="000000")

    # ftypes dictionary in constants / ftypes
    filetype = models.IntegerField(db_index=True, default=0, blank=True, null=True)
    mimetype = models.CharField(
        max_length=128, default="application/octet-stream", null=True
    )
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
    is_text = models.BooleanField(default=False, db_index=True)
    is_html = models.BooleanField(default=False, db_index=True)
    is_markdown = models.BooleanField(default=False, db_index=True)

    def __unicode__(self):
        return f"{self.fileext}"

    def return_any_icon_filename(self, fileext):
        """
        The return_icon_filename function takes a file extension as an argument and returns the filename of the
        icon that corresponds to that file extension.

        If no icon is found for a given file type, then it will return None.

        :param self: Allow the function to refer to the calling object
        :param fileext: Find the file extension of the file, lower case, and includes the DOT (e.g. .html, not html)
        :return: The icon filename for the given file extension (IMAGES_PATH + filename), or NONE if not found or
            the filename for the fileext is blank (e.g. JPEG, since JPEG will always be created based off the file)
        """
        fileext = fileext.lower()
        #        if not fileext.startswith("."):
        #            fileext = f'.{fileext}'
        if fileext in ["", None, "unknown"]:
            fileext = ".none"

        data = filetypes.objects.filter(fileext=fileext)
        if data.exists() and data[0].icon_filename != "":
            return os.path.join(settings.IMAGES_PATH, data[0].icon_filename)
        # else return None

    def return_filetype(self, fileext):
        """
        fileext = gif, jpg, mp4 (lower case, and without prefix .)
        """
        fileext = fileext.lower()
        #        if not fileext.startswith("."):
        #            fileext = f'.{fileext}'
        if fileext in ["", None, "unknown"]:
            fileext = ".none"

        return filetypes.objects.filter(fileext=fileext)

    class Meta:
        verbose_name = "File Type"
        verbose_name_plural = "File Types"


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
    #    if ext.startswith("."):
    #        ext = ext[1:]
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
    except:
        print("Unable to validate or create FileType database table.")
        print("\nPlease use manage.py --refresh-filetypes\n")
        print("This will rebuild and/or update the FileType table.")
    #   sys.exit()


# class filetype(AppConfig):


# class cache(AppConfig):
# #     name = "cache"
# #     path = os.path.join(settings.BASE_DIR, "cache")
# #     cold_start = False
# #
# #     def ready(self):
# #         global cold_start
# #         if self.cold_start:
# #             return
# #         from cache.models import Cache_Storage
# #
# #         try:
# #             if not self.cold_start:
# #                 print("Clearing all entries from Cache Tracking")
# #                 # Cache_Storage.clear_all_records()
# #                 self.cold_start = True
# #                 cold_start = True
# #         except ProgrammingError:
# #             print("Unable to clear Cache Table")
# #         except OperationalError:
# #             print("Cache table doesn't exist")

# FILETYPE_DATA = load_filetypes()
# reload_filetypes()
FILETYPE_DATA = load_filetypes()
# reload_filetypes()
