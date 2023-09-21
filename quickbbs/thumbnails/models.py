import os
# from io import BytesIO
import uuid

from django.conf import settings
from django.db import models

# from frontend.thumbnail import cr_tnail_img

# from uuid import uuid4


__version__ = '1.5'

__author__ = 'Benjamin Schollnick'
__email__ = 'Benjamin@schollnick.net'

__url__ = 'https://github.com/bschollnick/quickbbs'
__license__ = 'TBD'

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


def is_valid_uuid(uuid_to_test, version=4) -> bool:
    """
    Check if uuid_to_test is a valid UUID.
    https://stackoverflow.com/questions/19989481

    Args:
        uuid_to_test (str) - UUID code to validate
        version (int) - UUID version to validate against (eg  1, 2, 3, 4)

    Returns:
        boolean::
            `True` if uuid_to_test is a valid UUID, otherwise `False`.

    Raises:
        None

    Examples
    --------
    >>> is_valid_uuid('c9bf9e57-1685-4c89-bafb-ff5af830be8a')
    True
    >>> is_valid_uuid('c9bf9e58')
    False
    """
    try:
        uuid_obj = uuid.UUID(uuid_to_test, version=version)
    except:
        return False

    return str(uuid_obj) == uuid_to_test


def invalidate_thumb(thumbnail):
    """
    The invalidate_thumb function takes a thumbnail object and sets its file size to -1
    and clears all the thumbnails. This is done so that when we call update_thumb, it will
    be forced to regenerate the thumbnails from the original image.

    :param thumbnail: Specify the thumbnail to be invalidated
    :return: The thumbnail object with the file size set to - 1, and all of the thumbnails
        as empty bytes
    :doc-author: Trelent
    """
    thumbnail.FileSize = -1
    thumbnail.SmallThumb.Thumbnail = b""
    thumbnail.MediumThumb.Thumbnail = b""
    thumbnail.LargeThumb.Thumbnail = b""
    return thumbnail


class SmallThumb(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, unique=True, db_index=True, blank=True)
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)

    def add_thumb(self, imagedata, fext):
        """
        The add_thumb function adds a thumbnail image to the database.
        It takes two arguments: imagedata and fext.
        imagedata is the image data of the thumbnail, in binary form.
        fext is an optional argument that specifies what file extension
            should be used for this thumbnail (e.g., .png).
            If not specified, it defaults to whatever format the original image was in.

        :param self: Refer to the instance of the object itself
        :param imagedata: Save the image data to the database
        :param fext: Determine the file extension of the thumbnail image
        :return: The path to the thumbnail image
        :doc-author: Trelent
        """
        import cr_tnail_img
        self.Thumbnail = cr_tnail_img(imagedata,
                                      settings.IMAGE_SIZES["small"],
                                      fext=fext)
        self.save()

    def get_thumb(self):
        """
        The get_thumb function returns the thumbnail of a given image.


        :param self: Access variables that belongs to the class
        :return: The value of the thumbnail variable
        :doc-author: Trelent
        """
        return self.Thumbnail

    class Meta:
        verbose_name = 'Image File Small Thumbnail Cache'
        verbose_name_plural = 'Image File Small Thumbnails Cache'


class MediumThumb(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, unique=True, db_index=True, blank=True)
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)

    def add_thumb(self, imagedata, fext):
        """
        The add_thumb function adds a thumbnail to the image.
        It takes two arguments: imagedata and fext.
        imagedata is the binary data of an image file, and fext is its extension (e.g., jpg).
        The function creates a thumbnail from the imagedata using cr_tnail_img,
        which returns a string containing base64 encoded data for an image file with
        size &quot;medium&quot;. The function then sets self's Thumbnail attribute to this string.

        :param self: Refer to the instance of the object itself
        :param imagedata: Store the image data
        :param fext: Determine the file extension of the thumbnail image
        :return: The thumbnail image
        :doc-author: Trelent
        """
        import cr_tnail_img
        self.Thumbnail = cr_tnail_img(imagedata,
                                      settings.IMAGE_SIZES["medium"],
                                      fext=fext)
        self.save()

    def get_thumb(self):
        """
        The get_thumb function returns the thumbnail of a given image.


        :param self: Access variables that belongs to the class
        :return: The value of the thumbnail variable
        :doc-author: Trelent
        """
        return self.Thumbnail

    class Meta:
        verbose_name = 'Image File Medium Thumbnail Cache'
        verbose_name_plural = 'Image File Medium Thumbnails Cache'


class LargeThumb(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, unique=True, db_index=True, blank=True)
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)

    def add_thumb(self, imagedata, fext):
        """
        The add_thumb function adds a thumbnail image to the database.
        It takes two arguments: imagedata and fext.
        imagedata is the image data of the thumbnail, and fext is its file extension.

        :param self: Refer to the instance of the object itself
        :param imagedata: Specify the image data to be used for
        :param fext: Determine the file extension of the thumbnail image
        :return: A thumbnail image
        :doc-author: Trelent
        """
        import cr_tnail_img
        self.Thumbnail = cr_tnail_img(imagedata,
                                      settings.IMAGE_SIZES["large"],
                                      fext=fext)
        self.save()

    def get_thumb(self):
        """
        The get_thumb function returns the thumbnail of a given image.


        :param self: Access variables that belongs to the class
        :return: The value of the thumbnail variable
        :doc-author: Trelent
        """
        return self.Thumbnail

    class Meta:
        verbose_name = 'Image File Large Thumbnail Cache'
        verbose_name_plural = 'Image File Large Thumbnails Cache'


def create_file_entry(filename, filesize=None, is_default=False, version=4) -> object:
    record_id = uuid4()
    record_id = uuid.UUID(uuid_to_test, version=version)
    # filename = filename
    if filesize is None:
        filesize = os.path.getsize(filename)
    # else:
    #    filesize = filesize

    # is_default = is_default
    ignore = False

    small = SmallThumb.objects.create(uuid=record_id, FileSize=filesize, Thumbnail=b'')

    medium = MediumThumb.objects.create(uuid=record_id, FileSize=filesize, Thumbnail=b'')

    large = LargeThumb.objects.create(uuid=record_id, FileSize=filesize, Thumbnail=b'')

    entry = Thumbnails_Files.objects.create(uuid=record_id, FileName=filename,
                                            FileSize=filesize,
                                            SmallThumb=small, MediumThumb=medium,
                                            LargeThumb=large,
                                            is_default=is_default, ignore=ignore)
    return entry


class Thumbnails_Files(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, unique=True, db_index=True, blank=True)
    FileName = models.CharField(db_index=True, max_length=384, default=None)
    FileSize = models.BigIntegerField(default=-1)
    SmallThumb = models.OneToOneField(SmallThumb,
                                      on_delete=models.CASCADE,
                                      db_index=True,
                                      default=None,
                                      null=True,
                                      blank=True)

    MediumThumb = models.OneToOneField(MediumThumb,
                                       on_delete=models.CASCADE,
                                       db_index=True,
                                       default=None,
                                       null=True,
                                       blank=True)
    LargeThumb = models.OneToOneField(LargeThumb,
                                      on_delete=models.CASCADE,
                                      db_index=True,
                                      default=None,
                                      null=True,
                                      blank=True)

    is_default = models.BooleanField(default=False, db_index=False)
    ignore = models.BooleanField(default=False, db_index=False)

    def add_small(self, image_data):
        """
        The add_small function adds a small thumbnail to the database.
        It takes an image_data argument, which is the data of the image file.
        The function then uses cr_tnail_img to create a smaller version of
        that image and saves it in self.SmallThumb.

        :param self: Refer to the object that is calling the method
        :param image_data: Store the image data of the thumbnail
        :return: The image data of the small thumbnail
        :doc-author: Trelent
        """
        fext = os.path.splitext(self.FileName)[1][1:].lower()
        # image_data = cr_tnail_img(image_data, settings.IMAGE_settings.IMAGE_SIZES["small"], fext=fext)
        self.SmallThumb.add_thumb(image_data, fext=fext)
        self.SmallThumb.save()
        self.save()

    def add_medium(self, image_data):
        """
        The add_medium function adds a medium to the database.
        It takes an image_data argument, which is a string of binary data from an uploaded file.
        The function also requires that the FileName attribute be set before calling it.

        :param self: Refer to the instance of the class
        :param image_data: Pass the image data to the add_thumb function
        :return: The value of self
        :doc-author: Trelent
        """
        fext = os.path.splitext(self.FileName)[1][1:].lower()
        self.SmallThumb.add_thumb(image_data, fext=fext)
        self.SmallThumb.save()
        self.save()

    def add_large(self, image_data):
        """
        The add_large function adds a large thumbnail to the database.
        It takes an image_data argument, which is a string of binary data from the uploaded file.
        The fext argument is optional and defaults to the extension on FileName (e.g., .jpg).


        :param self: Refer to the instance of the class
        :param image_data: Store the image data in the database
        :return: None
        :doc-author: Trelent
        """
        fext = os.path.splitext(self.FileName)[1][1:].lower()
        self.LargeThumb.add_thumb(image_data, fext=fext)
        self.LargeThumb.save()
        self.save()

    class Meta:
        verbose_name = 'Thumbnails Index for Files'
        verbose_name_plural = 'Thumbnails Index for Files'
        # File Workflow:
        #
        #   When checking for a thumbnail, if Thumbnail_ID == 0, then generate
        #   the new thumbnails,
        #   and set the Thumbnail_ID for the file.
        #
        #   If the file has been flagged as changed, then:
        #       Grab the Thumbnail_ID record and set Flag_For_Regeneration to True
        #
        #   If the Thumbnail_ID record is set, check the Thumbnail_ID record for
        #   Flag_For_Regeneration, and if True, then Regenerate the Thumbnails.


class Thumbnails_Archive(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    zipfilepath = models.CharField(db_index=True, max_length=384, default='', blank=True)

    FilePath = models.CharField(db_index=True, max_length=384, default=None)
    FileName = models.CharField(db_index=True, max_length=384, default=None)
    SmallThumb = models.BinaryField(default=b"")

    class Meta:
        verbose_name = 'Archive Thumbnails Cache'
        verbose_name_plural = 'Archive Thumbnails Cache'


class Thumbnails_Archive_Pages(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    page = models.IntegerField(default=0)
    FileSize = models.BigIntegerField(default=-1)
    SmallThumb = models.BinaryField(default=b"")
    MediumThumb = models.BinaryField(default=b"")
    LargeThumb = models.BinaryField(default=b"")

    class Meta:
        verbose_name = 'Archive Pages Cache'
        verbose_name_plural = 'Archive Pages Cache'


class Thumbnails_Dir(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True)
    DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)
    FileName = models.CharField(db_index=True, max_length=384, default='', blank=True)
    FileSize = models.BigIntegerField(default=-1)
    Thumbnail = models.OneToOneField(SmallThumb,
                                     on_delete=models.CASCADE,
                                     db_index=True,
                                     default=None,
                                     null=True,
                                     blank=True)
    is_default = models.BooleanField(default=False, db_index=False)

    class Meta:
        verbose_name = 'Directory Thumbnails Cache'
        verbose_name_plural = 'Directory Thumbnails Cache'
