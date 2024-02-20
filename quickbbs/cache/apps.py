import os

from django.apps import AppConfig
from django.conf import settings
from django.db.utils import IntegrityError, OperationalError, ProgrammingError

# cold_start = False


# class cache(AppConfig):
#     name = "cache"
#     path = os.path.join(settings.BASE_DIR, "cache")
#     cold_start = False
#
#     def ready(self):
#         global cold_start
#         if self.cold_start:
#             return
#         from cache.models import Cache_Storage
#
#         try:
#             if not self.cold_start:
#                 print("Clearing all entries from Cache Tracking")
#                 # Cache_Storage.clear_all_records()
#                 self.cold_start = True
#                 cold_start = True
#         except ProgrammingError:
#             print("Unable to clear Cache Table")
#         except OperationalError:
#             print("Cache table doesn't exist")
