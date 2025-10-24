"""Admin configuration for user preferences."""

from __future__ import annotations

from django.contrib import admin

from user_preferences.models import UserPreferences


@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    """Admin interface for UserPreferences model."""

    list_display = ("user", "show_duplicates")
    list_filter = ("show_duplicates",)
    search_fields = ("user__username", "user__email")
    readonly_fields = ("user",)

    def has_add_permission(self, request) -> bool:
        """
        Disable manual creation - preferences auto-created via signals.

        Args:
            request: The HTTP request

        Returns:
            False to disable add permission
        """
        return False
