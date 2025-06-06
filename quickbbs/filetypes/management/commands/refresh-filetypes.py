from mimetypes import guess_type

from django.conf import settings
from django.core.management.base import BaseCommand
from filetypes.models import *


class Command(BaseCommand):
    def refresh_filetypes(self):
        for ext in settings.MOVIE_FILE_TYPES:
            mimetype = guess_type(f"test.{ext}")[0]
            if mimetype is None:
                mimetype = None
            filetypes.objects.update_or_create(
                fileext=ext,
                defaults={
                    "generic": True,
                    "icon_filename": "MovieIcon100.jpg",
                    "color": "CCCCCC",
                    "filetype": settings.FTYPES["movie"],
                    "is_movie": True,
                    "mimetype": mimetype,
                },
            )
        for ext in settings.AUDIO_FILE_TYPES:
            filetypes.objects.update_or_create(
                fileext=ext,
                defaults={
                    "generic": True,
                    "icon_filename": "MovieIcon100.jpg",
                    "color": "CCCCCC",
                    "filetype": settings.FTYPES["audio"],
                    "is_audio": True,
                    "mimetype": guess_type(f"test.{ext}")[0],
                },
            )

        for ext in settings.ARCHIVE_FILE_TYPES:
            filetypes.objects.update_or_create(
                fileext=ext,
                defaults={
                    "generic": True,
                    "icon_filename": "1431973824_compressed.png",
                    "color": "b2dece",
                    "filetype": settings.FTYPES["archive"],
                    "is_archive": True,
                    "mimetype": guess_type(f"test.{ext}")[0],
                },
            )

        for ext in settings.HTML_FILE_TYPES:
            filetypes.objects.update_or_create(
                fileext=ext,
                defaults={
                    "generic": True,
                    "icon_filename": "1431973779_html.png",
                    "color": "fef7df",
                    "filetype": settings.FTYPES["html"],
                    "is_html": True,
                    "is_text": False,
                    "mimetype": guess_type(f"test.{ext}")[0],
                },
            )

        for ext in settings.GRAPHIC_FILE_TYPES:
            filetypes.objects.update_or_create(
                fileext=ext,
                defaults={
                    "generic": False,
                    "color": "FAEBF4",
                    "filetype": settings.FTYPES["image"],
                    "is_image": True,
                    "mimetype": guess_type(f"test.{ext}")[0],
                },
            )

        for ext in settings.TEXT_FILE_TYPES:
            filetypes.objects.update_or_create(
                fileext=ext,
                defaults={
                    "generic": True,
                    "icon_filename": "1431973815_text.PNG",
                    "color": "FAEBF4",
                    "filetype": settings.FTYPES["image"],
                    "is_text": True,
                    "mimetype": guess_type(f"test.{ext}")[0],
                },
            )

        for ext in settings.MARKDOWN_FILE_TYPES:
            filetypes.objects.update_or_create(
                fileext=ext,
                defaults={
                    "generic": True,
                    "icon_filename": "1431973815_text.PNG",
                    "color": "FAEBF4",
                    "filetype": settings.FTYPES["image"],
                    "is_markdown": True,
                    "is_text": False,
                    "mimetype": guess_type(f"test.{ext}")[0],
                },
            )

        for ext in settings.LINK_FILE_TYPES:
            filetypes.objects.update_or_create(
                fileext=ext,
                defaults={
                    "generic": True,
                    "icon_filename": "redirecting-link.png",
                    "color": "FDEDB1",
                    "filetype": settings.FTYPES["link"],
                    "is_link": True,
                    "mimetype": guess_type(f"test.{ext}")[0],
                },
            )
        filetypes.objects.update_or_create(
            fileext=".link",
            defaults={
                "generic": True,
                "icon_filename": "redirecting-link.png",
                "color": "FDEDB1",
                "filetype": settings.FTYPES["link"],
                "is_link": True,
                "mimetype": guess_type("test.url")[0],
            },
        )

        filetypes.objects.update_or_create(
            fileext=".pdf",
            defaults={
                "generic": False,
                "color": "FDEDB1",
                "filetype": settings.FTYPES["image"],
                "is_pdf": True,
                "mimetype": guess_type("test.pdf")[0],
            },
        )

        filetypes.objects.update_or_create(
            fileext=".epub",
            defaults={
                "generic": True,
                "icon_filename": "epub-logo.gif",
                "color": "FDEDB1",
                "filetype": settings.FTYPES["epub"],
                "mimetype": guess_type("test.epub")[0],
            },
        )

        filetypes.objects.update_or_create(
            fileext=".dir",
            defaults={
                "generic": False,
                "color": "DAEFF5",
                "icon_filename": "1431973840_folder.png",
                "filetype": settings.FTYPES["dir"],
                "is_dir": True,
            },
        )

        filetypes.objects.update_or_create(
            fileext=".none",
            defaults={
                "generic": True,
                "icon_filename": "1431973807_fileicon_bg.png",
                "color": "FFFFFF",
                "filetype": settings.FTYPES["unknown"],
            },
        )

    def add_arguments(self, parser):
        # Positional arguments
        #        parser.add_argument('poll_ids', nargs='+', type=int)

        # Named (optional) arguments
        parser.add_argument(
            "--refresh-filetypes",
            action="store_true",
            help="Add, Refresh and revise the FileType table",
        )

    def handle(self, *args, **options):
        # ...
        #     try:
        print("Starting to refresh all filetypes")
        self.refresh_filetypes()
        print("filetypes have been refreshed.")

    #    except:
    #       print("Unable to validate or create FileType database table.")
