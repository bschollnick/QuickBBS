# Utilities

> Auto-generated documentation for [frontend.utilities](blob/master/frontend/utilities.py) module.

Utilities for QuickBBS, the python edition.

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Utilities
    - [break_down_urls](#break_down_urls)
    - [cr_tnail_img](#cr_tnail_img)
    - [delete_from_cache_tracking](#delete_from_cache_tracking)
    - [ensures_endswith](#ensures_endswith)
    - [is_valid_uuid](#is_valid_uuid)
    - [multiple_replace](#multiple_replace)
    - [naturalize](#naturalize)
    - [read_from_disk](#read_from_disk)
    - [rename_file](#rename_file)
    - [return_breadcrumbs](#return_breadcrumbs)
    - [return_disk_listing](#return_disk_listing)
    - [return_image_obj](#return_image_obj)
    - [sort_order](#sort_order)
    - [test_extension](#test_extension)

## break_down_urls

[[find in source code]](blob/master/frontend/utilities.py#L608)

```python
def break_down_urls(uri_path):
```

## cr_tnail_img

[[find in source code]](blob/master/frontend/utilities.py#L220)

```python
def cr_tnail_img(source_image, size, fext):
```

Given the PILLOW object, resize the image to <SIZE>
and return the saved version of the file (using FEXT
as the format to save as [eg. PNG])

Return the binary representation of the file that
was saved to memory

## delete_from_cache_tracking

[[find in source code]](blob/master/frontend/utilities.py#L332)

```python
def delete_from_cache_tracking(event):
```

## ensures_endswith

[[find in source code]](blob/master/frontend/utilities.py#L65)

```python
def ensures_endswith(string_to_check, value):
```

## is_valid_uuid

[[find in source code]](blob/master/frontend/utilities.py#L95)

```python
def is_valid_uuid(uuid_to_test, version=4):
```

Check if uuid_to_test is a valid UUID.
https://stackoverflow.com/questions/19989481

#### Arguments

uuid_to_test (str) - UUID code to validate
version (int) - UUID version to validate against (eg  1, 2, 3, 4)

#### Returns

boolean

```python
`True` if uuid_to_test is a valid UUID, otherwise `False`.
```

#### Raises

None

Examples
--------

```python
>>> is_valid_uuid('c9bf9e57-1685-4c89-bafb-ff5af830be8a')
True
>>> is_valid_uuid('c9bf9e58')
False

## multiple_replace

[[find in source code]](blob/master/frontend/utilities.py#L267)

```python
def multiple_replace(repl_dict, text):
```

## naturalize

[[find in source code]](blob/master/frontend/utilities.py#L252)

```python
def naturalize(string):
```

return <STRING> as a english sortable <STRING>

## read_from_disk

[[find in source code]](blob/master/frontend/utilities.py#L342)

```python
def read_from_disk(dir_to_scan, skippable=True):
```

Pass in FQFN, and the database stores the path as the URL path.

## rename_file

[[find in source code]](blob/master/frontend/utilities.py#L58)

```python
def rename_file(old_filename, new_filename):
```

## return_breadcrumbs

[[find in source code]](blob/master/frontend/utilities.py#L612)

```python
def return_breadcrumbs(uri_path=''):
```

## return_disk_listing

[[find in source code]](blob/master/frontend/utilities.py#L273)

```python
def return_disk_listing(fqpn, enable_rename=False):
```

## return_image_obj

[[find in source code]](blob/master/frontend/utilities.py#L152)

```python
def return_image_obj(fs_path, memory=False):
```

Given a Fully Qualified FileName/Pathname, open the image
(or PDF) and return the PILLOW object for the image
Fitz == py

#### Arguments

fs_path (str) - File system path
memory (bool) - Is this to be mapped in memory

#### Returns

boolean

```python
`True` if uuid_to_test is a valid UUID, otherwise `False`.
```

#### Raises

obj

```python
Pillow image object
```

Examples
--------

## sort_order

[[find in source code]](blob/master/frontend/utilities.py#L70)

```python
def sort_order(request, context):
```

Grab the sort order from the request (cookie)
and apply it to the session, and to the context for the web page.

#### Arguments

request (obj) - The request object
context (dict) - The dictionary for the web page template

#### Returns

obj

```python
The request object
```

dict

```python
The context dictionary
```

#### Raises

None

Examples
--------

## test_extension

[[find in source code]](blob/master/frontend/utilities.py#L126)

```python
def test_extension(name, ext_list):
```

Check if filename has an file extension that is in passed list.

#### Arguments

- `name` *str* - The Filename to examine
- `ext_list` *list* - ['zip', 'rar', etc] # list of file extensions (w/o .),
    lowercase.

#### Returns

boolean

```python
`True` if name does match an extension passed, otherwise `False`.
```

#### Raises

None

Examples
--------

```python
>>> test_extension("test.zip", ['zip', 'cbz'])
True
>>> test_extension("test.rar", ['zip', 'cbz'])
False
