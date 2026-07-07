"""Django AppConfig for filetypes application."""

import logging

from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save

logger = logging.getLogger(__name__)


class FiletypesConfig(AppConfig):
    """
    Django AppConfig for filetypes application.

    Sets up signals to auto-reload the in-memory filetypes cache when rows
    change. Loading itself is deferred — no database access happens here, to
    avoid Django's "accessing the database during app initialization" warning.
    FiletypeLoaderMiddleware loads the cache on the first request, and
    get_ftype_dict() self-loads on first use for non-request contexts
    (management commands, taskrunner).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "filetypes"
    label = "filetypes"

    def ready(self) -> None:
        """
        Wire up filetype cache auto-reload signals when Django app is ready.

        Deliberately performs no database queries — filetype data is loaded
        lazily by FiletypeLoaderMiddleware (first request) or get_ftype_dict()
        (first lookup in non-request contexts).
        """
        from filetypes.models import filetypes, load_filetypes

        def reload_filetypes(sender, **kwargs):
            """Reload the in-memory filetypes cache after a row is saved or deleted."""
            logger.info("Filetypes changed - reloading...")
            load_filetypes(force=True)

        post_save.connect(reload_filetypes, sender=filetypes)
        post_delete.connect(reload_filetypes, sender=filetypes)
