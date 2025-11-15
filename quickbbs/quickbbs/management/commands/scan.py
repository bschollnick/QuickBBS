"""
Django management command for file system integrity and maintenance.

Provides commands to verify and maintain the integrity of the QuickBBS gallery
database against the actual file system. Includes functionality for:
- Verifying directories and files exist and are valid
- Adding missing directories and files to the database
- Generating missing thumbnails
- Maintaining database consistency with the file system

Usage:
    python manage.py scan --verify_directories
    python manage.py scan --verify_files
    python manage.py scan --add_directories [--max_count N] [--start PATH]
    python manage.py scan --add_files [--max_count N] [--start PATH]
    python manage.py scan --add_thumbnails [--max_count N]
"""

import asyncio
import os

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, connections

from cache_watcher.models import Cache_Storage, fs_Cache_Tracking
from frontend.utilities import sync_database_disk
from quickbbs.common import normalize_fqpn
from quickbbs.management.commands.add_directories import add_directories
from quickbbs.management.commands.add_files import add_files
from quickbbs.management.commands.add_thumbnails import add_thumbnails
from quickbbs.management.commands.management_helper import (
    invalidate_empty_directories,
    invalidate_directories_with_null_sha256,
    invalidate_directories_with_null_virtual_directory,
)
from quickbbs.models import IndexData, DirectoryIndex


def verify_directories(start_path: str | None = None):
    """
    Verify directories in the database against the filesystem.

    Args:
        start_path: Starting directory path to verify from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    print("Checking for invalid directories in Database (eg. Deleted, Moved, etc).")
    start_count = DirectoryIndex.objects.count()
    print("Starting Directory Count: ", start_count)
    albums_root = os.path.join(settings.ALBUMS_PATH, "albums") + os.sep

    # Invalidate directories with link files missing virtual_directory
    print("-" * 30)
    print("Invalidating directories with NULL virtual_directory link files...")
    invalidate_directories_with_null_virtual_directory(start_path=start_path, verbose=True)
    print("-" * 30)

    # Invalidate empty directories before verification begins
    print("-" * 30)
    print("Invalidating empty directories (before verification)...")
    invalidate_empty_directories(start_path=start_path, verbose=True)
    print("-" * 30)

    # Filter directories to only those under start_path if specified
    if start_path:
        normalized_start = normalize_fqpn(start_path)
        print(f"Filtering directories under: {normalized_start}")
        directories_to_scan = (
            DirectoryIndex.objects.select_related("Cache_Watcher")
            .filter(fqpndirectory__startswith=normalized_start)
            .order_by("fqpndirectory")
            .iterator(chunk_size=1000)
        )
    else:
        print("Gathering Directories")
        # Prefetch Cache_Watcher relationship to avoid N+1 queries
        directories_to_scan = DirectoryIndex.objects.select_related("Cache_Watcher").order_by("fqpndirectory").all().iterator(chunk_size=1000)

    print("Starting Scan")

    # Process directories WITHOUT closing connections during iteration
    # Server-side cursors don't survive close_old_connections()
    batch_counter = 0
    cache_instance = fs_Cache_Tracking()

    for directory in directories_to_scan:
        if not os.path.exists(directory.fqpndirectory):
            print(f"Directory: {directory.fqpndirectory} does not exist")
            DirectoryIndex.delete_directory_record(directory)
        else:
            # Check if directory exists in fs_Cache_Tracking using 1-to-1 relationship
            if not hasattr(directory, "Cache_Watcher"):
                cache_instance.add_from_indexdirs(directory)
                print(f"Added directory to fs_Cache_Tracking: {directory.fqpndirectory}")

        batch_counter += 1
        if batch_counter % 1000 == 0:
            print(f"Processed {batch_counter} directories...")

    # Only close connections AFTER iteration is complete
    close_old_connections()

    end_count = DirectoryIndex.objects.count()
    print("Ending Count: ", end_count)
    print("Difference : ", start_count - end_count)
    print("-" * 30)
    print("Checking for unlinked parents")
    unlinked_parents = DirectoryIndex.objects.filter(parent_directory__isnull=True).exclude(fqpndirectory=albums_root)
    # exclude the albums_root, since that is suppose to have no parent.  You can't tranverse below the albums_root
    print(f"Found {unlinked_parents.count()} directories with no parents")

    # CRITICAL: Order by fqpndirectory to process parent directories before children
    # Shallower paths (fewer separators) naturally sort before deeper paths
    batch_counter = 0
    for directory in unlinked_parents.order_by("fqpndirectory").iterator(chunk_size=1000):
        print(f"Fixing Parent directory for {directory.fqpndirectory}")
        DirectoryIndex.add_directory(directory.fqpndirectory)

        batch_counter += 1
        if batch_counter % 1000 == 0:
            print(f"Processed {batch_counter} unlinked parents...")

    # Close connections after second iteration is complete
    close_old_connections()

    # Invalidate empty directories after all verification operations
    print("-" * 30)
    print("Invalidating empty directories (after verification)...")
    invalidate_empty_directories(start_path=start_path, verbose=True)
    print("-" * 30)


async def _verify_files_async(start_path: str | None = None):
    """
    Async implementation of verify_files.

    Args:
        start_path: Starting directory path to verify from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    # Invalidate directories containing files with NULL SHA256
    await sync_to_async(invalidate_directories_with_null_sha256, thread_sensitive=True)(start_path=start_path)

    # Invalidate directories with link files missing virtual_directory
    await sync_to_async(invalidate_directories_with_null_virtual_directory, thread_sensitive=True)(start_path=start_path)

    print("Checking for invalid files in Database")
    start_count = await sync_to_async(IndexData.objects.count, thread_sensitive=True)()
    print("\tStarting File Count: ", start_count)

    # Process directories in batches with connection cleanup
    batch_counter = 0
    cleanup_interval = 25  # Close connections every 25 directories

    # Fetch all directories first with Cache_Watcher prefetched
    # This prevents sync DB queries when accessing is_cached property
    # Filter directories to only those under start_path if specified
    if start_path:
        normalized_start = normalize_fqpn(start_path)
        print(f"\tFiltering directories under: {normalized_start}")
        directories = await sync_to_async(list, thread_sensitive=True)(
            DirectoryIndex.objects.select_related("Cache_Watcher").filter(fqpndirectory__startswith=normalized_start).order_by("fqpndirectory").all()
        )
    else:
        directories = await sync_to_async(list, thread_sensitive=True)(
            DirectoryIndex.objects.select_related("Cache_Watcher").order_by("fqpndirectory").all()
        )

    for directory in directories:
        await sync_to_async(Cache_Storage.remove_from_cache_sha, thread_sensitive=True)(sha256=directory.dir_fqpn_sha256)
        await sync_database_disk(directory)

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


def verify_files(start_path: str | None = None):
    """
    Synchronous wrapper for verify_files.

    Args:
        start_path: Starting directory path to verify from (default: ALBUMS_PATH/albums)

    Returns:
        None
    """
    asyncio.run(_verify_files_async(start_path=start_path))


class Command(BaseCommand):
    """
    Django management command for file system integrity and maintenance.

    Provides various scanning and validation operations for the QuickBBS gallery
    database to ensure consistency with the file system.
    """

    help = "Perform a Directory Validation/Integrity Scan"

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
            "--add_directories",
            action="store_true",
            help="Walk albums directory and add any missing directories to DirectoryIndex and fs_Cache_Tracking",
        )
        parser.add_argument(
            "--add_files",
            action="store_true",
            help="Walk albums directory and add any missing files to IndexData",
        )
        parser.add_argument(
            "--add_thumbnails",
            action="store_true",
            help="Scan IndexData for files missing thumbnails and generate them (images, videos, PDFs)",
        )
        parser.add_argument(
            "--max_count",
            type=int,
            default=0,
            help="Maximum number of records to add (0 = unlimited). Used with --add_directories, --add_files, or --add_thumbnails",
        )
        parser.add_argument(
            "--start",
            type=str,
            default=None,
            help="Starting directory path to walk from (default: ALBUMS_PATH/albums). Used with --verify_directories, --verify_files, --add_directories, or --add_files",
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

        max_count = options.get("max_count", 0)
        start_path = options.get("start", None)

        # Validate start_path if provided
        if start_path:
            # Normalize the provided path
            normalized_start_path = normalize_fqpn(start_path)

            # Get the albums root directory
            albums_root = normalize_fqpn(os.path.join(settings.ALBUMS_PATH, "albums"))

            # Ensure the start_path is within the albums directory
            if not normalized_start_path.startswith(albums_root):
                raise CommandError(
                    f"Invalid --start path: '{start_path}'\n"
                    f"The path must be within the albums directory: '{albums_root}'\n"
                    f"Normalized path provided: '{normalized_start_path}'"
                )

            # Ensure the path exists
            if not os.path.exists(normalized_start_path):
                raise CommandError(f"Invalid --start path: '{start_path}'\n" f"The directory does not exist: '{normalized_start_path}'")

            # Ensure it's a directory
            if not os.path.isdir(normalized_start_path):
                raise CommandError(f"Invalid --start path: '{start_path}'\n" f"The path is not a directory: '{normalized_start_path}'")

        if options["verify_directories"]:
            verify_directories(start_path=start_path)
        if options["verify_files"]:
            verify_files(start_path=start_path)
        if options["add_directories"]:
            add_directories(max_count=max_count, start_path=start_path)
        if options["add_files"]:
            add_files(max_count=max_count, start_path=start_path)
        if options["add_thumbnails"]:
            add_thumbnails(max_count=max_count)


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
