"""
Utilities for QuickBBS, the python edition.
"""

# from asgiref.sync import async_to_sync
import os
from functools import lru_cache

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
    is_link = models.BooleanField(default=False, db_index=True)

    def __unicode__(self):
        return f"{self.fileext}"

    def __str__(self):
        return f"{self.fileext}"

    @lru_cache(maxsize=200)
    @staticmethod
    def filetype_exists_by_ext(fileext):
        """
        Check if a filetype exists by its file extension.

        :param fileext: The file extension to check, lower case, and includes the DOT (e.g. .html, not html)
        :return: True if the filetype exists, False otherwise.
        """
        fileext = fileext.lower().strip()
        if fileext in ["", None, "unknown"]:
            return False
        if not fileext.startswith("."):
            fileext = "." + fileext
        return filetypes.objects.filter(fileext=fileext).exists()

    @lru_cache(maxsize=200)
    @staticmethod
    def return_any_icon_filename(fileext):
        """
        The return_icon_filename function takes a file extension as an argument and returns the filename of the
        icon that corresponds to that file extension.

        If no icon is found for a given file type, then it will return None.

        :param self: Allow the function to refer to the calling object
        :param fileext: Find the file extension of the file, lower case, and includes the DOT (e.g. .html, not html)
        :return: The icon filename for the given file extension (IMAGES_PATH + filename), or NONE if not found or
            the filename for the fileext is blank (e.g. JPEG, since JPEG will always be created based off the file)
        """
        fileext = fileext.lower().strip()
        if fileext in ["", None, "unknown"]:
            fileext = ".none"
        if not fileext.startswith("."):
            fileext = "." + fileext
        # data = filetypes.objects.filter(fileext=fileext)
        data = filetypes.return_filetype(fileext)
        if data and data.icon_filename != "":
            return os.path.join(settings.IMAGES_PATH, data.icon_filename)
        return None

    @lru_cache(maxsize=200)
    @staticmethod
    def return_filetype(fileext):
        """
        fileext = gif, jpg, mp4 (lower case, and without prefix .)
        """
        fileext = fileext.lower().strip()
        if fileext in ["", None, "unknown"]:
            fileext = ".none"
        if not fileext.startswith("."):
            fileext = "." + fileext

        return filetypes.objects.get(fileext=fileext)

    class Meta:
        verbose_name = "File Type"
        verbose_name_plural = "File Types"


@lru_cache(maxsize=200)
def get_ftype_dict():
    """
    Return filetypes information (from table) in an dictionary form.
    """
    # https://stackoverflow.com/questions/21925671/
    # from django.forms.models import model_to_dict
    return filetypes.objects.all().in_bulk()


def return_identifier(ext):
    """
    Return the extension portion of the filename (minus the .)
    """
    ext = ext.lower().strip()
    return ext


@lru_cache(maxsize=200)
def map_ext_to_id(ext):
    """
    Return the extension portion of the filename (minus the .)
    Why is this duplicated?
    """
    return return_identifier(ext)


def load_filetypes(force=False):
    global FILETYPE_DATA
    if not FILETYPE_DATA or force:
        try:
            print("Loading FileType data from database...")
            FILETYPE_DATA = get_ftype_dict()
        except:
            print("Unable to validate or create FileType database table.")
            print("\nPlease use manage.py --refresh-filetypes\n")
            print("This will rebuild and/or update the FileType table.")
    return FILETYPE_DATA
    #   sys.exit()
