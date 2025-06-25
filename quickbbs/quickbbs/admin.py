from django.contrib import admin

from quickbbs.models import IndexData, IndexDirs, Owners, Favorites


@admin.register(IndexData)
class AdminMaster_Index(admin.ModelAdmin):
    search_fields = ["name", "uuid", "file_sha256", "id"]
    list_filter = ["filetype"]
    readonly_fields = (
        "id",
        "uuid",
        "file_sha256",
        "unique_sha256",
        "name_sort",
        "display_fqpndirectory",
        "display_parent_directory",
    )
    list_display = (
        "id",
        "uuid",
        "file_sha256",
        "unique_sha256",
        "name",
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
        "uuid",
        "file_sha256",
        "unique_sha256",
        "name",
        "lastscan",
        "lastmod",
        "size",
        "display_fqpndirectory",
        "display_parent_directory",
        "delete_pending",
        "ownership",
        "filetype",
    )

    def display_fqpndirectory(self, obj):
        if obj.fqpndirectory:
            return obj.fqpndirectory
        return "No directory"

    def display_parent_directory(self, obj):
        if obj.home_directory:
            return obj.home_directory.fqpndirectory
        return "No home directory"


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
        # "dirname_sha256",
        "dir_parent_sha256",
        "uuid",
        "file_links",
        "display_file_links",
    )
    list_display = (
        "id",
        "dir_fqpn_sha256",
        # "dirname_sha256",
        "dir_parent_sha256",
        "fqpndirectory",
        "is_generic_icon",
        "filetype",
        "delete_pending",
        "uuid",
    )
    list_filter = ["filetype"]

    fields = (
        "id",
        "dir_fqpn_sha256",
        # "dirname_sha256",
        "dir_parent_sha256",
        "fqpndirectory",
        "is_generic_icon",
        "delete_pending",
        "uuid",
        "display_file_links",
    )

    def display_file_links(self, obj):
        links = obj.file_links.all()
        if len(links) > 25:
            links = links[:25]
            links.append("+ More files (Files truncated)...")
        return (
            ", \n".join([f"{link.fqpndirectory}{link.name}" for link in links])
            if links
            else "No links"
        )




admin.site.register(Owners)
admin.site.register(Favorites)
# admin.site.register(Cache_Tracking)
