from django.contrib import admin

# Register your models here.
from quickbbs.models import *

@admin.register(filetypes)
class AdminFiletypes(admin.ModelAdmin):
    fields = ('fileext', 'icon_filename', 'color', 'generic', 'filetype')
    list_display = ('fileext', 'icon_filename', 'color', 'generic', 'filetype')

@admin.register(Thumbnails_Dirs)
class AdminThumbnail_Dirs(admin.ModelAdmin):
    list_display = ('FilePath', 'DirName', 'FileSize')
    fields = ('uuid', 'FilePath', 'DirName', 'FileSize')

@admin.register(Thumbnails_Files)
class AdminThumbnail_Files(admin.ModelAdmin):
    list_display = ('FileName', 'FilePath', 'FileSize')#g, 'is_pdf', 'is_image')
    fields = ('uuid', 'FileName', 'FilePath', 'FileSize')#, 'is_pdf', 'is_image')

@admin.register(Thumbnails_Archives)
class AdminThumbnail_Archives(admin.ModelAdmin):
    list_display = ('zipfilepath', 'FilePath', 'FileName', 'page', 'FileSize')
    fields = ('uuid', 'zipfilepath', 'FilePath', 'FileName', 'page', 'FileSize')

@admin.register(index_data)
class AdminMaster_Index(admin.ModelAdmin):
    list_display = ('name', 'lastscan', 'lastmod', 'size', 'fqpndirectory', 'ignore', 'delete_pending', 'file_tnail', 'directory', 'archives', 'ownership')
    fields = ('name', 'sortname', 'lastscan', 'lastmod', 'size', 'fqpndirectory', 'ignore', 'delete_pending', 'file_tnail', 'directory', 'archives', 'ownership')

admin.site.register(owners)
admin.site.register(Favorites)
