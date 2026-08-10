"""Django app configuration for the thumbnails app."""

from __future__ import annotations

from django.apps import AppConfig
from django.conf import settings


class ThumbnailsConfig(AppConfig):
    """App config that hands QuickBBS settings to the framework-independent engine."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "thumbnails"

    def ready(self) -> None:
        """Push Django settings into the engine's configuration.

        The engine deliberately does not read Django settings itself, so the
        values it needs are set here, once, at startup.
        """
        from thumbnails.engine import config

        config.macintosh_optimizations = bool(getattr(settings, "MACINTOSH_OPTIMIZATIONS", False))
