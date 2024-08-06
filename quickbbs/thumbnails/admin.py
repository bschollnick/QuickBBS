from django.contrib import admin

# Register your models here.
from thumbnails.models import ThumbnailFiles


@admin.register(ThumbnailFiles)
class AdminThumbnail_Files(admin.ModelAdmin):
    readonly_fields = ("id", "sthumb", "mthumb", "lthumb")
    list_display = (
        "id",
        "fqpn_filename",
        "fqpn_hash",
        "sthumb",
        "mthumb",
        "lthumb",
    )
    fields = (
        "id",
        "fqpn_filename",
        "fqpn_hash",
        "sthumb",
        "mthumb",
        "lthumb",
    )  

    def sthumb(self, obj):
        return obj.small_thumb[0:25]

    def mthumb(self, obj):
        return obj.medium_thumb[0:25]

    def lthumb(self, obj):
        return obj.large_thumb[0:25]
