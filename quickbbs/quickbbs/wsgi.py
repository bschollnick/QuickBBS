"""
WSGI config for quickbbs project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.9/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")
application = get_wsgi_application()

# gunicorn -b 0.0.0.0:8888 --reload --pythonpath /Volumes/4TB_Drive/gallery/quickbbs,. quickbbs.wsgi
# gunicorn --worker-class eventlet -b 0.0.0.0:8888 --workers 5 --threads 5 --graceful-timeout 45 --reload --pythonpath /Volumes/4TB_Drive/gallery/quickbbs,. quickbbs.wsgi
