"""Django admin registrations for the cache_watcher app."""

from django.contrib import admin

from cache_watcher.models import CacheStatisticsTracking

# Thresholds for the sizing-advice column. These are deliberately conservative —
# the advice is only ever "consider" language, never a command, because hit rate
# alone can't distinguish eviction pressure from an inherently one-shot workload
# (see the docstring on CacheStatisticsTrackingAdmin.get_sizing_advice).
_LOW_HIT_RATE_PCT = 60.0
_FULL_THRESHOLD_PCT = 90.0  # current_size / max_size at or above this counts as "full"
_UNDERUSED_THRESHOLD_PCT = 50.0  # current_size / max_size at or below this counts as "underused"
_MIN_SAMPLE_SIZE = 50  # hits + misses below this is too little traffic to read the rate at all


@admin.register(CacheStatisticsTracking)
class CacheStatisticsTrackingAdmin(admin.ModelAdmin):
    """Admin view for MonitoredLRUCache hit/miss statistics snapshots."""

    list_display = (
        "cache_name",
        "hits",
        "misses",
        "get_hit_rate",
        "current_size",
        "max_size",
        "get_sizing_advice",
        "last_snapshot_at",
        "last_reset_at",
    )
    readonly_fields = ("cache_name", "hits", "misses", "get_hit_rate", "current_size", "max_size", "last_snapshot_at", "last_reset_at")
    ordering = ("cache_name",)
    change_list_template = "admin/cache_watcher/cachestatisticstracking/change_list.html"

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

    @admin.display(description="Sizing Advice")
    def get_sizing_advice(self, obj: CacheStatisticsTracking) -> str:
        """
        Suggest whether this cache's maxsize looks too small, too large, or fine.

        A low hit rate has two unrelated causes (see MonitoredCache.py's module
        docstring and quickbbs_app_design.md §4.5): eviction pressure, where a key
        really is being reused but doesn't survive long enough to be there for the
        second lookup, and cold-key traffic, where most keys are inherently one-shot
        and no maxsize would ever produce a hit. Hit rate alone can't tell those
        apart — but current_size relative to max_size can: a cache running full
        with a low hit rate is under eviction pressure; a cache running well below
        its max_size with a low hit rate is serving one-shot traffic that a bigger
        maxsize would not fix, so hint at shrinking it instead (recovering unused
        memory) rather than growing it.

        Returns:
            A short, non-imperative verdict string. Always "consider" language,
            never a command — this is a hint, not an automated decision, and the
            two-cause ambiguity means it can be wrong for a workload this simple
            heuristic doesn't fit.
        """
        total = obj.hits + obj.misses
        if total < _MIN_SAMPLE_SIZE:
            return "Not enough traffic yet"
        if obj.max_size <= 0:
            return "—"
        return self._sizing_verdict(obj)

    @staticmethod
    def _sizing_verdict(obj: CacheStatisticsTracking) -> str:
        """Return the sizing verdict for a cache with enough traffic to read."""
        hit_rate = obj.hit_rate
        fullness_pct = (obj.current_size / obj.max_size) * 100
        setting_hint = f"{obj.cache_name.upper()}_CACHE_SIZE"

        if hit_rate >= _LOW_HIT_RATE_PCT:
            if fullness_pct <= _UNDERUSED_THRESHOLD_PCT:
                return f"Healthy, oversized — could shrink {setting_hint}"
            return "Healthy"

        # hit_rate < _LOW_HIT_RATE_PCT from here on
        if fullness_pct >= _FULL_THRESHOLD_PCT:
            return f"Full + low hit rate — consider raising {setting_hint}"
        if fullness_pct <= _UNDERUSED_THRESHOLD_PCT:
            return "Low hit rate but cache isn't full — likely one-shot traffic, raising maxsize probably won't help"
        return "Low hit rate — inconclusive, watch over more traffic"
