# Database

> Auto-generated documentation for [frontend.database](blob/master/frontend/database.py) module.

Database Specific Functions

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Database
    - [check_dup_thumbs](#check_dup_thumbs)
    - [check_for_deletes](#check_for_deletes)
    - [get_db_files](#get_db_files)
    - [get_filtered](#get_filtered)
    - [get_values](#get_values)
    - [get_xth_image](#get_xth_image)
    - [return_offset_uuid](#return_offset_uuid)
    - [validate_database](#validate_database)

## check_dup_thumbs

[[find in source code]](blob/master/frontend/database.py#L98)

```python
def check_dup_thumbs(uuid_to_check, page=0):
```

Eliminate any duplicates in the Thumbnail Databases

Parameters
----------
uuid : str - The uuid of the index Filerec
page : int - The page number of the archive file that is being examined

Examples
--------
check_dup_thumbs(uuid)

check_dup_thumbs(uuid, page=4)

## check_for_deletes

[[find in source code]](blob/master/frontend/database.py#L40)

```python
def check_for_deletes():
```

Check to see if any deleted items exist, if so, delete them.

## get_db_files

[[find in source code]](blob/master/frontend/database.py#L77)

```python
def get_db_files(sorder, fpath):
```

Fetch specific database values only from the database

## get_filtered

[[find in source code]](blob/master/frontend/database.py#L70)

```python
def get_filtered(queryset, filtervalues):
```

Apply a filter to the queryset

## get_values

[[find in source code]](blob/master/frontend/database.py#L56)

```python
def get_values(database, values):
```

Fetch specific database values only from the database

## get_xth_image

[[find in source code]](blob/master/frontend/database.py#L138)

```python
def get_xth_image(database, positional=0, filters=None):
```

Return the xth image from the database, using the passed filters

Parameters
----------

database : object - The django database handle

positional : int - 0 is first, if positional is greater than the # of
             records, then it is reset to the count of records

filters : dictionary of filters

#### Returns

boolean

```python
If successful the database record in question,
        otherwise returns None
```

Examples
--------
return_img_attach("test.png", img_data)

## return_offset_uuid

[[find in source code]](blob/master/frontend/database.py#L85)

```python
def return_offset_uuid(sorder, fpath, tuuid):
```

Fetch specific database values only from the database

## validate_database

[[find in source code]](blob/master/frontend/database.py#L17)

```python
def validate_database(dir_to_scan):
```

validate the data base
