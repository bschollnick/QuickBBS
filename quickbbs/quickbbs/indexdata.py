"""
IndexData Model - Master index for all files in the gallery
"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING, Any

from django.db.models import Count
from django.db.models.query import QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse

# Import shared foundation
from .models import (
    INDEXDATA_DOWNLOAD_SELECT_RELATED_LIST,
    INDEXDATA_SELECT_RELATED_LIST,
    SORT_MATRIX,
    NaturalSortField,
    Owners,
    RangedFileResponse,
    ThumbnailFiles,
    cached,
    filetypes,
    get_file_sha,
    indexdata_cache,
    indexdata_download_cache,
    models,
    settings,
    sync_to_async,
)

if TYPE_CHECKING:
    from .indexdirs import IndexDirs


class IndexData(models.Model):
    """
    The Master Index for All files in the Gallery.  (See IndexDirs for the counterpart
    for Directories)

    The file_sha256 is the Sha256 of the file itself, and can be used to help eliminate multiple
    thumbnails being created for the same file.

    The unique_sha256 is the sha256 of the file + the fully qualified pathname of the file.
    The unique sha256 is the eventual replacement for the UUID.  The idea is that a regeneration of the
    database does not destroy the valid identifiers for the files.  The UUID works as an unique identifier,
    but is randomly generated, which means that it can't be regenerated after a database regeneration, or
    if the database record is deleted, and then recreated.  Where the unique_sha256 can be, as long as the
    file & file path is the same and unchanged.
    """

    id = models.AutoField(primary_key=True)

    file_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=False,
        null=True,
        default=None,
        max_length=64,
    )  # This is the sha256 of the file itself
    unique_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )  # This is the sha256 of the (file + fqfn)

    lastscan = models.FloatField(db_index=True)  # Stored as Unix timestamp (seconds)
    lastmod = models.FloatField(db_index=True)  # Stored as Unix timestamp (seconds)
    name = models.CharField(db_index=True, max_length=384, default=None)
    # FQFN of the file itself
    name_sort = NaturalSortField(for_field="name", max_length=384, default="")
    duration = models.BigIntegerField(null=True)
    size = models.BigIntegerField(default=0)  # File size

    home_directory = models.ForeignKey(
        "IndexDirs",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="IndexData_entries",
    )
    virtual_directory = models.ForeignKey(
        "IndexDirs",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="Virtual_IndexData",
    )
    is_animated = models.BooleanField(default=False, db_index=True)
    ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
    delete_pending = models.BooleanField(default=False, db_index=True)  # File is to be deleted,
    cover_image = models.BooleanField(default=False, db_index=True)  # This image is the directory placard
    filetype = models.ForeignKey(
        filetypes,
        to_field="fileext",
        on_delete=models.CASCADE,
        db_index=True,
        default=".none",
        related_name="file_filetype_data",
    )
    is_generic_icon = models.BooleanField(default=False, db_index=True)  # icon is a generic icon

    new_ftnail = models.ForeignKey(
        ThumbnailFiles,
        on_delete=models.SET_NULL,
        blank=True,
        default=None,
        null=True,
        related_name="IndexData",
    )

    # https://stackoverflow.com/questions/38388423

    ownership = models.OneToOneField(
        Owners,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

    # Reverse relationships
    dir_thumbnail: "models.manager.RelatedManager[IndexDirs]"  # From IndexDirs.thumbnail
    file_links: "models.manager.RelatedManager[IndexDirs]"  # From IndexDirs.file_links (ManyToMany)

    @property
    def fqpndirectory(self) -> str:
        """
        Return the fully qualified pathname of the directory containing this file
        Returns: String representing the directory path from the parent IndexDirs object
        """
        return self.home_directory.fqpndirectory

    @property
    def full_filepathname(self) -> str:
        """
        Return the complete file path including directory and filename
        Returns: String representing the full file path by concatenating directory + filename
        """
        return self.fqpndirectory + self.name

    @staticmethod
    def return_identical_files_count(sha: str) -> int:
        """
        Return the number of identical files in the database
        Returns: Integer - Number of identical files
        """
        return IndexData.objects.filter(file_sha256=sha).count()

    @staticmethod
    def return_list_all_identical_files_by_sha(sha: str) -> "QuerySet[IndexData]":
        """
        Return a query of all duplicate files based on file SHA256 hash

        Args:
            sha: The SHA256 hash of the file to find duplicates for

        Returns:
            QuerySet containing summary data (file_sha256 + count) using .values()
            and .annotate() for files with 2+ duplicates
        """
        dupes = (
            IndexData.objects.filter(file_sha256=sha)
            .values("file_sha256")
            .annotate(dupe_count=Count("file_sha256"))
            .exclude(dupe_count__lt=2)
            .order_by("-dupe_count")
        )
        return dupes

    @staticmethod
    def get_identical_file_entries_by_sha(sha: str) -> "QuerySet[dict[str, Any]]":
        """
        Get file entries for identical files based on SHA256 hash

        Args:
            sha: The SHA256 hash of the file to search for

        Returns:
            QuerySet with dictionary-like data containing only name and directory
            fields using .values() for identical files
        """
        return IndexData.objects.values("name", "home_directory__fqpndirectory").filter(file_sha256=sha)

    @cached(indexdata_cache)
    @staticmethod
    def get_by_filters(
        additional_filters: dict[str, Any] | None = None,
    ) -> "QuerySet[IndexData]":
        """
        Return the files in the current directory, filtered by additional filters

        Args:
            additional_filters: Additional filters to apply to the query

        Returns: The filtered query of files
        """
        if additional_filters is None:
            additional_filters = {}
        return IndexData.objects.select_related(*INDEXDATA_SELECT_RELATED_LIST).filter(delete_pending=False, **additional_filters)

    @staticmethod
    def return_by_sha256_list(sha256_list: list[str], sort: int = 0) -> "QuerySet[IndexData]":
        """
        Return files matching the provided SHA256 list

        Args:
            sha256_list: List of file SHA256 hashes to filter by
            sort: The sort order of the files (0-2)

        Returns: The sorted query of files matching the SHA256 list
        """
        files = (
            IndexData.objects.select_related(*INDEXDATA_SELECT_RELATED_LIST)
            .filter(file_sha256__in=sha256_list, delete_pending=False)
            .order_by(*SORT_MATRIX[sort])
        )
        return files

    @cached(indexdata_cache)
    @staticmethod
    def get_by_sha256(sha_value: str, unique: bool = False) -> IndexData | None:
        """
        Return the IndexData object by SHA256

        Args:
            sha_value: The SHA256 of the IndexData object
            unique: If True, search by unique_sha256 (expects one result),
                    If False, search by file_sha256 (may return first of multiple)

        Returns: IndexData object or None if not found
        """
        try:
            if unique:
                return IndexData.objects.select_related(*INDEXDATA_SELECT_RELATED_LIST).get(unique_sha256=sha_value, delete_pending=False)
            # When searching by file_sha256, there may be duplicates - return first
            return IndexData.objects.select_related(*INDEXDATA_SELECT_RELATED_LIST).filter(file_sha256=sha_value, delete_pending=False).first()
        except IndexData.DoesNotExist:
            return None

    @cached(indexdata_download_cache)
    @staticmethod
    def get_by_sha256_for_download(sha_value: str, unique: bool = False) -> IndexData | None:
        """
        Return the IndexData object by SHA256 optimized for file downloads.

        Uses select_related for forward FKs and .only() to fetch minimal fields
        for maximum performance with high concurrency.

        Args:
            sha_value: The SHA256 of the IndexData object
            unique: If True, search by unique_sha256, otherwise by file_sha256

        Returns: IndexData object or None if not found
        """
        try:
            # Determine which SHA field to filter on
            filter_field = "unique_sha256" if unique else "file_sha256"

            # Only fetch fields needed for download
            return (
                IndexData.objects.select_related("filetype", "home_directory")
                .only(
                    "name",
                    "filetype__mimetype",
                    "filetype__is_movie",
                    "home_directory__fqpndirectory",
                )
                .get(**{filter_field: sha_value, "delete_pending": False})
            )
        except IndexData.DoesNotExist:
            return None

    def get_file_sha(self, fqfn: str) -> tuple[str | None, str | None]:
        """
        Return the SHA256 hashes of the file as hexdigest strings.

        This is a convenience helper method that provides instance-based access
        to the centralized SHA256 hashing implementation in quickbbs.common.
        It exists purely as a workflow convenience - callers could import and call
        quickbbs.common.get_file_sha() directly, but this method provides a
        consistent interface when working with IndexData instances.

        All hashing logic is delegated to quickbbs.common.get_file_sha().

        Args:
            fqfn: The fully qualified filename of the file to be hashed

        Returns:
            Tuple of (file_sha256, unique_sha256) where file_sha256 is the hash
            of the file contents and unique_sha256 is the hash of the file
            contents + fqfn
        """
        return get_file_sha(fqfn)

    def get_file_counts(self) -> None:
        """
        Stub method for template compatibility.

        Provides API compatibility between IndexData and IndexDirs objects when used in
        Jinja2 templates. This allows templates to call .get_file_counts() on either object
        type without checking the instance type first. IndexDirs objects return actual counts,
        while this method returns None since individual files don't have child file counts.

        Returns:
            None
        """
        return None

    def get_dir_counts(self) -> None:
        """
        Stub method for template compatibility.

        Provides API compatibility between IndexData and IndexDirs objects when used in
        Jinja2 templates. This allows templates to call .get_dir_counts() on either object
        type without checking the instance type first. IndexDirs objects return actual counts,
        while this method returns None since individual files don't have child directory counts.

        Returns:
            None
        """
        return None

    def get_view_url(self) -> str:
        """
        Generate the URL for the viewing of the current database item

        Returns
        -------
            Django URL object

        """
        return reverse("view_item", args=(self.unique_sha256,))

    def get_thumbnail_url(self, size: str | None = None) -> str:
        """
        Generate the URL for the thumbnail of the current item

        Returns
        -------
            Django URL object

        """
        if size not in settings.IMAGE_SIZE and size is not None:
            size = None
        if size is None:
            size = "small"
        size = size.lower()
        if self.virtual_directory:
            return self.virtual_directory.get_thumbnail_url(size=size)
        url = reverse(r"thumbnail2_file", args=(self.file_sha256,)) + f"?size={size}"
        return url

    def get_download_url(self) -> str:
        """
        Generate the URL for the downloading of the current database item

        Returns
        -------
            Django URL object

        """
        return reverse("download_file") + self.name + f"?usha={self.unique_sha256}"

    def inline_sendfile(self, request: Any, ranged: bool = False) -> Any:
        """
        Helper function to send data to remote - matches original fast implementation.

        Loads entire file into memory for non-ranged requests (fast for small files,
        benefits from OS caching on repeated reads).

        Uses HttpResponse for non-ranged, RangedFileResponse for ranged (videos).
        """
        mtype = self.filetype.mimetype or "application/octet-stream"
        fqpn_filename = self.full_filepathname

        if not ranged:
            # Load entire file into memory - matches old fast code
            try:
                with open(fqpn_filename, "rb") as fh:
                    response = HttpResponse(fh.read(), content_type=mtype)
                    response["Content-Disposition"] = f"inline; filename={self.name}"
                    response["Cache-Control"] = "public, max-age=300"
            except FileNotFoundError as exc:
                raise Http404 from exc
        else:
            # Ranged request for video streaming
            try:
                response = RangedFileResponse(
                    request,
                    file=open(fqpn_filename, "rb"),  # pylint: disable=consider-using-with
                    as_attachment=False,
                    filename=self.name,
                )
                response["Cache-Control"] = "public, max-age=300"
            except FileNotFoundError as exc:
                raise Http404 from exc
        response["Content-Type"] = mtype
        return response

    async def async_inline_sendfile(self, request: Any, ranged: bool = False) -> Any:
        """
        Helper function to send data to remote (ASGI async version).

        Uses aiofiles for true async file I/O to avoid sync iterator warnings.
        For non-ranged requests, loads file into memory for optimal async serving.
        For ranged requests (videos), uses sync file handle as RangedFileResponse
        requires seekable files.

        Args:
            request: Django request object
            ranged: Whether to support HTTP range requests for video streaming

        Returns:
            FileResponse or RangedFileResponse with file content

        Raises:
            Http404: If file not found
            asyncio.CancelledError: Re-raised if client disconnects (file handle cleaned up)
        """
        import aiofiles

        mtype = self.filetype.mimetype or "application/octet-stream"
        fqpn_filename = self.full_filepathname
        file_handle = None

        try:
            if not ranged:
                # Non-ranged: Load file async and serve from memory (eliminates sync iterator warning)
                async with aiofiles.open(fqpn_filename, "rb") as f:
                    content = await f.read()

                response = FileResponse(
                    io.BytesIO(content),
                    content_type=mtype,
                    as_attachment=False,
                    filename=self.name,
                )
            else:
                # Ranged request for video streaming - requires seekable sync file handle
                # RangedFileResponse needs seek() which aiofiles doesn't support
                #
                # IMPORTANT: RangedFileResponse takes ownership of the file handle and closes it
                # when the response completes. Do NOT use context manager (with open()) as it
                # would close the handle prematurely before streaming completes.
                #
                # Handle lifecycle:
                # - Normal operation: RangedFileResponse closes handle when streaming completes
                # - Errors: Exception handlers below close handle (FileNotFoundError, CancelledError)
                # - Concurrent streams: 50+ simultaneous open handles is safe (system limit ~1024)
                def _open_file():
                    return open(fqpn_filename, "rb")

                file_handle = await sync_to_async(_open_file)()
                response = RangedFileResponse(
                    request,
                    file=file_handle,
                    as_attachment=False,
                    filename=self.name,
                )
                response["Content-Type"] = mtype

            response["Cache-Control"] = "public, max-age=300"
            return response

        except FileNotFoundError as exc:
            # Clean up file handle if opened
            if file_handle is not None:
                file_handle.close()
            raise Http404 from exc
        except asyncio.CancelledError:
            # Client disconnected - clean up file handle if opened
            if file_handle is not None:
                file_handle.close()
            # Re-raise to let Django handle the cancellation
            raise

    class Meta:
        verbose_name = "Master Files Index"
        verbose_name_plural = "Master Files Index"
        indexes = [
            models.Index(fields=["home_directory", "delete_pending"]),
            models.Index(fields=["file_sha256", "delete_pending"]),
            models.Index(fields=["unique_sha256", "delete_pending"]),
            models.Index(fields=["name"], name="quickbbs_indexdata_name_idx"),
            # Composite indexes for common query patterns
            models.Index(fields=["name", "delete_pending"], name="indexdata_name_delete_idx"),
            models.Index(fields=["filetype", "delete_pending"], name="indexdata_filetype_delete_idx"),
            # Performance optimization: Partial index for thumbnail linking queries
            # Speeds up: IndexData.objects.filter(file_sha256=sha, new_ftnail__isnull=True).exists()
            models.Index(
                fields=["file_sha256"],
                name="indexdata_sha256_unlinked_idx",
                condition=models.Q(new_ftnail__isnull=True),
            ),
            # Performance optimization: Composite index for file type queries in directories
            # Speeds up: IndexData.objects.filter(home_directory=dir, filetype=type, delete_pending=False)
            models.Index(
                fields=["home_directory", "filetype", "delete_pending"],
                name="indexdata_home_type_delete_idx",
            ),
        ]
