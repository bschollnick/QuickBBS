#from __future__ import unicode_literals
from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse
import uuid

def is_valid_uuid(uuid_to_test, version=4):
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

class filetypes(models.Model):
    fileext = models.CharField(primary_key=True,
                               db_index=True,
                               max_length=10,
                               unique=True) # File Extension (eg. html)
    generic = models.BooleanField(default=False, db_index=True)

    icon_filename = models.CharField(db_index=True, max_length=384, default='', blank=True)   # FQFN of the file itself
    color = models.CharField(max_length=7, default="000000")

    # ftypes dictionary in constants / ftypes
    filetype = models.IntegerField(db_index=True,
                                   default=0,
                                   blank=True,
                                   null=True)
    # quick testers.
    # Originally going to be filetype only, but the SQL got too large
    # (eg retrieve all graphics, became is JPEG, GIF, TIF, BMP, etc)
    # so is_image is easier to fetch.
    is_image = models.BooleanField(default=False, db_index=True)
    is_archive = models.BooleanField(default=False, db_index=True)
    is_pdf = models.BooleanField(default=False, db_index=True)
    is_movie = models.BooleanField(default=False, db_index=True)
    is_dir = models.BooleanField(default=False, db_index=True)
    def __unicode__(self):
        return u'%s' % self.fileext

    def return_filetype(self, fileext):
        """
            fileext = gif, jpg, mp4 (lower case, and without prefix .)
        """
        fileext = fileext.lower()

        if fileext.startswith("."):
            fileext = fileext[1:]

        if fileext in ['', None, 'unknown']:
            fileext = ".none"

        return filetypes.objects.filter(fileext=fileext)


    class Meta:
            verbose_name = u'File Type'
            verbose_name_plural = u'File Types'

class owners(models.Model):
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True)
    ownerdetails = models.OneToOneField(User,
                                        on_delete = models.CASCADE,
                                        db_index = True,
                                        default = None)
    class Meta:
        verbose_name = u'Ownership'
        verbose_name_plural = u'Ownership'

class Favorites(models.Model):
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True)

class Cache_Tracking(models.Model):
    DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)   # FQFN of the file itself
    lastscan = models.FloatField()   # Stored as Unix TimeStamp (ms)


class Thumbnails_Dirs(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)   # FQFN of the file itself
    FileSize = models.BigIntegerField(default=-1)
    FilePath = models.CharField(db_index=True, max_length=384, default=None)   # FQFN of the file itself
    SmallThumb = models.BinaryField(default=b"")
    class Meta:
        verbose_name = u'Directory Thumbnails Cache'
        verbose_name_plural = u'Directory Thumbnails Cache'

class Thumbnails_Small(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)
    class Meta:
        verbose_name = u'Image File Small Thumbnail Cache'
        verbose_name_plural = u'Image File Small Thumbnails Cache'

class Thumbnails_Medium(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)
    class Meta:
        verbose_name = u'Image File Medium Thumbnail Cache'
        verbose_name_plural = u'Image File Medium Thumbnails Cache'

class Thumbnails_Large(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)
    class Meta:
        verbose_name = u'Image File Large Thumbnail Cache'
        verbose_name_plural = u'Image File Large Thumbnails Cache'


class Thumbnails_Files(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    FilePath = models.CharField(db_index=True, max_length=384, default=None)   # FQFN of the file itself
    FileName = models.CharField(db_index=True, max_length=384, default=None)   # FQFN of the file itself
    FileSize = models.BigIntegerField(default=-1)
    SmallThumb = models.BinaryField(default=b"")
    MediumThumb = models.BinaryField(default=b"")
    LargeThumb = models.BinaryField(default=b"")
    class Meta:
        verbose_name = u'Image File Thumbnails Cache'
        verbose_name_plural = u'Image File Thumbnails Cache'
        # File Workflow:
        #
        #   When checking for a thumbnail, if Thumbnail_ID == 0, then generate the new thumbnails,
        #   and set the Thumbnail_ID for the file.
        #
        #   If the file has been flagged as changed, then:
        #       Grab the Thumbnail_ID record and set Flag_For_Regeneration to True
        #
        #   If the Thumbnail_ID record is set, check the Thumbnail_ID record for
        #   Flag_For_Regeneration, and if True, then Regenerate the Thumbnails.

class Thumbnails_Archives(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    zipfilepath = models.CharField(db_index=True, max_length=384, default='', blank=True)   # FQFN of the file itself

    FilePath = models.CharField(db_index=True, max_length=384, default=None)   # FQFN of the file itself
    FileName = models.CharField(db_index=True, max_length=384, default=None)   # FQFN of the file itself
    page = models.IntegerField(default=0)  # The
    FileSize = models.BigIntegerField(default=-1)
    SmallThumb = models.BinaryField(default=b"")
    MediumThumb = models.BinaryField(default=b"")
    LargeThumb = models.BinaryField(default=b"")
    class Meta:
        verbose_name = u'Archive Thumbnails Cache'
        verbose_name_plural = u'Archive Thumbnails Cache'


class index_data(models.Model):
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    lastscan = models.FloatField(db_index=True)   # Stored as Unix TimeStamp (ms)
    lastmod = models.FloatField(db_index=True)   # Stored as Unix TimeStamp (ms)
    name = models.CharField(db_index=True, max_length=384, default=None)   # FQFN of the file itself
    sortname = models.CharField(db_index=True, editable=False, max_length=384, default='')   # FQFN of the file itself
    size = models.BigIntegerField(default=0)     # File size
    numfiles = models.IntegerField(default=0)  # The # of files in this directory
    numdirs = models.IntegerField(default=0)    # The # of Children Directories in this directory
    count_subfiles = models.BigIntegerField(default=0)  # the # of subfiles in archive
    fqpndirectory = models.CharField(default=0, db_index=True, max_length=384)  # The actual Fully Qualified Path Name of the directory that it is contained in
    parent_dir_id = models.IntegerField(default=0)  # Directory that it is contained in
    is_animated = models.BooleanField(default=False, db_index=True)
    ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
    delete_pending = models.BooleanField(default=False, db_index=True)  # File is to be deleted,
    filetype = models.ForeignKey(filetypes, to_field='fileext', on_delete = models.CASCADE,
                                 db_index = True, default=".none")
# select * from public.quickbbs_indexdata where "Ignore" is True;
    file_tnail = models.OneToOneField(
        Thumbnails_Files,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

    directory = models.OneToOneField(
        Thumbnails_Dirs,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )
                                # https://stackoverflow.com/questions/38388423
    archives = models.OneToOneField(
        Thumbnails_Archives,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

    ownership = models.OneToOneField(
        owners, on_delete=models.CASCADE, db_index=True, default=None, null=True, blank=True
    )


    def get_bg_color(self):
        return self.filetype.color

    def get_view_url(self):
        options = {}
        options["i_uuid"] = str(self.uuid)

        parameters = []
        parameters.append("?small")
        if self.filetype.is_pdf:
            parameters.append("&pdf")
        elif self.filetype.is_archive:
            parameters.append("&arch")
        if self.filetype.is_dir:
            return reverse('home')+self.fqpndirectory
        else:
            return reverse('new_viewitem', kwargs=options)+"".join(parameters)


    def get_download_url(self):
        return reverse('download', kwargs={"filename":self.name})+"?UUID="+str(self.uuid)
                                    # null = System Owned
    class Meta:
        verbose_name = u'Master Index'
        verbose_name_plural = u'Master Index'
