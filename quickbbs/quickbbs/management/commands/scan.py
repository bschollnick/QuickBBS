import asyncio
import os
import sys

from asgiref.sync import sync_to_async
from cache_watcher.models import Cache_Storage, fs_Cache_Tracking
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections, connections
from frontend.utilities import sync_database_disk

from quickbbs.models import IndexData, IndexDirs


def verify_directories():
    print("Checking for invalid directories in Database (eg. Deleted, Moved, etc).")
    start_count = IndexDirs.objects.count()
    print("Starting Directory Count: ", start_count)
    albums_root = os.path.join(settings.ALBUMS_PATH, "albums") + os.sep
    print("Gathering Directories")
    directories_to_scan = IndexDirs.objects.all().iterator(chunk_size=1000)
    print("Starting Scan")

    # Process directories WITHOUT closing connections during iteration
    # Server-side cursors don't survive close_old_connections()
    batch_counter = 0
    cache_instance = fs_Cache_Tracking()

    for directory in directories_to_scan:
        if not os.path.exists(directory.fqpndirectory):
            print(f"Directory: {directory.fqpndirectory} does not exist")
            directory.delete_directory(fqpn_directory=directory.fqpndirectory)
        else:
            # Check if directory exists in fs_Cache_Tracking
            if not fs_Cache_Tracking.objects.filter(directory_sha256=directory.dir_fqpn_sha256).exists():
                cache_instance.add_to_cache(directory.fqpndirectory)
                print(f"Added directory to fs_Cache_Tracking: {directory.fqpndirectory}")

        batch_counter += 1
        if batch_counter % 1000 == 0:
            print(f"Processed {batch_counter} directories...")

    # Only close connections AFTER iteration is complete
    close_old_connections()

    end_count = IndexDirs.objects.count()
    print("Ending Count: ", end_count)
    print("Difference : ", start_count - end_count)
    print("-" * 30)
    print("Checking for unlinked parents")
    unlinked_parents = IndexDirs.objects.filter(parent_directory__isnull=True).exclude(fqpndirectory=albums_root)
    # exclude the albums_root, since that is suppose to have no parent.  You can't tranverse below the albums_root
    print(f"Found {unlinked_parents.count()} directories with no parents")

    batch_counter = 0
    for directory in unlinked_parents.iterator(chunk_size=1000):
        IndexDirs.add_directory(directory.fqpndirectory)

        batch_counter += 1
        if batch_counter % 1000 == 0:
            print(f"Processed {batch_counter} unlinked parents...")

    # Close connections after second iteration is complete
    close_old_connections()


async def _verify_files_async():
    """Async implementation of verify_files."""
    print("Checking for invalid files in Database")
    start_count = await sync_to_async(IndexData.objects.count, thread_sensitive=True)()
    print("\tStarting File Count: ", start_count)

    # Process directories in batches with connection cleanup
    batch_counter = 0
    cleanup_interval = 25  # Close connections every 25 directories

    # Fetch all directories first
    directories = await sync_to_async(list, thread_sensitive=True)(IndexDirs.objects.all())

    for directory in directories:
        await sync_to_async(Cache_Storage.remove_from_cache_sha, thread_sensitive=True)(sha256=directory.dir_fqpn_sha256)
        await sync_database_disk(directory.fqpndirectory)

        # Periodic connection cleanup to prevent exhaustion
        batch_counter += 1
        if batch_counter % cleanup_interval == 0:
            # Close connections in async context
            await sync_to_async(connections.close_all, thread_sensitive=True)()
            print(f"\tProcessed {batch_counter} directories...")

    # Final cleanup
    await sync_to_async(connections.close_all, thread_sensitive=True)()

    end_count = await sync_to_async(IndexData.objects.count, thread_sensitive=True)()
    print("\tStarting File Count: ", start_count)
    print("\tEnding Count: ", end_count)
    print("\tDifference : ", start_count - end_count)


def verify_files():
    """Synchronous wrapper for verify_files."""
    asyncio.run(_verify_files_async())


class Command(BaseCommand):
    help = "Perform a Directory Validation/Integrity Scan"

    def scan_directory(self, directory_paths=None):
        pass

    def scan_files(self, directory_paths=None):
        pass

    def add_arguments(self, parser):
        parser.add_argument(
            "--verify_directories",
            action="store_true",
            help="Trigger a Verification/Validation scan on the existing directories in the database",
        )
        parser.add_argument(
            "--verify_files",
            action="store_true",
            help="Trigger a Verification/Validation scan on the existing files in the database",
        )

        parser.add_argument(
            "--dir",
            action="store_true",
            help="Scan directories for importation",
        )
        # parser.add_argument(
        #     "--files",
        #     action="store_true",
        #     help="Scan Files for importation",
        # )

    def handle(self, *args, **options):
        # print(args)
        # print(options)

        if options["verify_directories"]:
            verify_directories()
        if options["verify_files"]:
            verify_files()

        # if options["dir"]:
        #     self.scan_directory(directories_to_scan)
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
