import os, sys
import django

# sys.path.append('/abs/path/to/my-project/)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'quickbbs.settings')
django.setup()

# Use
from quickbbs.models import Index_Dirs, Thumbnails_Dirs, convert_text_to_md5_hdigest

new_dir_index = Index_Dirs

# class Index_Dirs(models.Model):
#     uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True, blank=True)
#     DirName = models.CharField(db_index=False, max_length=384, default='', blank=True)  # FQFN of the file itself
#     WebPath_md5 = models.CharField(db_index=True, max_length=32, unique=False)
#     DirName_md5 = models.CharField(db_index=True, max_length=32, unique=False)
#     Combined_md5 = models.CharField(db_index=True, max_length=32, unique=True)
#     is_generic_icon = models.BooleanField(default=False, db_index=True)  # File is to be ignored
#     ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
#     delete_pending = models.BooleanField(default=False, db_index=True)  # File is to be deleted,
#     SmallThumb = models.BinaryField(default=b"")

# class Thumbnails_Dirs(models.Model):
#     id = models.AutoField(primary_key=True, db_index=True)
#     uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True, blank=True)
#     DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)  # FQFN of the file itself
#     FileSize = models.BigIntegerField(default=-1)
#     FilePath = models.CharField(db_index=True, max_length=384, default=None)  # FQFN of the file itself
#     SmallThumb = models.BinaryField(default=b"")
#
for entry in Thumbnails_Dirs.objects.all():
    print(entry.FilePath)
    Combined_md5 = convert_text_to_md5_hdigest(entry.FilePath)
    found, record = Index_Dirs.search_for_directory(entry.FilePath)
    if found:
        print("existing:", record.Parent_Dir_md5)
        parent_dir = os.path.abspath(os.path.join(entry.DirName,".."))
        if record.Parent_Dir_md5 in [None, ""]:
            md5 = convert_text_to_md5_hdigest(parent_dir)
            print(parent_dir, md5)
            record.parent_dir_md5 = str(md5)
            record.save(force_update=True, update_fields=["Parent_Dir_md5"])
    else:
        record = Index_Dirs.add_directory(fqpn_directory=entry.FilePath,
                                          thumbnail = entry.SmallThumb)
        record.SmallThumb = entry.SmallThumb
        record.save()
#    sys.exit()
