# Register your models here.
from cache_watcher.models import CacheStatisticsTracking, fs_Cache_Tracking
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


@admin.register(CacheStatisticsTracking)
class CacheStatisticsTrackingAdmin(admin.ModelAdmin):
    """Admin view for MonitoredLRUCache hit/miss statistics snapshots."""

    list_display = ("cache_name", "hits", "misses", "get_hit_rate", "current_size", "max_size", "last_snapshot_at", "last_reset_at")
    readonly_fields = ("cache_name", "hits", "misses", "get_hit_rate", "current_size", "max_size", "last_snapshot_at", "last_reset_at")
    ordering = ("cache_name",)

    def has_add_permission(self, request) -> bool:
        """Disallow manual creation — rows are managed by the snapshot task."""
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        """Disallow deletion — rows are managed by the snapshot task."""
        return False

    @admin.display(description="Hit Rate")
    def get_hit_rate(self, obj: CacheStatisticsTracking) -> str:
        """Return formatted hit rate percentage for display."""
        return f"{obj.hit_rate:.1f}%"
