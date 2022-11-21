from django.db import models

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
        return '%s' % self.fileext

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
