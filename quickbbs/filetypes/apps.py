"""Django AppConfig for filetypes application."""

import asyncio
import logging

from asgiref.sync import async_to_sync
from django.apps import AppConfig
from django.db import connection
from django.db.models.signals import post_delete, post_save
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)


class FiletypesConfig(AppConfig):
    """
    Django AppConfig for filetypes application.

    Loads filetypes at startup and sets up signals to auto-reload when filetypes change.
    ASGI compatible - defers loading if in async context.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "filetypes"
    label = "filetypes"

    def ready(self) -> None:
        """
        Initialize filetypes when Django app is ready.

        Loads filetype data from database and sets up signals to automatically
        reload when filetypes are modified in the admin interface.

        ASGI: Skips loading in async context - middleware will load on first request.
        """
        from filetypes.models import filetypes, load_filetypes

        # ASGI: Check if we're in an async context BEFORE any DB operations
        try:
            asyncio.get_running_loop()
            # We're in async context - skip loading, middleware will handle it
            logger.info("⏭ ASGI mode detected - deferring filetypes loading to middleware")
        except RuntimeError:
            # No event loop running - safe to load synchronously (WSGI mode)
            # load_filetypes() has its own error handling for DB issues
            load_filetypes()
            logger.info("✓ Filetypes loaded successfully (WSGI mode)")

        # Set up auto-reload signals when filetypes change (both WSGI and ASGI)
        def reload_filetypes(sender, **kwargs):
            logger.info("Filetypes changed - reloading...")
            load_filetypes(force=True)

        post_save.connect(reload_filetypes, sender=filetypes)
        post_delete.connect(reload_filetypes, sender=filetypes)
