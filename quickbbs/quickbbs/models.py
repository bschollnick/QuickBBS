from __future__ import unicode_literals

from django.db import models
from datetime import datetime
#from naturalsortfield import NaturalSortField

# class DirData(models.Model):
#     id = models.AutoField(primary_key=True)
#     LastScan = models.FloatField(db_index=True)  # Stored as Unix TimeStamp (ms)
#     LastMod = models.FloatField(db_index=True)   # Stored as Unix TimeStamp (ms)
#     DirPN = models.CharField(db_index=True,
#                              max_length=512,
#                              default=None,
#                              unique=False,
#                              blank=False)  # The Fully Qualified Path Name to reach this directory
#     DirURL = models.CharField(db_index=True,
#                               max_length=512,
#                               default=None,
#                               unique=False,
#                               blank=False)  # Expose this directory at this URL
#     NumFiles = models.IntegerField(default=0)  # The # of files in this directory
#     NumDirs = models.IntegerField(default=0)    # The # of Children Directories in this directory
#     ParentDirID = models.IntegerField(default=0,
#                                       db_index=True)  # The parent directory for this directory
#     ThumbFQFN = models.CharField(db_index=True,
#                                  max_length=512,
#                                  default=None,
#                                  unique=False,
#                                  blank=False)  # The Image file used as the Thumbnail for this directory
#     Ignore = models.BooleanField(default=False, db_index=True)  # This directory is not visible
#

# Create your models here.


class IndexData(models.Model):
    id = models.AutoField(primary_key=True)
    LastScan = models.FloatField(db_index=True)   # Stored as Unix TimeStamp (ms)
    LastMod = models.FloatField(db_index=True)   # Stored as Unix TimeStamp (ms)
    Name = models.CharField(db_index=True,
                            max_length=512,
                            default=None,
                            unique=False,
                            blank=False)   # FQFN of the file itself
    SortName = models.CharField(db_index=True,
                                editable=False,
                                max_length=512,
                                default="",
                                unique=False)   # FQFN of the file itself
    #FileName_Sort = NaturalSortField(for_field='FileName')     - django-naturalsortfield is giving odd error about max_length.
    Size = models.IntegerField(default=0)     # File size
    NumFiles = models.IntegerField(default=0)  # The # of files in this directory
    NumDirs = models.IntegerField(default=0)    # The # of Children Directories in this directory
    FQPNDirectory = models.CharField(default=0, db_index=True, max_length=512)  # The actual Fully Qualified Path Name of the directory that it is contained in
    ParentDirID = models.IntegerField(default=0)  # Directory that it is contained in
    is_dir = models.BooleanField(default=False, db_index=True)
    is_pdf = models.BooleanField(default=False, db_index=True)
    is_archive = models.BooleanField(default=False, db_index=True)
    Ignore = models.BooleanField(default=False, db_index=False)  # File is to be ignored
    DeletePending = models.BooleanField(default=False, db_index=False)  # File is to be deleted,
