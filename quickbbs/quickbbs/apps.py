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
        self._register_scheduled_task_admin()
        self._connect_favorite_delete_logging()

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
        self._reconcile_cache_statistics()

    @staticmethod
    def _register_scheduled_task_admin() -> None:
        """Replace django-dbtasks' default ScheduledTask admin with ours.

        django.contrib.admin's autodiscovery imports quickbbs.admin before
        dbtasks.admin (INSTALLED_APPS order), so dbtasks.admin's own
        @admin.register(ScheduledTask) always overwrites ours if registered
        directly in quickbbs/admin.py. AppConfig.ready() runs after all
        admin.py autodiscovery has completed, so re-registering here
        deterministically wins regardless of app load order.
        """
        from dbtasks.models import (  # pylint: disable=import-outside-toplevel
            ScheduledTask,
        )
        from django.contrib import admin  # pylint: disable=import-outside-toplevel

        from quickbbs.admin import (  # pylint: disable=import-outside-toplevel
            ScheduledTaskAdmin,
        )

        if admin.site.is_registered(ScheduledTask):
            admin.site.unregister(ScheduledTask)
        admin.site.register(ScheduledTask, ScheduledTaskAdmin)

    @staticmethod
    def _connect_favorite_delete_logging() -> None:
        """Connect pre_delete diagnostic logging for Favorite and its cascade sources.

        Runs for every process (dev server, management commands, production
        workers) so a Favorite loss via any path — direct delete, admin
        action, or DB_CASCADE from a DirectoryIndex/FileIndex/user delete —
        leaves a trail in logs/quickbbs.log. See favorite_delete_logging.py.
        """
        from quickbbs.favorite_delete_logging import (  # pylint: disable=import-outside-toplevel
            connect,
        )

        connect()

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

    @classmethod
    def _reconcile_cache_statistics(cls) -> None:
        """Arrange for stale cache_statistics_tracking rows to be dropped once.

        Keeps the statistics table aligned with the live cache registry, so a
        renamed or removed cache does not leave a permanently stale row behind.

        The work is deferred to the first request rather than run inline:
        querying the database from AppConfig.ready() raises Django's
        "Accessing the database during app initialization is discouraged"
        RuntimeWarning, and would also fail on a not-yet-migrated database
        (the table comes from CacheWatcher migration 0011). request_started
        fires once the app registry is fully populated and the DB is in use.
        """
        from django.core.signals import (  # pylint: disable=import-outside-toplevel
            request_started,
        )

        request_started.connect(cls._run_cache_statistics_reconcile, dispatch_uid="quickbbs.reconcile_cache_statistics")

    @staticmethod
    def _run_cache_statistics_reconcile(sender, **kwargs) -> None:  # pylint: disable=unused-argument
        """Run the reconcile once, then disconnect from request_started.

        Args:
            sender: The handler class sending request_started (unused).
            **kwargs: Signal keyword arguments (unused).
        """
        from django.core.signals import (  # pylint: disable=import-outside-toplevel
            request_started,
        )

        request_started.disconnect(dispatch_uid="quickbbs.reconcile_cache_statistics")
        try:
            from quickbbs.tasks import (
                reconcile_cache_statistics_rows,  # pylint: disable=import-outside-toplevel
            )

            reconcile_cache_statistics_rows()
        except Exception:  # pylint: disable=broad-exception-caught
            # Housekeeping only — never let this break request handling.
            logger.exception("Cache statistics startup reconcile failed")
