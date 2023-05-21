import os
import time
import uuid

from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse
from django.conf import settings

import thumbnails.models
from filetypes.models import filetypes


def is_valid_uuid(uuid_to_test, version=4):
    """
    Check if uuid_to_test is a valid UUID.
    https://stackoverflow.com/questions/19989481

    Args:
        uuid_to_test (str) - UUID code to validate
        version (int) - UUID version to validate against (eg  1, 2, 3, 4)

    Returns:
        boolean:
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


class owners(models.Model):
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True)
    ownerdetails = models.OneToOneField(User,
                                        on_delete=models.CASCADE,
                                        db_index=True,
                                        default=None)

    class Meta:
        verbose_name = 'Ownership'
        verbose_name_plural = 'Ownership'


class Favorites(models.Model):
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, blank=True)


class Thumbnails_Dirs(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)  # FQFN of the file itself
    FileSize = models.BigIntegerField(default=-1)
    FilePath = models.CharField(db_index=True, max_length=384, default=None)  # FQFN of the file itself
    SmallThumb = models.BinaryField(default=b"")

    class Meta:
        verbose_name = 'Directory Thumbnails Cache'
        verbose_name_plural = 'Directory Thumbnails Cache'
        constraints = [
                models.UniqueConstraint(fields=['DirName', 'FilePath'], name='unique_dir_thumb')
            ]


class Thumbnails_Small(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)

    class Meta:
        verbose_name = 'Image File Small Thumbnail Cache'
        verbose_name_plural = 'Image File Small Thumbnails Cache'


class Thumbnails_Medium(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)

    class Meta:
        verbose_name = 'Image File Medium Thumbnail Cache'
        verbose_name_plural = 'Image File Medium Thumbnails Cache'


class Thumbnails_Large(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    Thumbnail = models.BinaryField(default=b"")
    FileSize = models.BigIntegerField(default=-1)

    class Meta:
        verbose_name = 'Image File Large Thumbnail Cache'
        verbose_name_plural = 'Image File Large Thumbnails Cache'


class Thumbnails_Files(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    FilePath = models.CharField(db_index=True, max_length=384, default=None)  # FQFN of the file itself
    FileName = models.CharField(db_index=True, max_length=384, default=None)  # FQFN of the file itself
    FileSize = models.BigIntegerField(default=-1)
    SmallThumb = models.BinaryField(default=b"")
    MediumThumb = models.BinaryField(default=b"")
    LargeThumb = models.BinaryField(default=b"")

    class Meta:
        verbose_name = 'Image File Thumbnails Cache'
        verbose_name_plural = 'Image File Thumbnails Cache'
        constraints = [
                models.UniqueConstraint(fields=['FileName', 'FilePath'], name='unique_thumb_files')
            ]
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
    zipfilepath = models.CharField(db_index=True, max_length=384, default='', blank=True)  # FQFN of the file itself

    FilePath = models.CharField(db_index=True, max_length=384, default=None)  # FQFN of the file itself
    FileName = models.CharField(db_index=True, max_length=384, default=None)  # FQFN of the file itself
    page = models.IntegerField(default=0)  # The
    FileSize = models.BigIntegerField(default=-1)
    SmallThumb = models.BinaryField(default=b"")
    MediumThumb = models.BinaryField(default=b"")
    LargeThumb = models.BinaryField(default=b"")

    class Meta:
        verbose_name = 'Archive Thumbnails Cache'
        verbose_name_plural = 'Archive Thumbnails Cache'

        constraints = [
                models.UniqueConstraint(fields=['FileName', 'FilePath', 'zipfilepath'], name='unique_archives')
            ]

class scan_lock(models.Model):
    fqpndirectory = models.CharField(default=0, db_index=True, max_length=384, unique=True)

    def start_scan(self, fqpndirectory=None):
        if fqpndirectory is not None:
            self.fqpndirectory = str(fqpndirectory).title()
            self.save()

    def release_scan(fqpndirectory):
        scan_lock.objects.filter(fqpndirectory=str(fqpndirectory).title()).delete()

    def release_all():
        scan_lock.objects.all().delete()

    def scan_in_progress(fqpndirectory):
        return scan_lock.objects.filter(fqpndirectory=str(fqpndirectory).title()).exists()

    class Meta:
        verbose_name = 'Directory Scanning Lock'
        verbose_name_plural = 'Directory Scanning Locks'

#from django.db.models import Count
#index_dup = index_data.objects.values('id', 'name','fqpndirectory').annotate(name_count=Count('name'),dir_count = Count('fqpndirectory')).filter(name_count__gt=1,dir_count__gt=1)

class index_data(models.Model):
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True, blank=True)
    lastscan = models.FloatField(db_index=True)  # Stored as Unix TimeStamp (ms)
    lastmod = models.FloatField(db_index=True)  # Stored as Unix TimeStamp (ms)
    name = models.CharField(db_index=True, max_length=384, default=None)
    # FQFN of the file itself
    sortname = models.CharField(db_index=True, editable=False, max_length=384, default='')
    size = models.BigIntegerField(default=0)  # File size
    numfiles = models.IntegerField(default=0)  # The # of files in this directory
    numdirs = models.IntegerField(default=0)  # The # of Children Directories in this directory
    count_subfiles = models.BigIntegerField(default=0)  # the # of subfiles in archive
    fqpndirectory = models.CharField(default=0, db_index=True, max_length=384)
    # Directory of the file, lower().replace("//", "/"), ensure it is path, and not path + filename
    parent_dir_id = models.IntegerField(default=0)  # Directory that it is contained in
    is_animated = models.BooleanField(default=False, db_index=True)
    ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
    delete_pending = models.BooleanField(default=False, db_index=True)  # File is to be deleted,
    filetype = models.ForeignKey(filetypes, to_field='fileext', on_delete=models.CASCADE,
                                 db_index=True, default=".none")
    is_generic_icon = models.BooleanField(default=False, db_index=False)  # icon is a generic icon

    unified_thumb = models.OneToOneField(
        thumbnails.models.Thumbnails_Files,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

    unified_dirs = models.OneToOneField(
        thumbnails.models.Thumbnails_Dir,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

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


    def get_webpath(self):
        return self.fqpndirectory.replace(settings.ALBUMS_PATH.lower(), r"")


    def write_to_db_entry(self, fileentry, fqpn, version=4):
        """
        The write_to_db_entry function writes the fileentry to the index_data database.
        It takes a scandir entry and a fully qualified pathname as parameters.
        The function then determines if it is dealing with a directory or not, and
        then creates an appropriate FileType object for that file extension.
        If it is not an image, video, audio or archive type of file (as defined in
        the FILETYPE_DATA dictionary), then we will just create a generic FileType object
        that has no other attributes than being there.

        :param self: Reference the class instance
        :param fileentry: scandir entry
        :param fqpn: Pass the fully qualified pathname of the file to be scanned
        :param version=4: Generate a uuid version 4
        :return: None
        """
        """
        Start of Unified code.  WIP
        Intended to be the glue that writes the database entry.
        Parameters
        ----------
        fileentry : The scandir entry 
        fqpn : The fully qualified pathname of the file
        version : uuid version number

        Returns
        -------
            None:

        """
        if self.uuid is None:
            self.uuid = uuid.uuid(version=version)

        fext = os.path.splitext(fileentry.name)[1].lower()
        if fext == "":
            fext = ".none"
        self.filetypes(fileext=fext)

        if fileentry.is_dir():
            self.filetypes(fileext=".dir")
            fext = ".dir"

        if fext in [".gif"] and filetype_models.FILETYPE_DATA[fext]["is_image"]:
            try:
                animated = Image.open(os.path.join(fqpn, filename)).is_animated
                force_save = True
            except AttributeError:
                print(f"{fext} is not an animated GIF")

        numfiles = 0
        numdirs = 0
        lastscan = time.time()

    def get_bg_color(self):
        """
        Get the html / Cell background color of the file.

        Returns
        -------
        * The background hex color code of the current database entry
        """
        return self.filetype.color

    def get_view_url(self):
        """
        Generate the URL for the viewing of the current database item

        Returns
        -------
            Django URL object

        """
        options = {}
        options["i_uuid"] = str(self.uuid)

        parameters = []
        # parameters.append("?small")
        if self.filetype.is_pdf:
            parameters.append("&pdf")
        elif self.filetype.is_archive:
            parameters.append("&arch")
        if self.filetype.is_dir:
            return reverse('home') + self.fqpndirectory
        else:
            return reverse('new_viewitem', kwargs=options) + "".join(parameters)

    def get_download_url(self):
        """
        Generate the URL for the downloading of the current database item

        Returns
        -------
            Django URL object

        """
        return reverse('download', kwargs={"filename": self.name}) + "?UUID=" + str(self.uuid)
        # null = System Owned

    class Meta:
        verbose_name = 'Master Index'
        verbose_name_plural = 'Master Index'

        constraints = [
                models.UniqueConstraint(fields=['name', 'fqpndirectory'], name='unique name directory')
            ]
