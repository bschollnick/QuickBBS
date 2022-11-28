import os
from io import BytesIO
from uuid import uuid4

from django.db import models
from django.urls import reverse
#from frontend.utilities import return_image_obj
from PIL import Image

from frontend.thumbnail import cr_tnail_img, return_image_obj, sizes
"""
__version__ = '1.5'

__author__ = 'Benjamin Schollnick'
__email__ = 'Benjamin@schollnick.net'

__url__ = 'https://github.com/bschollnick/quickbbs'
__license__ = ''

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

def is_valid_uuid(uuid_to_test, version=4) -> uuid4:
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

def invalidate_thumb(thumbnail, imagesize="Small"):
    thumbnail.FileSize = -1
    thumbnail.Thumbnail = b""
    thumbnail.MediumThumb = b""
    thumbnail.LargeThumb = b""
    return thumbnail


class SmallThumb(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, unique=True, db_index=True, blank=True)
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)
    def add_thumb(self, imagedata, fext):
        self.Thumbnail = cr_tnail_img(imagedata,
                                      sizes["small"],
                                      fext=fext)
        self.save()

    def remove_thumb(self):
        self.FileSize = -1
        self.Thumbnail = b""

    def get_thumb(self):
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
        self.Thumbnail = cr_tnail_img(return_image_obj(imagedata),
                                      sizes["medium"],
                                      fext=fext)
        self.save()
        self.save()

    def remove_thumb(self):
        self.FileSize = -1
        self.Thumbnail = b""
        self.save()

    def get_thumb(self):
        return self.Thumbnail

    class Meta:
        verbose_name = 'Image File Medium Thumbnail Cache'
        verbose_name_plural = 'Image File Medium Thumbnails Cache'

class LargeThumb(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, unique=True, db_index=True, blank=True)
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)

    def add_thumb(self, imagedata, fext):
        self.Thumbnail = cr_tnail_img(return_image_obj(imagedata),
                                      sizes["medium"],
                                      fext=fext)
        self.save()

    def remove_thumb(self):
        self.FileSize = -1
        self.Thumbnail = b""
        self.save()

    def get_thumb(self):
        return self.Thumbnail

    class Meta:
        verbose_name = 'Image File Large Thumbnail Cache'
        verbose_name_plural = 'Image File Large Thumbnails Cache'

def create_file_entry(filename, filesize=None, is_default=False):
    uuid = uuid4()
    filename = filename
    if filesize is None:
        filesize = os.path.getsize(filename)
    else:
        filesize = filesize

    is_default = is_default
    ignore = False

    small = SmallThumb.objects.create(uuid=uuid, FileSize=filesize, Thumbnail=b'')

    medium = MediumThumb.objects.create(uuid=uuid, FileSize=filesize, Thumbnail=b'')

    large = LargeThumb.objects.create(uuid=uuid, FileSize=filesize, Thumbnail=b'')

    entry = Thumbnails_Files.objects.create(uuid=uuid, FileName=filename,
                                            FileSize=filesize,
                                            SmallThumb=small, MediumThumb=medium,
                                            LargeThumb=large,
                                            is_default=is_default, ignore=False)
    return entry

#        obj, created = self.objects.update_or_create(uuid=self.uuid)

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
        fext = os.path.splitext(self.FileName)[1][1:].lower()
        #image_data = cr_tnail_img(image_data, sizes["small"], fext=fext)
        obj, created = SmallThumb.objects.update_or_create(uuid=self.uuid,
                                                           FileSize=self.FileSize,
                                                           Thumbnail=b'',
                                                           defaults={'uuid':self.uuid,
                                                                     'FileSize':self.FileSize,
                                                                     'Thumbnail':b''})
        self.SmallThumb = obj
        self.SmallThumb.add_thumb(image_data, fext=fext)
        self.SmallThumb.save()
        self.save()

    def remove_small(self):
        self.SmallThumb.remove_thumb()
        self.save()

    def add_medium(self, image_data):
        self.MediumThumb.FileSize = self.FileSize
        self.MediumThumb.uuid = self.uuid
        self.MediumThumb.add_thumb(image_data)
        self.save()

    def remove_medium(self):
        self.MediumThumb.remove_thumb()


    def remove_small(self):
        self.SmallThumb.remove_thumb()
        self.save()

    def add_large(self, image_data):
        self.LargeThumb.FileSize = self.FileSize
        self.LargeThumb.uuid = self.uuid
        self.LargeThumb.add_thumb(image_data)
        self.save()

    def remove_large(self):
        self.LargeThumb.remove_thumb()
        self.save()

    def remove_all(self):
        self.remove_small()
        self.remove_medium()
        self.remove_large()

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

    def check_thumb(self):
        if self.FileSize != self.Thumbnail.FileSize:
            self.remove_thumb()

    def add_thumb(self, filename, fext):
        self.Thumbnail = cr_tnail_img(return_image_obj(filename),
                                      sizes["small"],
                                      fext=fext)
        self.save()

    def remove_thumb(self):
        self.FileSize = -1
        self.Thumbnail = b""
        self.save()

    def get_thumb(self):
        return self.Thumbnail

    class Meta:
        verbose_name = 'Directory Thumbnails Cache'
        verbose_name_plural = 'Directory Thumbnails Cache'
