"""
File type registry for QuickBBS: one row per file extension.

The table is tiny and read-heavy, so it is loaded once into a module-level
dict (get_ftype_dict / load_filetypes) and all lookups are served from
memory. Seed/refresh the table with `manage.py refresh_filetypes`.
"""

# from asgiref.sync import async_to_sync
import io
from typing import TYPE_CHECKING

from django.db import models

if TYPE_CHECKING:
    from django.db.models.fields.related_descriptors import RelatedManager

    from quickbbs.models import DirectoryIndex, FileIndex

# Single in-memory cache for the full filetypes table dict (loaded once at startup)
_filetypes_dict: dict[str, "filetypes"] | None = None


class filetypes(models.Model):
    """A registered file extension and its handling flags.

    Keyed by `fileext` (primary key — lowercase, includes the dot). The
    is_image/is_movie/is_pdf/... booleans drive dispatch decisions (e.g.
    which thumbnail backend handles the file), `generic` marks types served
    with a stock icon, and `thumbnail` holds that icon's image bytes.

    Example:
        >>> ft = filetypes.return_filetype(".mp4")
        >>> ft.is_movie, ft.is_image
        (True, False)
    """

    fileext = models.CharField(
        primary_key=True, db_index=True, max_length=10, unique=True
    )  # File Extension (eg. .html, includes the DOT). Always stored lowercase.
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

        Returns:
            FileResponse containing the generic icon image bytes stored in
            the `thumbnail` field.
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
        Normalize a file extension to its consistent format.

        Args:
            fileext: File extension to normalize.

        Returns:
            Normalized extension (lowercase, stripped, with dot prefix).
            Empty/None/"unknown" values normalize to ".none".
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

        Args:
            fileext: The file extension to check; normalized to lowercase
                with a dot prefix (e.g. .html).

        Returns:
            True if the filetype exists, False otherwise (including for
            extensionless ".none").

        Example:
            >>> filetypes.filetype_exists_by_ext(".jpg")
            True
            >>> filetypes.filetype_exists_by_ext(".xyz")
            False
        """
        fileext = filetypes._normalize_extension(fileext)
        if fileext == ".none":
            return False
        return fileext in get_ftype_dict()

    @staticmethod
    def return_filetype(fileext: str) -> "filetypes":
        """
        Return filetype object for the given file extension.

        Looks up from the in-memory dict loaded by get_ftype_dict() — no DB query.

        Args:
            fileext: File extension (e.g. 'gif', 'jpg', '.mp4'). Will be
                normalized to lowercase with a dot prefix.

        Returns:
            The filetypes object for the specified extension.

        Raises:
            KeyError: If the extension is not registered in the filetypes table.

        Example:
            >>> filetypes.return_filetype("mp4").is_movie
            True
        """
        fileext = filetypes._normalize_extension(fileext)
        return get_ftype_dict()[fileext]

    class Meta:
        """Model metadata: composite indexes for thumbnailable, dir/link, and text queries."""

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


def get_ftype_dict() -> dict[str, "filetypes"]:
    """
    Return filetypes information from database as a dictionary.

    Loads the full filetypes table once into a module-level dict and returns
    it on every subsequent call — no repeated DB queries. Call
    load_filetypes(force=True) to reload after the table changes.

    Returns:
        Dictionary of all filetype objects keyed by their primary key
        (fileext string, e.g. ".jpg").
    """
    global _filetypes_dict  # pylint: disable=global-statement
    if _filetypes_dict is None:
        _filetypes_dict = filetypes.objects.all().in_bulk()
    return _filetypes_dict


def load_filetypes(force: bool = False) -> dict[str, "filetypes"]:
    """
    Load file type data from the database into the module-level cache.

    A failed reload is not recoverable and is not swallowed: it propagates
    so the caller (worker startup, request middleware, or the post_save/
    post_delete signal handler) fails loudly instead of continuing to run
    against stale or invalid filetype data.

    Args:
        force: If True, reload from the database even if already cached.

    Returns:
        Dictionary of filetype objects keyed by fileext string.

    Raises:
        SynchronousOnlyOperation: If called from an async context. Async
            callers must wrap with sync_to_async(), as FiletypeLoaderMiddleware
            does.
        DatabaseError: If the reload query fails.
    """
    global _filetypes_dict  # pylint: disable=global-statement
    if not _filetypes_dict or force:
        _filetypes_dict = None
        print("Loading FileType data from database...")
        return get_ftype_dict()
    return _filetypes_dict
