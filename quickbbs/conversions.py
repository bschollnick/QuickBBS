import os
import sys

import django

# sys.path.append('/abs/path/to/my-project/)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")
django.setup()

from quickbbs.models import IndexData, IndexDirs, convert_text_to_md5_hdigest
from thumbnails.models import ThumbnailFiles
import pprint
import os
# for entry in IndexData.objects.all():
#     # pprint.pprint(entry.__dict__)
#     fs_item = os.path.join(entry.fqpndirectory, entry.name).title().strip()
#     if not os.path.exists(fs_item):
#         print("deleting")
#         entry.delete()
#         continue

for entry in IndexDirs.objects.all():
#     # pprint.pprint(entry.__dict__)
     fs_item = os.path.join(entry.fqpndirectory).title().strip()
     if not os.path.exists(fs_item):
        print("deleting")
        entry.delete()
        continue

    #entry.file_sha256 = entry.get_file_sha(fqfn=fs_item)
    #print("updating")
    #entry.save(update_fields=["file_sha256"])
#  index_qs = (
#         IndexData.objects.prefetch_related("new_ftnail")
#         .prefetch_related("filetype")
#         .filter(uuid=tnail_id)
#     )
#     if not index_qs.exists():
#         # does not exist
#         print(tnail_id, "File not found - No records returned.")
#         return Http404

#     thumbsize = request.GET.get("size", "small").lower()
#     entry = index_qs[0]
#     fs_item = os.path.join(entry.fqpndirectory, entry.name).title().strip()
#     fs_item_hash = ThumbnailFiles.convert_text_to_md5_hdigest(fs_item)
#     # fname = os.path.basename(entry.name).title().strip()
#     if entry.new_ftnail:
#         if entry.new_ftnail.thumbnail_exists(size=thumbsize):
#             return entry.new_ftnail.send_thumbnail(
#                 filename_override=None, fext_override=".jpg", size=thumbsize
#             )

# for uuid in IndexData.objects.filter(new_ftnail__sha256_hash=None).values_list("uuid", flat=True):
#     entry = (
#         IndexData.objects.prefetch_related("new_ftnail")
#         .prefetch_related("filetype")
#         .filter(uuid=uuid)
#     )[0]
#     fs_item = os.path.join(entry.fqpndirectory, entry.name).title().strip()
#     if not entry.new_ftnail:
#         continue # no thumbnail has been created
# #    print(fs_item)
#     if not entry.new_ftnail.thumbnail_exists(size="small"):
#         print("Skipping")
#         continue
#     fs_item_hash = ThumbnailFiles.convert_text_to_md5_hdigest(fs_item)
#     #print(fs_item_hash)
#     Thumbnail = ThumbnailFiles.objects.filter(fqpn_hash=fs_item_hash)[0]
#     #Thumbnail = ThumbnailFiles.objects.filter(fqpn_filename=fs_item)[0]
#     Thumbnail.sha256_hash = entry.file_sha256
#     Thumbnail.save(update_fields=["sha256_hash"])
# Thumbnail.save(update_fields=["sha256_hash"])
# tnail = ThumbnailFiles.objects.filter(pk=IndexFile.new_ftnail)
# IndexFile.new_ftnail.save(update_fields=["sha256_hash"])

# for thumbnail in ThumbnailFiles.objects.filter(sha256_hash=None):
#    parent_file = IndexData.objects.filter(fqpnfile=thumbnail.fqpn_filename)

# new_dir_index = Index_Dirs

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

# good
# for directory in index_data.objects.all().values("fqpndirectory").distinct():
#     found, dir_entry = Index_Dirs.search_for_directory(directory["fqpndirectory"])
#     # print(found, directory["fqpndirectory"], dir_entry)
#     files = index_data.objects.filter(fqpndirectory=directory["fqpndirectory"])
#     if dir_entry != files[0].parent_dir:
#         print(f"updated {dir_entry.DirName}")
#         files.update(parent_dir=dir_entry)
#         sys.exit()

# old
# for entry in Thumbnails_Dirs.objects.all():
#     Combined_md5 = convert_text_to_md5_hdigest(entry.FilePath)
#     found, record = Index_Dirs.search_for_directory(entry.FilePath)
#     if found:
#         parent_dir = os.path.abspath(os.path.join(entry.DirName,".."))
#         if record.Parent_Dir_md5 in [None, ""]:
#             md5 = convert_text_to_md5_hdigest(parent_dir)
#             record.parent_dir_md5 = str(md5)
#             record.save(update_fields=["Parent_Dir_md5"])
#     else:
#         record = Index_Dirs.add_directory(fqpn_directory=entry.FilePath,
#                                           thumbnail = entry.SmallThumb)
#         record.SmallThumb = entry.SmallThumb
#         record.save()
# for directory in index_data.objects.filter(parent_dir=None).values("fqpndirectory").distinct():
#     found, dir_entry = Index_Dirs.search_for_directory(directory["fqpndirectory"])
#     print(found, directory["fqpndirectory"], dir_entry)
#     if not found:
#         dir_entry = Index_Dirs.add_directory(fqpn_directory=directory["fqpndirectory"])
#     files = index_data.objects.filter(parent_dir=None, fqpndirectory=directory["fqpndirectory"])
#     files.update(parent_dir=dir_entry)


#    sys.exit()
