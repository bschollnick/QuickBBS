from django.db import models

class fs_Cache_Tracking(models.Model):
    DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)   # FQFN of the file itself
    lastscan = models.FloatField()   # Stored as Unix TimeStamp (ms)

