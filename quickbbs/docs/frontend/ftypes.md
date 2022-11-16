# Ftypes

> Auto-generated documentation for [frontend.ftypes](blob/master/frontend/ftypes.py) module.

Utilities for QuickBBS, the python edition.

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Ftypes
    - [get_ftype_dict](#get_ftype_dict)
    - [map_ext_to_id](#map_ext_to_id)
    - [return_filetype](#return_filetype)
    - [return_identifier](#return_identifier)

#### Attributes

- `FILETYPE_DATA` - refresh_filetypes(): `get_ftype_dict()`

## get_ftype_dict

[[find in source code]](blob/master/frontend/ftypes.py#L25)

```python
def get_ftype_dict():
```

Return filetypes information (from table) in an dictionary form.

## map_ext_to_id

[[find in source code]](blob/master/frontend/ftypes.py#L47)

```python
def map_ext_to_id(ext):
```

Return the extension portion of the filename (minus the .)
Why is this duplicated?

## return_filetype

[[find in source code]](blob/master/frontend/ftypes.py#L14)

```python
def return_filetype(fileext):
```

Return the filetype data for a particular file extension

fileext: String, the extension of the file type with ., in lowercase
        eg .doc, .txt

## return_identifier

[[find in source code]](blob/master/frontend/ftypes.py#L38)

```python
def return_identifier(ext):
```

Return the extension portion of the filename (minus the .)
