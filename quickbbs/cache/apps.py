import os
from django.apps import AppConfig
from django.conf import settings
class cache(AppConfig):
    name = 'cache'
    path = os.path.join(settings.BASE_DIR, 'cache')