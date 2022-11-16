# Admin

> Auto-generated documentation for [frontend.admin](blob/master/frontend/admin.py) module.

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Admin
    - [AdminFiletypes](#adminfiletypes)
    - [AdminMaster_Index](#adminmaster_index)
    - [AdminThumbnail_Archives](#adminthumbnail_archives)
    - [AdminThumbnail_Dirs](#adminthumbnail_dirs)
    - [AdminThumbnail_Files](#adminthumbnail_files)

## AdminFiletypes

[[find in source code]](blob/master/frontend/admin.py#L7)

```python
admin.register(filetypes)
class AdminFiletypes(admin.ModelAdmin):
```

## AdminMaster_Index

[[find in source code]](blob/master/frontend/admin.py#L27)

```python
admin.register(index_data)
class AdminMaster_Index(admin.ModelAdmin):
```

## AdminThumbnail_Archives

[[find in source code]](blob/master/frontend/admin.py#L22)

```python
admin.register(Thumbnails_Archives)
class AdminThumbnail_Archives(admin.ModelAdmin):
```

## AdminThumbnail_Dirs

[[find in source code]](blob/master/frontend/admin.py#L12)

```python
admin.register(Thumbnails_Dirs)
class AdminThumbnail_Dirs(admin.ModelAdmin):
```

## AdminThumbnail_Files

[[find in source code]](blob/master/frontend/admin.py#L17)

```python
admin.register(Thumbnails_Files)
class AdminThumbnail_Files(admin.ModelAdmin):
```
