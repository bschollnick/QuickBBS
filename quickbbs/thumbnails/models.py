import os

# from io import BytesIO

from django.conf import settings
from django.db import models
from .image_utils import cr_tnail_img, return_image_obj

# from frontend.thumbnail import cr_tnail_img

# from uuid import uuid4


__version__ = "1.5"

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
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    fqpn_filename = models.CharField(
        db_index=True,
        max_length=384,
        default=None,
        unique=True,
    )  # FQFN of the file itself
    file_size = models.BigIntegerField(default=-1)

    small_thumb = models.BinaryField(default=b"")
    medium_thumb = models.BinaryField(default=b"")
    large_thumb = models.BinaryField(default=b"")

    class Meta:
        verbose_name = "Image File Thumbnails Cache"
        verbose_name_plural = "Image File Thumbnails Cache"

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
        self.file_size = -1
        self.small_thumb = b""
        self.medium_thumb = b""
        self.large_thumb = b""

    def image_to_thumbnail(self):
        """

        Since we are just looking for a thumbnailable image, it doesn't have
        to be the most up to date, nor the most current.  Cached is fine.
        """
        fext = os.path.splitext(self.fqpn_filename)[1][1:].lower()
        self.invalidate_thumb()

        # https://stackoverflow.com/questions/1167398/python-access-class-property-from-string
        img_original = return_image_obj(self.fqpn_filename)
        #
        for size in ["large", "medium", "small"]:
            image_thumbnail = cr_tnail_img(
                img_original, settings.IMAGE_SIZE[size], fext=fext
            )
            setattr(self, f"{size}_thumb", image_thumbnail)
