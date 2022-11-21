from django.contrib import admin

# Register your models here.
from filetypes.models import *

@admin.register(filetypes)
class AdminFiletypes(admin.ModelAdmin):
    fields = ('fileext', 'icon_filename', 'color', 'generic', 'filetype')
    list_display = ('fileext', 'icon_filename', 'color', 'generic', 'filetype')
