"""App configuration for user_preferences."""

from __future__ import annotations

from django.apps import AppConfig


class UserPreferencesConfig(AppConfig):
    """Configuration for user_preferences app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "user_preferences"

    def ready(self) -> None:
        """
        Import signals when app is ready.

        Returns:
            None
        """
        # Imported only to register the post_save receivers; importing at module
        # level would load models before the app registry is ready.
        import user_preferences.signals  # noqa: F401  # pylint: disable=import-outside-toplevel,unused-import
