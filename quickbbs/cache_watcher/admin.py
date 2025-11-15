# Register your models here.
from cache_watcher.models import fs_Cache_Tracking
from django.contrib import admin


@admin.register(fs_Cache_Tracking)
class Cache_dir_tracking_Index(admin.ModelAdmin):
    list_display = ("get_directory_path", "invalidated", "get_directory_sha", "lastscan")
    fields = ("directory", "invalidated", "lastscan", "get_directory_sha", "get_directory_path")
    search_fields = ["directory__fqpndirectory", "directory__dir_fqpn_sha256"]
    readonly_fields = (
        "get_directory_sha",
        "get_directory_path",
    )
    autocomplete_fields = ["directory"]  # Enable autocomplete for directory selection

    @admin.display(description="Directory Path")
    def get_directory_path(self, obj):
        """Display the fqpndirectory from the related DirectoryIndex."""
        if obj.directory:
            return obj.directory.fqpndirectory
        return None

    @admin.display(description="Directory SHA256")
    def get_directory_sha(self, obj):
        """Display the dir_fqpn_sha256 from the related DirectoryIndex."""
        if obj.directory:
            return obj.directory.dir_fqpn_sha256
        return None
