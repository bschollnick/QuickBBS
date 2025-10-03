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
            # Add any startup logic here (e.g., starting cache_watcher)
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
