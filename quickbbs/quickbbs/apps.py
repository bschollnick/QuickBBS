"""Django AppConfig for the quickbbs application."""

from __future__ import annotations

import logging
import os
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class QuickbbsConfig(AppConfig):
    """AppConfig for the quickbbs application.

    Runs one-time startup checks (e.g. SSL certificate expiration) when the
    Django app is ready.
    """

    name = "quickbbs"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Run startup checks once per server process.

        Only runs for server commands (runserver/runserver_plus dev reloader
        child, or production ASGI/WSGI workers), not for management commands
        like migrate/shell/scan — mirrors the gating used in
        cache_watcher.apps.cache_startup.ready().

        Returns:
            None
        """
        is_manage_py = sys.argv[0].endswith("manage.py") and len(sys.argv) > 1
        is_dev_server_cmd = is_manage_py and sys.argv[1] in ("runserver", "runserver_plus")
        is_other_management_cmd = is_manage_py and not is_dev_server_cmd

        if is_other_management_cmd:
            return

        if is_dev_server_cmd:
            run_main = os.environ.get("WERKZEUG_RUN_MAIN") or os.environ.get("RUN_MAIN")
            if run_main != "true":
                return

        self._check_ssl_cert_expiry()

    @staticmethod
    def _check_ssl_cert_expiry() -> None:
        """Log SSL certificate expiration status at startup.

        Delegates to quickbbs.tasks.check_ssl_cert_expiry so the same logic
        backs both the startup check and the daily periodic task. Import is
        deferred to avoid triggering app-registry access before Django has
        finished loading all apps.
        """
        try:
            from quickbbs.tasks import (
                check_ssl_cert_expiry,  # pylint: disable=import-outside-toplevel
            )

            check_ssl_cert_expiry.func()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("SSL certificate startup check failed")
