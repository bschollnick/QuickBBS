"""
Utilities for QuickBBS, the python edition.
"""

# from asgiref.sync import async_to_sync
import io
import os
from functools import lru_cache

from django.apps import AppConfig
from django.conf import settings
from django.db import models
from django.http import FileResponse, HttpResponse
from django.utils.functional import cached_property

from frontend.serve_up import send_file_response

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

    thumbnail = models.BinaryField(default=b"", null=True)

    def __unicode__(self) -> str:
        return f"{self.fileext}"

    def __str__(self) -> str:
        return f"{self.fileext}"

    @cached_property
    def thumbnail_stream(self) -> io.BytesIO:
        """
        Get cached BytesIO stream for thumbnail data.

        :return: BytesIO object containing thumbnail binary data
        """
        return io.BytesIO(self.thumbnail)

    def send_thumbnail(self):
        """
        Send the generic icon thumbnail for this file type.

        :return: FileResponse containing the generic icon image
        """
        # Reset stream position for reuse
        self.thumbnail_stream.seek(0)
        return send_file_response(
            filename=self.icon_filename,
            content_to_send=self.thumbnail_stream,
            mtype=self.mimetype or "image/jpeg",
            attachment=False,
            last_modified=None,
            expiration=300,
        )

    @staticmethod
    def _normalize_extension(fileext: str) -> str:
        """
        Normalize file extension to consistent format.

        :param fileext: File extension to normalize
        :return: Normalized extension (lowercase, stripped, with dot prefix)
        """
        fileext = fileext.lower().strip()
        if fileext in ["", None, "unknown"]:
            fileext = ".none"
        if not fileext.startswith("."):
            fileext = "." + fileext
        return fileext

    @lru_cache(maxsize=1000)
    @staticmethod
    def filetype_exists_by_ext(fileext: str) -> bool:
        """
        Check if a filetype exists by its file extension.

        :param fileext: The file extension to check, lower case, and includes the DOT (e.g. .html, not html)
        :return: True if the filetype exists, False otherwise.
        """
        fileext = filetypes._normalize_extension(fileext)
        if fileext == ".none":
            return False
        return filetypes.objects.filter(fileext=fileext).exists()

    @lru_cache(maxsize=500)
    @staticmethod
    def return_any_icon_filename(fileext: str) -> str | None:
        """
        The return_icon_filename function takes a file extension as an argument and returns the filename of the
        icon that corresponds to that file extension.

        If no icon is found for a given file type, then it will return None.

        :param self: Allow the function to refer to the calling object
        :param fileext: Find the file extension of the file, lower case, and includes the DOT (e.g. .html, not html)
        :return: The icon filename for the given file extension (IMAGES_PATH + filename), or NONE if not found or
            the filename for the fileext is blank (e.g. JPEG, since JPEG will always be created based off the file)
        """
        fileext = filetypes._normalize_extension(fileext)
        data = filetypes.return_filetype(fileext)
        if data and data.icon_filename != "":
            return os.path.join(settings.IMAGES_PATH, data.icon_filename)
        return None

    @lru_cache(maxsize=5000)
    @staticmethod
    def return_filetype(fileext: str) -> "filetypes":
        """
        Return filetype object for the given file extension.

        :param fileext: File extension (e.g., 'gif', 'jpg', '.mp4'). Will be normalized to lowercase with dot prefix
        :return: filetypes object for the specified extension
        """
        fileext = filetypes._normalize_extension(fileext)
        return filetypes.objects.get(fileext=fileext)

    class Meta:
        verbose_name = "File Type"
        verbose_name_plural = "File Types"


@lru_cache(maxsize=50)
def get_ftype_dict() -> dict:
    """
    Return filetypes information from database as a dictionary.

    :return: Dictionary of all filetype objects keyed by their primary key
    """
    # https://stackoverflow.com/questions/21925671/
    # from django.forms.models import model_to_dict
    return filetypes.objects.all().in_bulk()


def return_identifier(ext: str) -> str:
    """
    Return the extension portion of the filename.

    :param ext: File extension to process
    :return: Lowercase, stripped extension
    """
    ext = ext.lower().strip()
    return ext




def load_filetypes(force: bool = False) -> dict:
    """
    Load file type data from database into global cache.

    :param force: If True, force reload from database even if already cached
    :return: Dictionary of filetype data
    """
    from django.db import DatabaseError, connections

    global FILETYPE_DATA
    if not FILETYPE_DATA or force:
        try:
            print("Loading FileType data from database...")
            FILETYPE_DATA = get_ftype_dict()
        except DatabaseError as e:
            print(f"Database error while loading FileType data: {e}")
            print("\nPlease use manage.py --refresh-filetypes\n")
            print("This will rebuild and/or update the FileType table.")
            connections.close_all()
        except Exception as e:
            print(f"Unexpected error while loading FileType data: {e}")
            print("\nPlease use manage.py --refresh-filetypes\n")
            print("This will rebuild and/or update the FileType table.")
            connections.close_all()
    return FILETYPE_DATA
