from __future__ import unicode_literals

from django.db import models
from datetime import datetime


class DirData(models.Model):
    id = models.AutoField(primary_key=True)
    LastScan = models.IntegerField(db_index=True)   # Stored as Unix TimeStamp (ms)

#    LastScan = models.DateTimeField(db_index=True)
#                                    default=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))#data.st[stat.ST_MTIME]default=time.time())  # Directory was last scanned on
    LastMod = models.IntegerField(db_index=True)   # Stored as Unix TimeStamp (ms)
    DirPN = models.CharField(db_index=True,
                             max_length=512,
                             default=None,
                             unique=False,
                             blank=False)  # The Fully Qualified Path Name to reach this directory
    DirURL = models.CharField(db_index=True,
                              max_length=512,
                              default=None,
                              unique=False,
                              blank=False)  # Expose this directory at this URL
    NumFiles = models.IntegerField(default=0)  # The # of files in this directory
    NumDirs = models.IntegerField(default=0)    # The # of Children Directories in this directory
    ParentDirID = models.IntegerField(default=0,
                                      db_index=True)  # The parent directory for this directory
    ThumbFQFN = models.CharField(db_index=True,
                                 max_length=512,
                                 default=None,
                                 unique=False,
                                 blank=False)  # The Image file used as the Thumbnail for this directory
    Ignore = models.BooleanField(default=False, db_index=True)  # This directory is not visible


# Create your models here.


class FileData(models.Model):
    id = models.AutoField(primary_key=True)
    LastScan = models.IntegerField(db_index=True)   # Stored as Unix TimeStamp (ms)
    LastMod = models.IntegerField(db_index=True)   # Stored as Unix TimeStamp (ms)
#    LastScan = models.DateTimeField(db_index=True)
#    LastMod = models.DateTimeField(db_index=True)
    FileName = models.CharField(db_index=True,
                                max_length=512,
                                default=None,
                                unique=False,
                                blank=False)   # FQFN of the file itself
    FileSize = models.IntegerField(default=0)     # File size
    FQPNDirectory = models.IntegerField(default=0)  # The actual Fully Qualified Path Name of the directory that it is contained in
    ParentDirID = models.IntegerField(default=0)  # Directory that it is contained in
    is_pdf = models.BooleanField(default=False, db_index=True)
    is_archive = models.BooleanField(default=False, db_index=True)
    Ignore = models.BooleanField(default=False, db_index=False)  # File is to be ignored
    DeletePending = models.BooleanField(default=False, db_index=False)  # File is to be deleted,
