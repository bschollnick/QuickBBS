from django.core.management.base import BaseCommand, CommandError

from filetypes.models import *
# from filetypes.constants import ftypes
# import filetypes.settings as settings
from django.conf import settings

class Command(BaseCommand):
    def refresh_filetypes(self):
        for ext in settings.MOVIE_FILE_TYPES:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                                         "icon_filename":"MovieIcon100.jpg",
                                                         "color":"CCCCCC",
                                                         "filetype":settings.FTYPES['movie'],
                                                         "is_movie":True}
                                                         )
        for ext in settings.AUDIO_FILE_TYPES:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                                         "icon_filename":"MovieIcon100.jpg",
                                                         "color":"CCCCCC",
                                                         "filetype":settings.FTYPES['audio'],
                                                         "is_audio":True}
                                                         )

        for ext in settings.ARCHIVE_FILE_TYPES:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                                         "icon_filename":"1431973824_compressed.png",
                                                         "color":"b2dece",
                                                         "filetype":settings.FTYPES['archive'],
                                                         "is_archive":True})

        for ext in settings.HTML_FILE_TYPES:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                               "icon_filename":"1431973779_html.png",
                                               "color":"fef7df",
                                               "filetype":settings.FTYPES['html'],
                                               "is_text":True})

        for ext in settings.GRAPHIC_FILE_TYPES:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":False,
                                               "color":"FAEBF4", "filetype":settings.FTYPES['image'],
                                               "is_image":True})

        for ext in settings.TEXT_FILE_TYPES:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                               "icon_filename":"1431973815_text.PNG",
                                               "color":"FAEBF4",
                                               "filetype":settings.FTYPES['image'],
                                               "is_text": True})

        filetypes.objects.update_or_create(fileext=".pdf",
                                           defaults={"generic":False,
                                           "color":"FDEDB1", "filetype":settings.FTYPES['image'],
                                           "is_pdf":True})

        filetypes.objects.update_or_create(fileext=".epub",
                                           defaults={"generic":True,
                                           "icon_filename":"epub-logo.gif",
                                           "color":"FDEDB1", "filetype":settings.FTYPES['epub']})

        filetypes.objects.update_or_create(fileext=".dir",
                                            defaults={"generic":False,
                                           "color":"DAEFF5",
                                           "icon_filename":"1431973840_folder.png",
                                           "filetype":settings.FTYPES['dir'],
                                           "is_dir":True})

        filetypes.objects.update_or_create(fileext=".none", defaults={"generic":True,
                                           "icon_filename":"1431973807_fileicon_bg.png",
                                           "color":"FFFFFF", "filetype":settings.FTYPES['unknown']})


    def add_arguments(self, parser):
        # Positional arguments
#        parser.add_argument('poll_ids', nargs='+', type=int)

        # Named (optional) arguments
        parser.add_argument(
            '--refresh-filetypes',
            action='store_true',
            help='Add, Refresh and revise the FileType table',
        )

    def handle(self, *args, **options):
        # ...
        try:
             self.refresh_filetypes()
        except:
             print("Unable to validate or create FileType database table.")

