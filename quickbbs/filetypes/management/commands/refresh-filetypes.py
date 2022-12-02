from django.core.management.base import BaseCommand, CommandError

from filetypes.models import *
from filetypes.constants import ftypes
import filetypes.constants as constants

class Command(BaseCommand):
    def refresh_filetypes(self):
        for ext in constants._movie:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                                         "icon_filename":"MovieIcon100.jpg",
                                                         "color":"CCCCCC",
                                                         "filetype":ftypes['movie'],
                                                         "is_movie":True}
                                                         )
        for ext in constants._audio:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                                         "icon_filename":"MovieIcon100.jpg",
                                                         "color":"CCCCCC",
                                                         "filetype":ftypes['audio'],
                                                         "is_audio":True}
                                                         )

        for ext in constants._archives:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                                         "icon_filename":"1431973824_compressed.png",
                                                         "color":"b2dece",
                                                         "filetype":ftypes['archive'],
                                                         "is_archive":True})

        for ext in constants._html:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                               "icon_filename":"1431973779_html.png",
                                               "color":"fef7df",
                                               "filetype":ftypes['html'],
                                               "is_text":True})

        for ext in constants._graphics:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":False,
                                               "color":"FAEBF4", "filetype":ftypes['image'],
                                               "is_image":True})

        for ext in constants._text:
            filetypes.objects.update_or_create(fileext=ext,
                                               defaults={"generic":True,
                                               "icon_filename":"1431973815_text.PNG",
                                               "color":"FAEBF4",
                                               "filetype":ftypes['image'],
                                               "is_text": True})

        filetypes.objects.update_or_create(fileext=".pdf",
                                           defaults={"generic":False,
                                           "color":"FDEDB1", "filetype":ftypes['image'],
                                           "is_pdf":True})

        filetypes.objects.update_or_create(fileext=".epub",
                                           defaults={"generic":True,
                                           "icon_filename":"epub-logo.gif",
                                           "color":"FDEDB1", "filetype":ftypes['epub']})

        filetypes.objects.update_or_create(fileext=".dir",
                                            defaults={"generic":False,
                                           "color":"DAEFF5", "filetype":ftypes['dir'],
                                           "is_dir":True})

        filetypes.objects.update_or_create(fileext=".none", defaults={"generic":True,
                                           "icon_filename":"1431973807_fileicon_bg.png",
                                           "color":"FFFFFF", "filetype":ftypes['unknown']})


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
        #     pass

