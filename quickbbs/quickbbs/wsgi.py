"""
WSGI config for quickbbs project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.9/howto/deployment/wsgi/
"""

import os
import sys
quickbbs_path = r'/Volumes/4TB_Drive/gallery/quickbbs'
sys.path.append(quickbbs_path)
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

#os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

application = get_wsgi_application()
