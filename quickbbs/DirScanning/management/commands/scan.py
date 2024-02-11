import os
import pathlib
import sys

from django.core.management.base import BaseCommand

from cache.models import create_hash
from quickbbs.models import *


class Command(BaseCommand):
    help = (
        "Perform a Directory or File(s) scan to add/update/remove files from database"
    )

    def scan_directory(self, directory_paths=None):
        pass

    def scan_files(self, directory_paths=None):
        pass

    def add_arguments(self, parser):
        parser.add_argument(
            "scan",
            action="store",
            type=str,
            default=None,
            help="Directory to scan",
        )
        parser.add_argument(
            "--dir",
            action="store_true",
            help="Scan directories for importation",
        )
        parser.add_argument(
            "--files",
            action="store_true",
            help="Scan Files for importation",
        )

    def handle(self, *args, **options):
        directories_to_scan = options["scan"].split(",")
        print(directories_to_scan)
        print(args)
        print(options)
        if options["dir"]:
            self.scan_directory(directories_to_scan)
        sys.exit()
        if options["files"]:
            self.scan_files(directories_to_scan)


# # Use
# from quickbbs.models import Index_Dirs, Thumbnails_Dirs, convert_text_to_md5_hdigest
#
# new_dir_index = Index_Dirs
#
# # class Index_Dirs(models.Model):
# #     uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True, blank=True)
# #     DirName = models.CharField(db_index=False, max_length=384, default='', blank=True)  # FQFN of the file itself
# #     WebPath_md5 = models.CharField(db_index=True, max_length=32, unique=False)
# #     DirName_md5 = models.CharField(db_index=True, max_length=32, unique=False)
# #     Combined_md5 = models.CharField(db_index=True, max_length=32, unique=True)
# #     is_generic_icon = models.BooleanField(default=False, db_index=True)  # File is to be ignored
# #     ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
# #     delete_pending = models.BooleanField(default=False, db_index=True)  # File is to be deleted,
# #     SmallThumb = models.BinaryField(default=b"")
#
# # class Thumbnails_Dirs(models.Model):
# #     id = models.AutoField(primary_key=True, db_index=True)
# #     uuid = models.UUIDField(default=None, null=True, editable=False, db_index=True, blank=True)
# #     DirName = models.CharField(db_index=True, max_length=384, default='', blank=True)  # FQFN of the file itself
# #     FileSize = models.BigIntegerField(default=-1)
# #     FilePath = models.CharField(db_index=True, max_length=384, default=None)  # FQFN of the file itself
# #     SmallThumb = models.BinaryField(default=b"")
# #
# for entry in Thumbnails_Dirs.objects.all()[0:1]:
#     print(entry.FilePath)
#     #Combined_md5 = convert_text_to_md5_hdigest(entry.DirName)
#     found, record = Index_Dirs.search_for_directory(entry.DirName)
#     # if found:
#     #     if record.DirName != entry.FilePath:
#     #         record.DirName = entry.FilePath
#     #         record.save()
#     #     if record.SmallThumb == b"":
#     #         record.SmallThumb = entry.SmallThumb
#     #         record.save()
#     # else:
#     Index_Dirs.add_directory(fqpn_directory=entry.FilePath,
#                              thumbnail = entry.SmallThumb)
#     sys.exit()
#
