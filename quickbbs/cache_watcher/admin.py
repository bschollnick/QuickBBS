# Register your models here.
from cache_watcher.models import *
from django.contrib import admin


@admin.register(fs_Cache_Tracking)
class Cache_dir_tracking_Index(admin.ModelAdmin):
    list_display = ("DirName", "directory_sha256", "lastscan")
    fields = ("DirName", "directory_sha256", "lastscan")
    search_fields = ["DirName", "directory_sha256"]
    readonly_fields = (
        "directory_sha256",
        "directory_sha256",
    )
