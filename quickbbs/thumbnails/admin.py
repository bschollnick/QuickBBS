from django.contrib import admin

# Register your models here.
from thumbnails.models import *


@admin.register(SmallThumb)
class AdminFiletypes(admin.ModelAdmin):
    readonly_fields = ("id", "uuid", "Thumbnail")
    fields = ("id", "uuid", "FileSize")
    list_display = ("id", "uuid", "FileSize")


@admin.register(MediumThumb)
class AdminFiletypes(admin.ModelAdmin):
    readonly_fields = ("id", "uuid", "Thumbnail")
    fields = ("id", "uuid", "FileSize")
    list_display = ("id", "uuid", "FileSize")


@admin.register(LargeThumb)
class AdminFiletypes(admin.ModelAdmin):
    readonly_fields = ("id", "uuid", "Thumbnail")
    fields = ("id", "uuid", "FileSize")
    list_display = ("id", "uuid", "FileSize")


@admin.register(Thumbnails_Dir)
class AdminThumbnail_Dirs(admin.ModelAdmin):
    readonly_fields = (
        "id",
        "uuid",
    )
    list_display = ("id", "uuid", "FileName", "FileSize", "is_default")
    fields = ("id", "uuid", "FileName", "FileSize", "is_default")


@admin.register(Thumbnails_Files)
class AdminThumbnail_Files(admin.ModelAdmin):
    readonly_fields = ("id", "uuid", "SmallThumb", "MediumThumb", "LargeThumb")
    list_display = (
        "id",
        "uuid",
        "FileName",
        "FileSize",
        "is_default",
        "SmallThumb",
        "MediumThumb",
        "LargeThumb",
    )
    fields = (
        "id",
        "FileName",
        "FileSize",
        "is_default",
        "uuid",
        "SmallThumb",
        "MediumThumb",
        "LargeThumb",
    )  # , 'is_pdf', 'is_image')


# admin.site.register(Cache_Tracking)
