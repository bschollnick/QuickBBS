"""
WSGI config for quickbbs project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.9/howto/deployment/wsgi/
"""

import os
import sys

quickbbs_path = r"/Volumes/4TB_Drive/gallery/quickbbs"
sys.path.append(quickbbs_path)
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

application = get_wsgi_application()

# gunicorn -b 0.0.0.0:8888 --reload --pythonpath /Volumes/4TB_Drive/gallery/quickbbs,. quickbbs.wsgi
# gunicorn --worker-class eventlet -b 0.0.0.0:8888 --workers 5 --threads 5 --graceful-timeout 45 --reload --pythonpath /Volumes/4TB_Drive/gallery/quickbbs,. quickbbs.wsgi
# uwsgi --chdir=/Volumes/C-8TB/Gallery/quickbbs/quickbbs --module=quickbbs.wsgi --env DJANGO_SETTINGS_MODULE=quickbbs.settings --master --pidfile=./uswgi.pid --socket=0.0.0.0:8888 --protocol=http -b 65535 --processes=5
