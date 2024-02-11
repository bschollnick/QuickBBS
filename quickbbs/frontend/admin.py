from django.contrib import admin

from quickbbs.models import *

# @admin.register(filetypes)
# class AdminFiletypes(admin.ModelAdmin):
#     fields = ('fileext', 'icon_filename', 'color', 'generic', 'filetype')
#     list_display = ('fileext', 'icon_filename', 'color', 'generic', 'filetype')


@admin.register(Thumbnails_Files)
class AdminThumbnail_Files(admin.ModelAdmin):
    readonly_fields = (
        "id",
        "uuid",
    )
    list_display = ("id", "uuid", "FileName", "FilePath", "FileSize")
    fields = ("id", "uuid", "FileName", "FilePath", "FileSize")


@admin.register(Thumbnails_Archives)
class AdminThumbnail_Archives(admin.ModelAdmin):
    readonly_fields = (
        "id",
        "uuid",
    )
    list_display = ("zipfilepath", "FilePath", "FileName", "page", "FileSize")
    fields = ("uuid", "zipfilepath", "FilePath", "FileName", "page", "FileSize")


@admin.register(IndexData)
class AdminMaster_Index(admin.ModelAdmin):
    readonly_fields = ("id", "uuid", "name_sort")
    list_display = (
        "id",
        "uuid",
        "name",
        "lastscan",
        "lastmod",
        "size",
        "fqpndirectory",
        "ignore",
        "delete_pending",
        "file_tnail",
        #        "directory",
        "archives",
        "ownership",
        "filetype",
    )
    fields = (
        "id",
        "uuid",
        "name",
        "lastscan",
        "lastmod",
        "size",
        "fqpndirectory",
        "ignore",
        "delete_pending",
        "file_tnail",
        # "directory",
        "archives",
        "ownership",
        "filetype",
    )


# @admin.register(Cache_Tracking)
# class Cache_dir_tracking_Index(admin.ModelAdmin):
#     list_display = ('DirName', 'lastscan')
#     fields = ('DirName', 'lastscan')
# @admin.register(scan_lock)
# class AdminScan_Lock(admin.ModelAdmin):
#     list_display = ('fqpndirectory',)
#     fields = ('fqpndirectory',)

admin.site.register(Owners)
admin.site.register(Favorites)
# admin.site.register(Cache_Tracking)
