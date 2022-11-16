# Views

> Auto-generated documentation for [frontend.views](blob/master/frontend/views.py) module.

Django views for QuickBBS Gallery

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Views
    - [downloadFile](#downloadfile)
    - [item_info](#item_info)
    - [new_archive_item](#new_archive_item)
    - [new_json_viewitem](#new_json_viewitem)
    - [new_view_archive](#new_view_archive)
    - [new_viewgallery](#new_viewgallery)
    - [new_viewitem](#new_viewitem)
    - [return_prev_next](#return_prev_next)
    - [thumbnails](#thumbnails)

## downloadFile

[[find in source code]](blob/master/frontend/views.py#L408)

```python
def downloadFile(request, filename=None):
```

Replaces new_download.

This now takes http://<servername>/downloads/<filename>?UUID=<uuid>

This fakes the browser into displaying the filename as the title of the
download.

## item_info

[[find in source code]](blob/master/frontend/views.py#L239)

```python
@cache_page(120)
def item_info(request, i_uuid):
```

## new_archive_item

[[find in source code]](blob/master/frontend/views.py#L552)

```python
def new_archive_item(request, i_uuid):
```

Show item in an archive

## new_json_viewitem

[[find in source code]](blob/master/frontend/views.py#L323)

```python
def new_json_viewitem(request, i_uuid):
```

## new_view_archive

[[find in source code]](blob/master/frontend/views.py#L472)

```python
def new_view_archive(request, i_uuid):
```

Show the gallery from the archive contents

## new_viewgallery

[[find in source code]](blob/master/frontend/views.py#L170)

```python
@cache_page(60)
def new_viewgallery(request):
```

View the requested Gallery page

## new_viewitem

[[find in source code]](blob/master/frontend/views.py#L342)

```python
def new_viewitem(request, i_uuid):
```

## return_prev_next

[[find in source code]](blob/master/frontend/views.py#L68)

```python
def return_prev_next(fqpn, currentpath, sorder):
```

Read the parent directory, get the index of the current path,
return the previous & next paths.

Replace the old system, with Django pagination.

## thumbnails

[[find in source code]](blob/master/frontend/views.py#L106)

```python
@cache_page(120)
def thumbnails(request, t_url_name=None):
```

Serve the thumbnail resources

URL -> thumbnails/(?P<t_url_name>.*)
