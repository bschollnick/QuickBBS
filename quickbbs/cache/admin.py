from django.contrib import admin

# Register your models here.
from cache.models import *

@admin.register(fs_Cache_Tracking)
class Cache_dir_tracking_Index(admin.ModelAdmin):
    list_display = ('DirName', 'lastscan')
    fields = ('DirName', 'lastscan')

#admin.site.register(fs_Cache_Tracking)
