from django.contrib import admin
from thumbnails.models import ThumbnailFiles


@admin.register(ThumbnailFiles)
class AdminThumbnail_Files(admin.ModelAdmin):
    readonly_fields = (
        "id",
        "sthumb",
        "mthumb",
        "lthumb",
        "sha256_hash",
    )

    search_fields = ["sha256_hash", "id"]

    list_display = (
        "id",
        "sha256_hash",
        "sthumb",
        "mthumb",
        "lthumb",
    )
    fields = (
        "id",
        "sha256_hash",
        "sthumb",
        "mthumb",
        "lthumb",
    )

    def sthumb(self, obj):
        if obj.small_thumb is not None:
            return obj.small_thumb[0:25]
        else:
            return "None"

    def mthumb(self, obj):
        if obj.medium_thumb is not None:
            return obj.medium_thumb[0:25]
        else:
            return "None"

    def lthumb(self, obj):
        if obj.large_thumb is not None:
            return obj.large_thumb[0:25]
        else:
            return "None"
