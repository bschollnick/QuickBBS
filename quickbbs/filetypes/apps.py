import os

from django.apps import AppConfig

# from django.conf import settings
# from django.db.utils import IntegrityError, OperationalError, ProgrammingError

# cold_start = False


class filetype_setup(AppConfig):
    name = "filetypes"
    label = "filetypes"

    def ready(self):
        import filetypes.models

        print("!! Starting Filetypes")
        filetypes.models.FILETYPE_DATA = filetypes.models.load_filetypes()
        # cache_watcher.models.Cache_Storage = cache_watcher.models.fs_Cache_Tracking()
        print("Filetypes established")
