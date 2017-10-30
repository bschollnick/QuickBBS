from __future__ import unicode_literals

from django.db import models

class DirEntry(models.Model):
    id = models.AutoField(primary_key=True)
    LastMod = models.DateField(db_index = True)
    LastScan = models.DateField(db_index = True)
    DirFQFN = models.CharField(db_index = True, max_length=512, default=None)
    DirURL = models.CharField(db_index = True, max_length=512, default=None)
    NumFiles = models.IntegerField(default=0)
    NumDirs = models.IntegerField(default=0)
    ParentDirID = models.IntegerField(default=0, db_index=True)
    ThumbFQFN = models.CharField(db_index = True, max_length=512, default=None)
    ThumbURL = models.CharField(db_index = True, max_length=512, default=None)
    Ignore = models.BooleanField(default=False, db_index=True)

# Create your models here.
class FileEntry(models.Model):
    id = models.AutoField(primary_key=True)
    LastMod = models.DateField(db_index = True)
    LastScan = models.DateField(db_index = True)
    FilenameName = models.CharField(db_index = True, max_length=512, default=None)
    FileSize = models.IntegerField(default=0)
    NumDirs = models.IntegerField(default=0)
    ParentDirID = models.IntegerField(default=0)
    ThumbFQFN = models.CharField(db_index = True, max_length=512, default=None)
    ThumbURL = models.CharField(db_index = True, max_length=512, default=None)
    IgnoreFile = models.BooleanField(default=False, db_index=True)
    DeletePending = models.BooleanField(default=False, db_index=True)

