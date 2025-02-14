# Register your models here.
from cache_watcher.models import *
from django.contrib import admin


@admin.register(fs_Cache_Tracking)
class Cache_dir_tracking_Index(admin.ModelAdmin):
    list_display = ("DirName", "Dir_md5_hdigest", "lastscan")
    fields = ("DirName", "lastscan")
    search_fields = ["DirName", "Dir_md5_hdigest"]
    readonly_fields = ("Dir_md5_hdigest",)