"""
ASGI config for QuickBBS project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.1/howto/deployment/asgi/
"""

import logging
import os

from django.core.asgi import get_asgi_application

logger = logging.getLogger(__name__)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

# Get the Django ASGI application
django_application = get_asgi_application()

# Imported after get_asgi_application() so Django's app registry is populated
# before django.db.connections is touched. Necessarily separated from the
# django.core.asgi import above by that ordering constraint.
# pylint: disable-next=wrong-import-position,ungrouped-imports
from asgiref.sync import sync_to_async  # noqa: E402
from django.db import (  # noqa: E402  # pylint: disable=wrong-import-position,ungrouped-imports
    connections,
)
from django.db.utils import (  # noqa: E402  # pylint: disable=wrong-import-position,ungrouped-imports
    DatabaseError,
    OperationalError,
)


def _warm_pool() -> None:
    """
    Force the DB connection pool to open and establish a connection.

    Deliberately runs a trivial raw query rather than calling
    ensure_connection() directly: ensure_connection() triggers Django's
    lazy pg_version cached property, whose PostgreSQL-specific
    implementation opens a *nested* temporary_connection() / cursor() call
    — a second, distinct sync_to_async-style dispatch through
    django.utils.asyncio's @async_unsafe wrapper. That nested call can run
    on a different asgiref executor thread than the one that created the
    connection object, and Django's validate_thread_sharing() then raises
    DatabaseError because the connection is used from a thread other than
    the one that created it. Executing one plain query directly (no nested
    lazy-property access) establishes the pool connection without
    triggering that nested dispatch.
    """
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT 1")


async def lifespan_handler(scope, receive, send):
    """
    Handle ASGI lifespan events (startup/shutdown).

    Args:
        scope: ASGI scope dictionary
        receive: ASGI receive callable
        send: ASGI send callable
    """
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            logger.info("ASGI application starting up")
            # Pre-warm the DB connection pool during startup rather than
            # letting it lazily open on first use inside a
            # sync_to_async-dispatched executor thread. Opening it lazily
            # under hypercorn causes psycopg_pool's connection-establishment
            # to stall the first time it's triggered from a non-main thread
            # under hypercorn's asyncio loop — reproduced directly during
            # Phase 3 load-test investigation
            # (claude_docs/plans/async_simplification.md): every request
            # timed out at the pool's configured 15s timeout as soon as 2-3
            # concurrent requests arrived, and disappeared entirely once the
            # pool was warmed here instead.
            try:
                await sync_to_async(_warm_pool)()
                logger.info("Database connection pool pre-warmed")
            except (DatabaseError, OperationalError):
                logger.exception("Failed to pre-warm database connection pool")
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            logger.info("ASGI application shutting down")
            # Add any shutdown logic here (e.g., stopping cache_watcher)
            await send({"type": "lifespan.shutdown.complete"})
            return


async def application(scope, receive, send):
    """
    Main ASGI application with lifespan support.

    Args:
        scope: ASGI scope dictionary
        receive: ASGI receive callable
        send: ASGI send callable

    :Return:
        Response from Django application or lifespan handler
    """
    if scope["type"] == "lifespan":
        await lifespan_handler(scope, receive, send)
    else:
        await django_application(scope, receive, send)
