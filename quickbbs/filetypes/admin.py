from django.contrib import admin

# Register your models here.
from filetypes.models import *


@admin.register(filetypes)
class AdminFiletypes(admin.ModelAdmin):
    fields = (
        "fileext",
        "icon_filename",
        "color",
        "generic",
        "filetype",
        "mimetype",
        "is_image",
        "is_archive",
        "is_pdf",
        "is_movie",
        "is_audio",
        "is_dir",
        "is_text",
        "is_html",
        "is_markdown",
        "is_link",
    )

    list_display = (
        "fileext",
        "icon_filename",
        "color",
        "generic",
        "filetype",
        "mimetype",
        "is_image",
        "is_archive",
        "is_pdf",
        "is_movie",
        "is_audio",
        "is_dir",
        "is_text",
        "is_html",
        "is_markdown",
        "is_link",
    )

    list_filter = [
        "fileext",
        "generic",
        "is_image",
        "is_archive",
        "is_pdf",
        "is_movie",
        "is_audio",
        "is_dir",
        "is_text",
        "is_html",
        "is_markdown",
        "is_link",
    ]
