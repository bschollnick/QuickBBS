"""
WSGI config for quickbbs project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.9/howto/deployment/wsgi/
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

from django.core.wsgi import (  # pylint: disable=wrong-import-position
    get_wsgi_application,
)

application = get_wsgi_application()
