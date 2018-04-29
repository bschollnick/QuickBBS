from __future__ import unicode_literals
#from uuid import uuid4
from django.contrib.auth.models import User
from django.db import models

class owners(models.Model):
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False)
    ownerdetails = models.OneToOneField(User,
                                        on_delete = models.CASCADE,
                                        db_index = True,
                                        default = None)

class Favorites(models.Model):
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False)

class Thumbnails_Dirs(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True)
    FileSize = models.BigIntegerField(default=-1)
    FilePath = models.CharField(db_index=True,
                                max_length=512,
                                default=None,
                                unique=False,
                                blank=False)   # FQFN of the file itself
    SmallThumb = models.BinaryField(default=b"")

class Thumbnails_Files(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True)
    FilePath = models.CharField(db_index=True,
                                max_length=512,
                                default=None,
                                unique=False,
                                blank=False)   # FQFN of the file itself
    FileName = models.CharField(db_index=True,
                                max_length=512,
                                default=None,
                                unique=False,
                                blank=False)   # FQFN of the file itself
    FileSize = models.BigIntegerField(default=-1)
    SmallThumb = models.BinaryField(default=b"")
    MediumThumb = models.BinaryField(default=b"")
    LargeThumb = models.BinaryField(default=b"")
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
    uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True)
    zipfilepath = models.CharField(db_index=True,
                                max_length=512,
                                default=None,
                                unique=False,
                                blank=False,
                                null=True)   # FQFN of the file itself

    FilePath = models.CharField(db_index=True,
                                max_length=512,
                                default=None,
                                unique=False,
                                blank=False)   # FQFN of the file itself
    FileName = models.CharField(db_index=True,
                                max_length=512,
                                default=None,
                                unique=False,
                                blank=False)   # FQFN of the file itself
    page = models.IntegerField(default=0)  # The
    FileSize = models.BigIntegerField(default=-1)
    SmallThumb = models.BinaryField(default=b"")
    MediumThumb = models.BinaryField(default=b"")
    LargeThumb = models.BinaryField(default=b"")


class index_data(models.Model):
    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True)
    lastscan = models.FloatField(db_index=True)   # Stored as Unix TimeStamp (ms)
    lastmod = models.FloatField(db_index=True)   # Stored as Unix TimeStamp (ms)
    name = models.CharField(db_index=True,
                            max_length=512,
                            default=None,
                            unique=False,
                            blank=False)   # FQFN of the file itself
    sortname = models.CharField(db_index=True,
                                editable=False,
                                max_length=512,
                                default="",
                                unique=False)   # FQFN of the file itself
    size = models.BigIntegerField(default=0)     # File size
    numfiles = models.IntegerField(default=0)  # The # of files in this directory
    numdirs = models.IntegerField(default=0)    # The # of Children Directories in this directory
    fqpndirectory = models.CharField(default=0, db_index=True, max_length=512)  # The actual Fully Qualified Path Name of the directory that it is contained in
    parent_dir_id = models.IntegerField(default=0)  # Directory that it is contained in
    is_dir = models.BooleanField(default=False, db_index=True)
    is_pdf = models.BooleanField(default=False, db_index=True)
    is_archive = models.BooleanField(default=False, db_index=True)
    is_image = models.BooleanField(default=False, db_index=True)
    ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
    delete_pending = models.BooleanField(default=False, db_index=True)  # File is to be deleted,
# select * from public.quickbbs_indexdata where "Ignore" is True;
    file_tnail = models.OneToOneField(Thumbnails_Files,
                                      on_delete = models.CASCADE,
                                      db_index = True,
                                      default=None,
                                      null = True)

    directory = models.OneToOneField(Thumbnails_Dirs,
                                     on_delete = models.CASCADE,
                                     db_index = True,
                                     default=None,
                                     null = True)
                                # https://stackoverflow.com/questions/38388423
    archives = models.OneToOneField(Thumbnails_Archives,
                                    on_delete = models.CASCADE,
                                    db_index = True,
                                    default=None,
                                    null = True)

    ownership = models.OneToOneField(owners,
                                     on_delete = models.CASCADE,
                                     db_index = True,
                                     default=None,
                                     null = True)
                                    # null = System Owned
