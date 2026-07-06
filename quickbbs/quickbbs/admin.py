"""Django admin registrations for the QuickBBS core models."""

import time

from django.contrib import admin
from django.db import transaction
from django.db.models.query import QuerySet
from django.http import HttpRequest

from cache_watcher.models import fs_Cache_Tracking
from quickbbs.models import DirectoryIndex, Favorites, FileIndex, Owners


@admin.register(FileIndex)
class AdminMasterIndex(admin.ModelAdmin):
    """Admin configuration for FileIndex (the master file index)."""

    search_fields = [
        "name",
        "file_sha256",
        "unique_sha256",
        "id",
    ]
    list_filter = ["filetype"]
    readonly_fields = (
        "id",
        "file_sha256",
        "unique_sha256",
        "name_sort",
        "display_fqpndirectory",
        "display_parent_directory",
        "has_thumbs",
        "small_thumb",
    )

    list_display = (
        "id",
        "file_sha256",
        "unique_sha256",
        "name",
        "has_thumbs",
        "lastscan",
        "lastmod",
        "size",
        "display_fqpndirectory",
        "delete_pending",
        "ownership",
        "filetype",
    )
    fields = (
        "id",
        "file_sha256",
        "unique_sha256",
        "virtual_directory",
        "has_thumbs",
        "name",
        "lastscan",
        "lastmod",
        "size",
        "display_fqpndirectory",
        "display_parent_directory",
        "delete_pending",
        "ownership",
        "filetype",
        "small_thumb",
    )

    def has_thumbs(self, obj: FileIndex) -> bool:
        """
        Return whether the file has any thumbnail data.

        Args:
            obj: FileIndex record being displayed

        Returns:
            True if the linked ThumbnailFiles record holds a small, medium,
            or large thumbnail; False if unlinked or all sizes are empty
        """
        if obj.new_ftnail is None:
            return False
        if any(
            [
                obj.new_ftnail.small_thumb,
                obj.new_ftnail.medium_thumb,
                obj.new_ftnail.large_thumb,
            ]
        ):
            return True
        return False

    def display_fqpndirectory(self, obj: FileIndex) -> str:
        """
        Return the file's directory path for display.

        Args:
            obj: FileIndex record being displayed

        Returns:
            The fully qualified directory path, or "No directory" when unset
        """
        if obj.fqpndirectory:
            return obj.fqpndirectory
        return "No directory"

    def display_parent_directory(self, obj: FileIndex) -> str:
        """
        Return the home directory path for display.

        Args:
            obj: FileIndex record being displayed

        Returns:
            The home directory's fully qualified path, or "No home directory"
            when the record is orphaned
        """
        if obj.home_directory:
            return obj.home_directory.fqpndirectory
        return "No home directory"

    def small_thumb(self, obj: FileIndex) -> bytes | memoryview | None:  # pragma: no cover
        """
        Return a short preview of the small thumbnail's raw bytes.

        Args:
            obj: FileIndex record being displayed

        Returns:
            The first 20 bytes of the small thumbnail (bytes or memoryview,
            depending on how the BinaryField was loaded), or None when no
            thumbnail is linked or the small size is empty
        """
        if obj.new_ftnail is None:
            return None
        if obj.new_ftnail.small_thumb:
            return obj.new_ftnail.small_thumb[0:20]
        return None


@admin.register(DirectoryIndex)
class AdminMasterDirs(admin.ModelAdmin):
    """Admin configuration for DirectoryIndex (the master directory index)."""

    search_fields = [
        "fqpndirectory",
        "dir_fqpn_sha256",
        # "dirname_sha256",
    ]
    readonly_fields = (
        "id",
        "dir_fqpn_sha256",
    )
    list_display = (
        "id",
        "dir_fqpn_sha256",
        # "dirname_sha256",
        "fqpndirectory",
        "is_generic_icon",
        "filetype",
        "delete_pending",
    )
    list_filter = ["filetype"]
    actions = ["force_rebuild_thumbnails"]

    fields = (
        "id",
        "dir_fqpn_sha256",
        # "dirname_sha256",
        "fqpndirectory",
        "is_generic_icon",
        "delete_pending",
    )

    @admin.action(description="Force rebuild thumbnails for selected directories")
    def force_rebuild_thumbnails(self, request: HttpRequest, queryset: "QuerySet[DirectoryIndex]") -> None:
        """
        Force rebuild thumbnails for all files in the selected directories.

        This action clears all thumbnail data (sets to b"") for files in the selected
        directories, forcing them to be regenerated on next access. Also marks the
        directories as invalidated in the cache system.

        Args:
            request: The HTTP request object
            queryset: QuerySet of selected DirectoryIndex objects

        Returns:
            None - displays success message to user
        """
        total_files = 0
        total_thumbnails_cleared = 0
        directories_invalidated = 0

        with transaction.atomic():
            for directory in queryset:
                # Get all files in this directory using the FileIndex_entries reverse relationship
                files = directory.FileIndex_entries.select_related("new_ftnail").filter(delete_pending=False)
                total_files += files.count()

                # Clear thumbnails for each file
                for file_obj in files:
                    if file_obj.new_ftnail:
                        # Clear the thumbnail data
                        file_obj.new_ftnail.invalidate_thumb()
                        file_obj.new_ftnail.save(update_fields=["small_thumb", "medium_thumb", "large_thumb"])
                        total_thumbnails_cleared += 1

                # Mark the directory as invalidated in the cache system
                # This ensures the directory will be rescanned and thumbnails regenerated
                fs_Cache_Tracking.objects.update_or_create(
                    directory=directory,
                    defaults={
                        "invalidated": True,
                        "lastscan": time.time(),
                    },
                )
                directories_invalidated += 1

                # Invalidate the directory's thumbnail as well
                directory.invalidate_thumb()

        self.message_user(
            request,
            f"Cleared thumbnails for {total_thumbnails_cleared} files across {queryset.count()} "
            f"director{'y' if queryset.count() == 1 else 'ies'} (total files: {total_files}). "
            f"Invalidated {directories_invalidated} director{'y' if directories_invalidated == 1 else 'ies'} in cache.",
        )


admin.site.register(Owners)
admin.site.register(Favorites)
# admin.site.register(Cache_Tracking)
