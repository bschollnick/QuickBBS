from django.contrib import admin

from quickbbs.models import Favorites, IndexData, IndexDirs, Owners


@admin.register(IndexData)
class AdminMaster_Index(admin.ModelAdmin):
    search_fields = ["name", "file_sha256", "id"]
    list_filter = ["filetype"]
    readonly_fields = (
        "id",
        "file_sha256",
        "unique_sha256",
        "name_sort",
        "display_fqpndirectory",
        "display_parent_directory",
        "has_thumbs",
        "small_thumb",
    )

    list_display = (
        "id",
        "file_sha256",
        "unique_sha256",
        "name",
        "has_thumbs",
        "lastscan",
        "lastmod",
        "size",
        "display_fqpndirectory",
        "delete_pending",
        "ownership",
        "filetype",
    )
    fields = (
        "id",
        "file_sha256",
        "unique_sha256",
        "virtual_directory",
        "has_thumbs",
        "name",
        "lastscan",
        "lastmod",
        "size",
        "display_fqpndirectory",
        "display_parent_directory",
        "delete_pending",
        "ownership",
        "filetype",
        "small_thumb",
    )

    def has_thumbs(self, obj):
        if obj.new_ftnail is None:
            return False
        if any(
            [
                obj.new_ftnail.small_thumb,
                obj.new_ftnail.medium_thumb,
                obj.new_ftnail.large_thumb,
            ]
        ):
            return True
        return False

    def display_fqpndirectory(self, obj):
        if obj.fqpndirectory:
            return obj.fqpndirectory
        return "No directory"

    def display_parent_directory(self, obj):
        if obj.home_directory:
            return obj.home_directory.fqpndirectory
        return "No home directory"

    def small_thumb(self, obj):  # pragma: no cover
        if obj.new_ftnail is None:
            return None
        if obj.new_ftnail.small_thumb:
            return obj.new_ftnail.small_thumb[0:20]
        return None


@admin.register(IndexDirs)
class AdminMaster_Dirs(admin.ModelAdmin):
    search_fields = [
        "fqpndirectory",
        "dir_fqpn_sha256",
        # "dirname_sha256",
    ]
    readonly_fields = (
        "id",
        "dir_fqpn_sha256",
        "file_links",
        "display_file_links",
    )
    list_display = (
        "id",
        "dir_fqpn_sha256",
        # "dirname_sha256",
        "fqpndirectory",
        "is_generic_icon",
        "filetype",
        "delete_pending",
    )
    list_filter = ["filetype"]

    fields = (
        "id",
        "dir_fqpn_sha256",
        # "dirname_sha256",
        "fqpndirectory",
        "is_generic_icon",
        "delete_pending",
        "display_file_links",
    )

    def display_file_links(self, obj):
        links = obj.file_links.all()
        if len(links) > 25:
            links = links[:25]
            links.append("+ More files (Files truncated)...")
        return ", \n".join([f"{link.fqpndirectory}{link.name}" for link in links]) if links else "No links"


admin.site.register(Owners)
admin.site.register(Favorites)
# admin.site.register(Cache_Tracking)
