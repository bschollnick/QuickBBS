"""
Utilities for QuickBBS, the python edition.
"""

# from asgiref.sync import async_to_sync
import io
import os
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import DatabaseError, models

if TYPE_CHECKING:
    from django.db.models.manager import RelatedManager

    from quickbbs.models import DirectoryIndex, FileIndex

FILETYPE_DATA = {}

# Single in-memory cache for the full filetypes table dict (loaded once at startup)
_filetypes_dict: dict | None = None


class filetypes(models.Model):
    fileext = models.CharField(
        primary_key=True, db_index=True, max_length=10, unique=True
    )  # File Extension (eg. .html, is lowercase, and includes the DOT)
    generic = models.BooleanField(default=False)

    icon_filename = models.CharField(max_length=384, default="", blank=True)  # FQFN of the file itself
    color = models.CharField(max_length=7, default="000000")

    # ftypes dictionary in constants / ftypes
    filetype = models.IntegerField(default=0, blank=True, null=True)
    mimetype = models.CharField(max_length=128, default="application/octet-stream", null=True)
    # quick testers.
    # Originally going to be filetype only, but the SQL got too large
    # (eg retrieve all graphics, became is JPEG, GIF, TIF, BMP, etc)
    # so is_image is easier to fetch.
    # Note: Individual db_index removed - table is small and cached in memory at startup.
    # Query patterns are covered by composite Meta indexes (thumbnailable, dir_link, text).
    is_image = models.BooleanField(default=False)
    is_archive = models.BooleanField(default=False)
    is_pdf = models.BooleanField(default=False)
    is_movie = models.BooleanField(default=False)
    is_audio = models.BooleanField(default=False)
    is_dir = models.BooleanField(default=False)
    is_text = models.BooleanField(default=False)
    is_html = models.BooleanField(default=False)
    is_markdown = models.BooleanField(default=False)
    is_link = models.BooleanField(default=False)

    thumbnail = models.BinaryField(default=b"", null=True)

    # Reverse ForeignKey relationships
    dirs_filetype_data: "RelatedManager[DirectoryIndex]"  # From DirectoryIndex.filetype
    file_filetype_data: "RelatedManager[FileIndex]"  # From FileIndex.filetype

    def __unicode__(self) -> str:
        return f"{self.fileext}"

    def __str__(self) -> str:
        return f"{self.fileext}"

    def send_thumbnail(self):
        """
        Send the generic icon thumbnail for this file type.

        :return: FileResponse containing the generic icon image
        """
        # Create a fresh BytesIO object each time - FileResponse will close it after sending
        # Cannot use cached_property because Django closes the file handle after response
        from frontend.serve_up import send_file_response

        thumbnail_stream = io.BytesIO(self.thumbnail)
        return send_file_response(
            filename=self.icon_filename,
            content_to_send=thumbnail_stream,
            mtype=self.mimetype or "image/jpeg",
            attachment=False,
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

    @staticmethod
    def filetype_exists_by_ext(fileext: str) -> bool:
        """
        Check if a filetype exists by its file extension.

        Looks up from the in-memory dict loaded by get_ftype_dict() — no DB query.

        :param fileext: The file extension to check, lower case, and includes the DOT (e.g. .html, not html)
        :return: True if the filetype exists, False otherwise.
        """
        fileext = filetypes._normalize_extension(fileext)
        if fileext == ".none":
            return False
        return fileext in get_ftype_dict()

    @staticmethod
    def return_any_icon_filename(fileext: str) -> str | None:
        """
        Return the icon filename for the given file extension, or None if not found.

        Looks up from the in-memory dict loaded by get_ftype_dict() — no DB query.

        :param fileext: File extension (e.g. .html). Will be normalized to lowercase with dot prefix.
        :return: Full path to the icon file, or None if not found or no icon is set.
        """
        fileext = filetypes._normalize_extension(fileext)
        data = get_ftype_dict().get(fileext)
        if data and data.icon_filename != "":
            return os.path.join(settings.IMAGES_PATH, data.icon_filename)
        return None

    @staticmethod
    def return_filetype(fileext: str) -> "filetypes":
        """
        Return filetype object for the given file extension.

        Looks up from the in-memory dict loaded by get_ftype_dict() — no DB query.

        :param fileext: File extension (e.g., 'gif', 'jpg', '.mp4'). Will be normalized to lowercase with dot prefix
        :return: filetypes object for the specified extension
        """
        fileext = filetypes._normalize_extension(fileext)
        return get_ftype_dict()[fileext]

    class Meta:
        verbose_name = "File Type"
        verbose_name_plural = "File Types"
        indexes = [
            # Composite index for thumbnailable file queries (images, movies, PDFs)
            models.Index(fields=["is_image", "is_movie", "is_pdf"], name="filetypes_thumbnailable_idx"),
            # Composite index for directory and link filtering
            models.Index(fields=["is_dir", "is_link"], name="filetypes_dir_link_idx"),
            # Composite index for text content queries
            models.Index(fields=["is_text", "is_html", "is_markdown"], name="filetypes_text_idx"),
        ]


def get_ftype_dict() -> dict:
    """
    Return filetypes information from database as a dictionary.

    Loads the full filetypes table once into a module-level dict and returns
    it on every subsequent call — no repeated DB queries. Call load_filetypes()
    to force a reload after the table changes.

    Returns: Dictionary of all filetype objects keyed by their primary key (fileext string)
    """
    global _filetypes_dict  # pylint: disable=global-statement
    if _filetypes_dict is None:
        _filetypes_dict = filetypes.objects.all().in_bulk()
    return _filetypes_dict


def return_identifier(ext: str) -> str:
    """
    Return the extension portion of the filename.

        ext: File extension to process
    Returns: Lowercase, stripped extension
    """
    ext = ext.lower().strip()
    return ext


def load_filetypes(force: bool = False) -> dict:
    """
    Load file type data from database into global cache.

        force: If True, force reload from database even if already cached
    Returns: Dictionary of filetype data
    """
    global FILETYPE_DATA, _filetypes_dict  # pylint: disable=global-statement
    if not FILETYPE_DATA or force:
        if force:
            _filetypes_dict = None  # invalidate get_ftype_dict() cache
        try:
            print("Loading FileType data from database...")
            FILETYPE_DATA = get_ftype_dict()
        except DatabaseError as e:
            print(f"Database error while loading FileType data: {e}")
            print("\nPlease use manage.py --refresh-filetypes\n")
            print("This will rebuild and/or update the FileType table.")
            # ASGI: connections.close_all() commented out for ASGI compatibility
            # connections.close_all()
        except Exception as e:  # TODO: narrow once startup failure modes are known (e.g. ImportError, AttributeError from model mismatches)
            print(f"Unexpected error while loading FileType data: {e}")
            print("\nPlease use manage.py --refresh-filetypes\n")
            print("This will rebuild and/or update the FileType table.")
            # ASGI: connections.close_all() commented out for ASGI compatibility
            # connections.close_all()
    return FILETYPE_DATA
