import io
import zipfile

from django.contrib import admin
from django.http import HttpResponse

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

    actions = ["download_thumbnails"]

    def download_thumbnails(self, request, queryset):
        """
        Admin action to download selected thumbnails as a ZIP file.

        Creates a ZIP file containing all thumbnail sizes (small, medium, large)
        for the selected ThumbnailFiles records. Files are named using the format:
        <sha256_hash>_<size>.jpg

        :Args:
            request: Django HttpRequest object
            queryset: QuerySet of selected ThumbnailFiles records

        :Returns:
            HttpResponse with ZIP file attachment
        """
        # Create in-memory ZIP file
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for thumb in queryset:
                sha = thumb.sha256_hash

                # Add small thumbnail if exists
                if thumb.small_thumb:
                    filename = f"{sha}_small.jpg"
                    zip_file.writestr(filename, thumb.small_thumb)

                # Add medium thumbnail if exists
                if thumb.medium_thumb:
                    filename = f"{sha}_medium.jpg"
                    zip_file.writestr(filename, thumb.medium_thumb)

                # Add large thumbnail if exists
                if thumb.large_thumb:
                    filename = f"{sha}_large.jpg"
                    zip_file.writestr(filename, thumb.large_thumb)

        # Prepare HTTP response
        zip_buffer.seek(0)
        response = HttpResponse(zip_buffer.read(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="thumbnails.zip"'

        # Add success message
        count = queryset.count()
        self.message_user(request, f"Downloaded thumbnails for {count} record(s).")

        return response

    download_thumbnails.short_description = "Download selected thumbnails as ZIP"

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
