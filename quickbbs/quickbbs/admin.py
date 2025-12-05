import time

from django.contrib import admin
from django.db import transaction

from cache_watcher.models import fs_Cache_Tracking
from quickbbs.models import DirectoryIndex, Favorites, FileIndex, Owners


@admin.register(FileIndex)
class AdminMaster_Index(admin.ModelAdmin):
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

    def has_thumbs(self, obj):
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

    def display_fqpndirectory(self, obj):
        if obj.fqpndirectory:
            return obj.fqpndirectory
        return "No directory"

    def display_parent_directory(self, obj):
        if obj.home_directory:
            return obj.home_directory.fqpndirectory
        return "No home directory"

    def small_thumb(self, obj):  # pragma: no cover
        if obj.new_ftnail is None:
            return None
        if obj.new_ftnail.small_thumb:
            return obj.new_ftnail.small_thumb[0:20]
        return None


@admin.register(DirectoryIndex)
class AdminMaster_Dirs(admin.ModelAdmin):
    search_fields = [
        "fqpndirectory",
        "dir_fqpn_sha256",
        # "dirname_sha256",
    ]
    readonly_fields = (
        "id",
        "dir_fqpn_sha256",
        "file_links",
        "display_file_links",
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
        "display_file_links",
    )

    def display_file_links(self, obj):
        links = obj.file_links.all()
        if len(links) > 25:
            links = links[:25]
            links.append("+ More files (Files truncated)...")
        return ", \n".join([f"{link.fqpndirectory}{link.name}" for link in links]) if links else "No links"

    @admin.action(description="Force rebuild thumbnails for selected directories")
    def force_rebuild_thumbnails(self, request, queryset):
        """
        Force rebuild thumbnails for all files in the selected directories.

        This action clears all thumbnail data (sets to b"") for files in the selected
        directories, forcing them to be regenerated on next access. Also marks the
        directories as invalidated in the cache system.

        :Args:
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
