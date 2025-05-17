from django.contrib import admin

from quickbbs.models import IndexData, IndexDirs, Owners, Favorites

@admin.register(IndexData)
class AdminMaster_Index(admin.ModelAdmin):
    search_fields = ["name", "fqpndirectory", "uuid", "file_sha256", "id"]
    list_filter = ["filetype"]
    readonly_fields = ("id", "uuid", "file_sha256", "unique_sha256", "name_sort")
    list_display = (
        "id",
        "uuid",
        "file_sha256",
        "unique_sha256",
        "name",
        "lastscan",
        "lastmod",
        "size",
        "fqpndirectory",
        #        "ignore",
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
        "fqpndirectory",
        #        "ignore",
        "delete_pending",
        "ownership",
        "filetype",
    )


@admin.register(IndexDirs)
class AdminMaster_Dirs(admin.ModelAdmin):
    search_fields = [
        "fqpndirectory",
        "dir_sha256",
    ]
    readonly_fields = (
        "id",
        "dir_sha256",
        "uuid",
        "sthumb",
    )
    list_display = (
        "id",
        "dir_sha256",
        "uuid",
        "fqpndirectory",
        "is_generic_icon",
        "sthumb",
        "delete_pending",
    )

    fields = (
        "id",
        "dir_sha256",
        "uuid",
        "fqpndirectory",
        "is_generic_icon",
        "sthumb",
        "delete_pending",
    )

    def sthumb(self, obj):
        if obj.small_thumb is not None:
            return obj.small_thumb[0:25]
        else:
            return "None"
        
admin.site.register(Owners)
admin.site.register(Favorites)
# admin.site.register(Cache_Tracking)
