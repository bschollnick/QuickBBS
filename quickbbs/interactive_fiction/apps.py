"""App configuration for interactive_fiction."""

from __future__ import annotations

from django.apps import AppConfig


class InteractiveFictionConfig(AppConfig):
    """Configuration for interactive_fiction app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "interactive_fiction"
