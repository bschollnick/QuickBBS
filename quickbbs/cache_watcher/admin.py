"""Django admin registrations for the cache_watcher app."""

from django.contrib import admin

from cache_watcher.models import CacheStatisticsTracking


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
