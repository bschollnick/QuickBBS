"""
The models, and logic for thumbnail storage for the Quickbbs reloaded project.

* Thumbnail Files - Is the core storage for the thumbnails.  This stores the actual
    data for the thumbnail (e.g. FileSize, FileName, uuid, etc.  The actual
    thumbnail is stored in the *Thumb tables (see below) )

    These tables are the binary storage for Thumbnail Files.
    * SmallThumb - The binary storage for the Small Thumbnails
    * MediumThumb - The Binary storage for the Medium Thumbnails
    * LargeThumb - The Binary Storage for the Large Thumbnails

v4 - Attempting to reduce the amount of queries by maximizing the foreign key logic,
    to access the IndexData information, instead of fetching it separately.
    Changing the directory thumbnail logic, the directory data is still it's own table,
    but the thumbnail is now a foreign key to the ThumbnailFiles model for the file
    that is being shown as the thumbnail. This eliminates the need for the redundant blob
    in the DirectoryThumbnail model, and allows for easier management of the thumbnails.

v3 - Pilot changing the thumbnail storage to be a single table, with the small, medium,
    and large blobs containing the actual thumbnail data.  This will reduce the number of
    queries, and allow for easier management of the thumbnails.

    Split the directory thumbnails into a separate table, so that we can manage the thumbnails
    separately from the IndexData model.

"""

import io
import os
from functools import lru_cache

from django.conf import settings
from django.db import models, transaction
from django.http import FileResponse
from frontend.serve_up import send_file_response

# from .image_utils import resize_pil_image, return_image_obj
from .thumbnail_engine import create_thumbnails_from_path

__version__ = "4.0"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/quickbbs"
__license__ = "TBD"


ThumbnailFiles_Prefetch_List = [
    "IndexData__filetype",
]


class ThumbnailFiles(models.Model):
    """
    ThumbnailFiles is the primary storage for any thumbnails that are created.

    Primary Key - `sha256_hash` - This is the sha256 hash of the file that the thumbnail is for.

    * SmallThumb - The binary storage for the Small Thumbnails
    * MediumThumb - The Binary storage for the Medium Thumbnails
    * LargeThumb - The Binary Storage for the Large Thumbnails

    """

    sha256_hash = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )
    small_thumb = models.BinaryField(default=b"", null=True)
    medium_thumb = models.BinaryField(default=b"", null=True)
    large_thumb = models.BinaryField(default=b"", null=True)

    class Meta:
        verbose_name = "Image File Thumbnails Cache"
        verbose_name_plural = "Image File Thumbnails Cache"

    @staticmethod
    def get_or_create_thumbnail_record(
        file_sha256: str, suppress_save: bool = False
    ) -> "ThumbnailFiles":
        """
        Get or create a thumbnail record for a file.

        :Args:
            file_sha256: The sha256 hash of the file to retrieve or create a thumbnail for
            suppress_save: If True, do not save the thumbnail after creation (default: False)

        :return: ThumbnailFiles object, either retrieved from database or newly created
        """

        from quickbbs.models import IndexData

        # Phase 1: Database operations only (inside transaction)
        with transaction.atomic():
            defaults = {
                "sha256_hash": file_sha256,
                "small_thumb": b"",
                "medium_thumb": b"",
                "large_thumb": b"",
            }
            thumbnail, created = ThumbnailFiles.objects.prefetch_related(
                *ThumbnailFiles_Prefetch_List
            ).get_or_create(sha256_hash=file_sha256, defaults=defaults)

            # Use prefetched data to avoid additional queries
            prefetched_indexdata = list(thumbnail.IndexData.all())

            if prefetched_indexdata:
                index_data_item = prefetched_indexdata[0]
                make_link = any(item.new_ftnail_id is None for item in prefetched_indexdata)
            else:
                index_data_item = IndexData.objects.select_related('filetype').filter(
                    file_sha256=file_sha256
                ).first()
                make_link = True

            make_link = make_link or created

            if make_link:
                thumbnail.save()
                IndexData.objects.filter(
                    file_sha256=file_sha256,
                    new_ftnail__isnull=True,
                ).update(new_ftnail=thumbnail)

        # Phase 2: File I/O operations (outside transaction)
        if thumbnail.thumbnail_exists():
            return thumbnail

        filename = index_data_item.full_filepathname
        filetype = index_data_item.filetype

        if filetype.is_image:
            thumbnails = create_thumbnails_from_path(
                filename, settings.IMAGE_SIZE, output="JPEG", backend="image"
            )
        elif filetype.is_movie:
            thumbnails = create_thumbnails_from_path(
                filename, settings.IMAGE_SIZE, output="JPEG", backend="video"
            )
        elif filetype.is_pdf:
            thumbnails = create_thumbnails_from_path(
                filename, settings.IMAGE_SIZE, output="JPEG", backend="pdf"
            )
        else:
            print("Unable to create thumbnails for this file type.")
            thumbnails = {
                "small": b"",
                "medium": b"",
                "large": b"",
            }

        thumbnail.small_thumb = thumbnails["small"]
        thumbnail.medium_thumb = thumbnails["medium"]
        thumbnail.large_thumb = thumbnails["large"]

        if not suppress_save:
            thumbnail.save(
                update_fields=["small_thumb", "medium_thumb", "large_thumb"]
            )

        return thumbnail

    def number_of_indexdata_references(self) -> int:
        """
        Return the number of IndexData references for this thumbnail.

        :return: Count of IndexData objects referencing this thumbnail
        """
        from quickbbs.models import IndexData

        return IndexData.objects.filter(file_sha256=self.sha256_hash).count()

    @lru_cache(maxsize=250)
    def get_thumbnail_by_sha(self, sha256: str) -> "ThumbnailFiles":
        """
        Get thumbnail object by SHA256 hash.

        :param sha256: SHA256 hash of the file
        :return: ThumbnailFiles object for the specified hash
        """
        return ThumbnailFiles.objects.prefetch_related(
            *ThumbnailFiles_Prefetch_List
        ).get(sha256_hash=sha256)

    def thumbnail_exists(self, size: str = "small") -> bool:
        """
        Check if the thumbnail exists for the given size.

        :param size: The size of the thumbnail to check for (small, medium, or large)
        :return: True if the thumbnail exists, False otherwise
        """
        match size.lower():
            case "small":
                return self.small_thumb not in ["", b"", None]
            case "medium":
                return self.medium_thumb not in ["", b"", None]
            case "large":
                return self.large_thumb not in ["", b"", None]
        return False

    def invalidate_thumb(self) -> None:
        """
        Clear all thumbnail data for regeneration.

        Sets all thumbnail binary fields (small, medium, large) to empty byte strings.
        Does not save the object - call save() explicitly after invalidation.

        :return: None

        Note:
            This function does not delete the thumbnail object or save changes.
            The intention is to clear thumbnail data for regeneration.

        Example:
            >>> thumbnail = ThumbnailFiles.objects.get(sha256_hash='...')
            >>> thumbnail.invalidate_thumb()
            >>> thumbnail.save()
        """
        self.small_thumb = b""
        self.medium_thumb = b""
        self.large_thumb = b""

    def retrieve_sized_tnail(self, size: str = "small") -> bytes:
        """
        Get thumbnail blob of specified size.

        :param size: The size string (small, medium, or large)
        :return: Binary blob containing the image data for the specified size
        """
        blobdata = b""
        match size.lower():
            case "small":
                blobdata = self.small_thumb
            case "medium":
                blobdata = self.medium_thumb
            case "large":
                blobdata = self.large_thumb
        return blobdata

    def send_thumbnail(self, filename_override: str | None = None, fext_override: str | None = None, size: str = "small"):
        """
        Send thumbnail as HTTP response with appropriate headers.

        :param filename_override: Optional filename to use instead of the original
        :param fext_override: Optional file extension override (unused, kept for API compatibility)
        :param size: The size of thumbnail to send (small, medium, or large)
        :return: Django FileResponse containing the thumbnail with appropriate headers

        Note:
            Thumbnails are stored as JPEGs, so JPEG will always be sent regardless of
            the original file type.

        Example:
            >>> thumbnail.send_thumbnail(filename_override="cover.jpg", size="medium")
        """
        filename = filename_override or self.IndexData.first().name
        mtype = "image/jpeg"
        blob = self.retrieve_sized_tnail(size=size)
        return send_file_response(
            filename=filename,
            content_to_send=io.BytesIO(blob),
            mtype=mtype or "image/jpeg",
            attachment=False,
            last_modified=None,
            expiration=300,
        )
        return response
