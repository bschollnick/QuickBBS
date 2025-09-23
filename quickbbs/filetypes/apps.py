"""Django AppConfig for filetypes application."""

import logging

from django.apps import AppConfig
from django.db import connection
from django.db.models.signals import post_delete, post_save
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)


class FiletypesConfig(AppConfig):
    """
    Django AppConfig for filetypes application.

    Loads filetypes at startup and sets up signals to auto-reload when filetypes change.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "filetypes"
    label = "filetypes"

    def ready(self) -> None:
        """
        Initialize filetypes when Django app is ready.

        Loads filetype data from database and sets up signals to automatically
        reload when filetypes are modified in the admin interface.
        """
        # Only load if database is available (handles migrations)
        try:
            from filetypes.models import filetypes, load_filetypes

            # Check if table exists
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM filetypes_filetypes LIMIT 1")

            # Load filetypes at startup
            load_filetypes()
            logger.info("✓ Filetypes loaded successfully")

            # Auto-reload when filetypes change
            def reload_filetypes(sender, **kwargs):
                logger.info("Filetypes changed - reloading...")
                load_filetypes(force=True)

            post_save.connect(reload_filetypes, sender=filetypes)
            post_delete.connect(reload_filetypes, sender=filetypes)

        except OperationalError:
            logger.warning("⚠ Filetypes table not ready (probably running migrations)")
        except Exception as e:
            logger.error(f"⚠ Could not load filetypes: {e}")