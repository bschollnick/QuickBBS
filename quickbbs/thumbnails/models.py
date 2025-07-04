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
from django.db import models
from django.http import FileResponse
from django.db import transaction

# from .image_utils import resize_pil_image, return_image_obj
from .thumbnail_engine import create_thumbnails_from_path
from frontend.serve_up import send_file_response

__version__ = "4.0"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/quickbbs"
__license__ = "TBD"


ThumbnailFiles_Prefetch_List = [
    "IndexData",
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
        file_sha256, suppress_save=False
    ) -> "ThumbnailFiles":
        """
        Given a sha256 hash, return the thumbnail object, or create it if it
        does not exist.

        Args:
            file_sha256 (str): The sha256 hash of the file to retrieve or create a thumbnail for.

        Returns:
            ThumbnailFiles: The thumbnail object, either retrieved or created.
        """

        from quickbbs.models import IndexData

        make_link = False
        defaults = {
            "sha256_hash": file_sha256,
            "small_thumb": b"",
            "medium_thumb": b"",
            "large_thumb": b"",
        }
        with transaction.atomic():
            thumbnail, created = ThumbnailFiles.objects.prefetch_related(
                *ThumbnailFiles_Prefetch_List
            ).get_or_create(sha256_hash=file_sha256, defaults=defaults)

            if thumbnail.IndexData.all().exists():
                # Reverse lookup to get the first IndexData model that matches this sha256
                #           print("Found IndexData item for sha256:")
                index_data_item = thumbnail.IndexData.first()
            else:
                # Go the long way around to get the IndexData item, presumably there are no
                # active IndexData items that match this sha256, so we will just get the first one
                #            print("No active IndexData items found, Going the long way around:")
                index_data_item = IndexData.objects.filter(
                    file_sha256=file_sha256
                ).first()
                make_link = True

            make_link = (
                make_link
                or created
                or IndexData.objects.filter(
                    file_sha256=file_sha256, new_ftnail__isnull=True
                ).exists()
            )
            filename = os.path.join(index_data_item.fqpndirectory, index_data_item.name)
            filetype = index_data_item.filetype

            if make_link:
                thumbnail.save()
                IndexData.objects.filter(
                    file_sha256=file_sha256,
                    new_ftnail__isnull=True,  # Only update if not already set
                ).update(new_ftnail=thumbnail)

            if thumbnail.thumbnail_exists():
                return thumbnail
            else:
                if filetype.is_image:
                    # If the file is an image, we can create the thumbnail
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
                    # If the file is not an image, movie, or pdf, we cannot create a thumbnail
                    thumbnails = {
                        "small": b"",
                        "medium": b"",
                        "large": b"",
                    }
                thumbnail.small_thumb = thumbnails["small"]
                thumbnail.medium_thumb = thumbnails["medium"]
                thumbnail.large_thumb = thumbnails["large"]
                if suppress_save:
                    pass
                else:
                    thumbnail.save(
                        update_fields=["small_thumb", "medium_thumb", "large_thumb"]
                    )
        return thumbnail

    def number_of_indexdata_references(self):
        """
        Given a sha256 hash, return the number of IndexData references
        """
        from quickbbs.models import IndexData

        return IndexData.objects.filter(file_sha256=self.sha256_hash).count()

    @lru_cache(maxsize=250)
    def get_thumbnail_by_sha(self, sha256):
        """
        Given a sha256 hash, return the thumbnail object
        """
        return ThumbnailFiles.objects.prefetch_related(
            *ThumbnailFiles_Prefetch_List
        ).get(sha256_hash=sha256)

    def thumbnail_exists(self, size="small"):
        """
        Check if the thumbnail exists for the given size.

        Args:
            size (str): The size of the thumbnail to check for (eg. small, medium, large).

        Returns:
            bool: True if the thumbnail exists, False otherwise.
        """
        match size.lower():
            case "small":
                return self.small_thumb not in ["", b"", None]
            case "medium":
                return self.medium_thumb not in ["", b"", None]
            case "large":
                return self.large_thumb not in ["", b"", None]
        return False

    def invalidate_thumb(self):
        """
        The invalidate_thumb function accepts a Thumbnail object and sets all of its attributes
        to an empty byte string. It is used when the thumbnail file cannot be found on disk,
        or when the thumbnail file has been corrupted.

        Note:
            This function does not delete the thumbnail object, it simply clears the thumbnail data.
            This also does not save the object, so you will need to call save() after this.
            The intention is to clear the thumbnail data, so that it can be regenerated, so
            callling save here is potentially redundant.

        Args:
            thumbnail: Store the thumbnail data

        Returns:
            ThumbnailFile: The thumbnail object


        >>> test = quickbbs.models.IndexData()
        >>> test.invalidate_thumb()
        """
        self.small_thumb = b""
        self.medium_thumb = b""
        self.large_thumb = b""

    def retrieve_sized_tnail(self, size="small"):
        """
        Helper to get and pick the right size for the thumbnail to be sent
        :param size: The size string
        :param tnail: The thumbnail record to be checked
        :return: the blob that contains the image data
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

    def send_thumbnail(self, filename_override=None, fext_override=None, size="small"):
        """
         Output a http response header, for an image attachment.

        Args:
             filename (str): The filename to be sent with the thumbnail
             fext_override (str): Filename extension to use instead of the original file's ext
             size (str): The size string of the thumbnail to send (small, medium, large)

         Returns:
             object::
                 The Django response object that contains the attachment and header

         Raises:
             None

         Examples
         --------
         send_thumbnail("test.png")

        Note:
            Thumbnails are stored as jpeg's, not as other types, so we'll always be sending a
            jpeg as the thumbnail, until/unless it is stored differently (e.g. JPEG XL, PNG, etc)

        References:
            https://stackoverflow.com/questions/36392510/django-download-a-file
            https://stackoverflow.com/questions/27712778/
                   video-plays-in-other-browsers-but-not-safari
            https://stackoverflow.com/questions/720419/
                    how-can-i-find-out-whether-a-server-supports-the-range-header

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
