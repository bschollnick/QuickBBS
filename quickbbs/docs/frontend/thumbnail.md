# Thumbnail

> Auto-generated documentation for [frontend.thumbnail](blob/master/frontend/thumbnail.py) module.

Thumbnail routines for QuickBBS

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Thumbnail
    - [ensures_endswith](#ensures_endswith)
    - [images_in_dir](#images_in_dir)
    - [invalidate_thumb](#invalidate_thumb)
    - [new_process_archive](#new_process_archive)
    - [new_process_dir](#new_process_dir)
    - [new_process_img](#new_process_img)

## ensures_endswith

[[find in source code]](blob/master/frontend/thumbnail.py#L29)

```python
def ensures_endswith(string_to_check, value):
```

## images_in_dir

[[find in source code]](blob/master/frontend/thumbnail.py#L34)

```python
def images_in_dir(database, webpath):
```

Check for images in the directory.
If they do not exist, try to load the directory, and test again.
If they do exist, grab the 1st image from the file list.

#### Arguments

database (obj) - Django Database
webpath (str) - The directory to examine

#### Returns

object

```python
The thumbnail (in memory) of the first image
```

#### Raises

None

Examples
--------
#>>> is_valid_uuid('c9bf9e57-1685-4c89-bafb-ff5af830be8a')
#True
#>>> is_valid_uuid('c9bf9e58')
#False

## invalidate_thumb

[[find in source code]](blob/master/frontend/thumbnail.py#L139)

```python
def invalidate_thumb(thumbnail):
```

## new_process_archive

[[find in source code]](blob/master/frontend/thumbnail.py#L202)

```python
def new_process_archive(ind_entry, request, page=0):
```

Process an archive, and return the thumbnail

## new_process_dir

[[find in source code]](blob/master/frontend/thumbnail.py#L71)

```python
def new_process_dir(db_index):
```

input:
    entry - The index_data entry

Read directory, and identify the first thumbnailable file.
Make thumbnail of that file
Return thumbnail results

Since we are just looking for a thumbnailable image, it doesn't have
to be the most up to date, nor the most current.  Cached is fine.

## new_process_img

[[find in source code]](blob/master/frontend/thumbnail.py#L147)

```python
def new_process_img(entry, request, imagesize='Small'):
```

input:
    entry - The index_data entry
    request - The request data from Django
    imagesize - (small, medium, large constant)

Read directory, and identify the first thumbnailable file.
Make thumbnail of that file
Return thumbnail results

Since we are just looking for a thumbnailable image, it doesn't have
to be the most up to date, nor the most current.  Cached is fine.
