import hashlib
import io

# from io import BytesIO
import mimetypes
import os
from functools import lru_cache

from django.conf import settings
from django.db import models
from django.http import FileResponse

from .image_utils import resize_pil_image, return_image_obj

# from frontend.thumbnail import cr_tnail_img

# from uuid import uuid4


__version__ = "1.9"

__author__ = "Benjamin Schollnick"
__email__ = "Benjamin@schollnick.net"

__url__ = "https://github.com/bschollnick/quickbbs"
__license__ = "TBD"

"""
The models, and logic for thumbnail storage for the Quickbbs reloaded project.

* Thumbnail Files - Is the core storage for the thumbnails.  This stores the actual
    data for the thumbnail (e.g. FileSize, FileName, uuid, etc.  The actual
    thumbnail is stored in the *Thumb tables (see below) )

    These tables are the binary storage for Thumbnail Files.
    * SmallThumb - The binary storage for the Small Thumbnails
    * MediumThumb - The Binary storage for the Medium Thumbnails
    * LargeThumb - The Binary Storage for the Large Thumbnails

create_file_entry(filename, filesize, is_default)
    Is used to create the initial record, and creates the small, medium, and large
    Thumbnails in a "empty" placeholder fashion.

    If filesize is None, then create_file_entry will use os.path.getsize to get the
    files filesize.

"""


class ThumbnailFiles(models.Model):
    sha256_hash = models.CharField(
        db_index=True, blank=True, unique=True, null=True, default=None
    )
    fqpn_filename = models.CharField(
        db_index=True,
        max_length=384,
        default=None,
        unique=True,
    )  # FQFN of the file itself
    small_thumb = models.BinaryField(default=b"", null=True)
    medium_thumb = models.BinaryField(default=b"", null=True)
    large_thumb = models.BinaryField(default=b"", null=True)

    class Meta:
        verbose_name = "Image File Thumbnails Cache"
        verbose_name_plural = "Image File Thumbnails Cache"

    def number_of_IndexData_references(self):
        """
        Given a sha256 hash, return the number of IndexData references
        """
        from quickbbs.models import IndexData
        return IndexData.objects.filter(sha256_hash=self.sha256_hash).count()
    
    @lru_cache(maxsize=250)
    def get_thumbnail_by_sha(self, sha256):
        """
        Given a sha256 hash, return the thumbnail object
        """
        return ThumbnailFiles.objects.get(sha256_hash=sha256)

    def thumbnail_exists(self, size="small"):
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

        :param thumbnail: Store the thumbnail data
        :return: The thumbnail object
        >>> test = quickbbs.models.IndexData()
        >>> test = invalidate_thumb(test)
        """
        self.small_thumb = b""
        self.medium_thumb = b""
        self.large_thumb = b""


    def pil_to_thumbnail(self, pil_data):
        """

        Args:
            pil_data:

        # https://stackoverflow.com/questions/1167398/python-access-class-property-from-string

        """
        self.invalidate_thumb()
        fext = os.path.splitext(self.fqpn_filename)[1][1:].lower()
        img_original = pil_data
        for size in ["large", "medium", "small"]:
            setattr(
                self,
                f"{size}_thumb",
                resize_pil_image(img_original, settings.IMAGE_SIZE[size], fext=fext),
            )

    def image_to_thumbnail(self):
        """
        Since we are just looking for a thumbnailable image, it doesn't have
        to be the most up to date, nor the most current.  Cached is fine.

        https://stackoverflow.com/questions/1167398/python-access-class-property-from-string
        """
        fext = os.path.splitext(self.fqpn_filename)[1][1:].lower()
        self.invalidate_thumb()
        img_original = return_image_obj(self.fqpn_filename)
        for size in ["large", "medium", "small"]:
            setattr(
                self,
                f"{size}_thumb",
                resize_pil_image(img_original, settings.IMAGE_SIZE[size], fext=fext),
            )
        self.save(update_fields=["small_thumb", "medium_thumb", "large_thumb", "fqpn_filename"])

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
        mtype = "image/jpeg"
        blob = self.retrieve_sized_tnail(size=size)
        response = FileResponse(
            io.BytesIO(blob),
            content_type=mtype,
            as_attachment=False,
            filename=filename_override or self.fqpn_filename,
        )
        response["Content-Type"] = mtype
        response["Content-Length"] = len(blob)
        return response
