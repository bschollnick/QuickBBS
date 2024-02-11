from django.contrib import admin

# Register your models here.
from thumbnails.models import *


# @admin.register(Thumbnail_Files)
# class AdminThumbnail_Files(admin.ModelAdmin):
#     # readonly_fields = ("id", "uuid", "smallthumb", "mediumthumb", "largethumb")
#     list_display = (
#         "id",
#         "uuid",
#         "filename",
#         "filesize",
#         "is_generic",
#         "smallthumb",
#         "mediumthumb",
#         "largethumb",
#     )
#     fields = (
#         "id",
#         "uuid",
#         "filename",
#         "filesize",
#         "is_generic",
#         "smallthumb",
#         "mediumthumb",
#         "largethumb",
#     )  # , 'is_pdf', 'is_image')


# admin.site.register(Cache_Tracking)
