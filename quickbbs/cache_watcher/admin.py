# Register your models here.
from cache_watcher.models import fs_Cache_Tracking
from django.contrib import admin


@admin.register(fs_Cache_Tracking)
class Cache_dir_tracking_Index(admin.ModelAdmin):
    list_display = ("DirName", "invalidated", "directory_sha256", "get_directory_sha", "lastscan")
    fields = ("DirName", "invalidated", "directory_sha256", "get_directory_sha", "lastscan")
    search_fields = ["DirName", "directory_sha256"]
    readonly_fields = (
        "directory_sha256",
        "get_directory_sha",
    )

    @admin.display(description="Directory SHA (from 1-to-1)")
    def get_directory_sha(self, obj):
        """Display the dir_fqpn_sha256 from the related IndexDirs."""
        if obj.directory:
            return obj.directory.dir_fqpn_sha256
        return None
