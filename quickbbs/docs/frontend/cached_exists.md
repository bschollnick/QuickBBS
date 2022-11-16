# Cached Exists

> Auto-generated documentation for [frontend.cached_exists](blob/master/frontend/cached_exists.py) module.

Cached file exists

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Cached Exists
    - [cached_exist](#cached_exist)
- [File size Tests](#file-size-tests)
        - [cached_exist().addFile](#cached_existaddfile)
- [File size Tests](#file-size-tests)
        - [cached_exist().addFileDirEntry](#cached_existaddfiledirentry)
- [File size Tests](#file-size-tests)
        - [cached_exist().check_count](#cached_existcheck_count)
- [File size Tests](#file-size-tests)
        - [cached_exist().check_lastmod](#cached_existcheck_lastmod)
        - [cached_exist().clear_path](#cached_existclear_path)
        - [cached_exist().clear_scanned_paths](#cached_existclear_scanned_paths)
        - [cached_exist().fexistImgHash](#cached_existfexistimghash)
- [File size Tests](#file-size-tests)
        - [cached_exist().fexistName](#cached_existfexistname)
- [File size Tests](#file-size-tests)
        - [cached_exist().fexistSha](#cached_existfexistsha)
- [File size Tests](#file-size-tests)
        - [cached_exist().generate_imagehash](#cached_existgenerate_imagehash)
        - [cached_exist().generate_sha224](#cached_existgenerate_sha224)
        - [cached_exist().generate_sha256](#cached_existgenerate_sha256)
        - [cached_exist().processFile](#cached_existprocessfile)
        - [cached_exist().read_path](#cached_existread_path)
        - [cached_exist().return_extended_count](#cached_existreturn_extended_count)
        - [cached_exist().return_fileCount](#cached_existreturn_filecount)
        - [cached_exist().return_imagehash_name](#cached_existreturn_imagehash_name)
        - [cached_exist().return_newest](#cached_existreturn_newest)
        - [cached_exist().return_sha224_name](#cached_existreturn_sha224_name)
        - [cached_exist().sanitize_filenames](#cached_existsanitize_filenames)
        - [cached_exist().search_file_exist](#cached_existsearch_file_exist)
        - [cached_exist().search_imagehash_exist](#cached_existsearch_imagehash_exist)
        - [cached_exist().search_sha224_exist](#cached_existsearch_sha224_exist)
        - [cached_exist().search_sha224_exist](#cached_existsearch_sha224_exist)
        - [cached_exist().set_reset_count](#cached_existset_reset_count)
    - [clear_scanned_paths](#clear_scanned_paths)
    - [file_exist](#file_exist)
- [File size Tests](#file-size-tests)
    - [read_path](#read_path)
    - [search_exist](#search_exist)

Quick and Fast execution to avoid hitting hard drive to check if a file exists.

import cached_exists
db = cached_exists.cached_exist(use_image_hash=False)
db.read_path(dirpath=r'/Volumes/masters/masters/instagram2/A/allyauer/',recursive=True)
db.scanned_paths

import cached_exists
db = cached_exists.cached_exist(use_image_hash=True)
db.read_path(dirpath=r'/Volumes/masters/masters/instagram2/A/allyauer/',recursive=True)
db.read_path(dirpath=r'/Volumes/masters/masters/gallery-dl/gallery-dl/deviantart/allyauer/',recursive=True)

test1 = r'/Volumes/masters/masters/instagram2/A/allyauer/2021-08-08_18-52-15_UTC.jpg'
test2 = r'/Volumes/masters/masters/gallery-dl/gallery-dl/deviantart/allyauer/deviantart_887872179_Ada Wong.jpg'
db.fexistImgHash(filename=test1)
db.fexistImgHash(filename=test2)

t1 = db.fexistImgHash(filename=test1, rtn_size=True)
t2 = db.fexistImgHash(filename=test2, rtn_size=True)

z = db.generate_imagehash(test1)
db.search_imagehash_exist(img_hash=z)
db.return_imagehash_name(img_hash=z)

print(db.return_imagehash_name(img_hash=z))

## cached_exist

[[find in source code]](blob/master/frontend/cached_exists.py#L50)

```python
class cached_exist():
    def __init__(
        reset_count=RESET_COUNT,
        use_modify=False,
        use_shas=False,
        FilesOnly=True,
        use_extended=False,
        use_filtering=False,
        use_image_hash=False,
        image_hasher=imagehash.average_hash,
    ):
```

Cached Exist functionality - Caching engine to detect by filename,
    and SHA224.   Can use last modification and file / dir count to
    identify cache invalidation.

#### Arguments

- `reset_count` *integer* - The number of queries to allow before
    forcing a cache invalidation.

- `use_modify` *boolean* - Store & Use the last modified date of
    the contents of the directory for cache invalidation.

- `use_shas` *boolean* - Store & Use SHA224 for the files that
    are scanned.

- `FilesOnly` *boolean* - Ignore directories

- `use_extended` *boolean* - Store direntries, and break out
    directory & files counts.

#### Returns

- `Boolean` - True if the file exists, or false if it doesn't.
- `Integer` - If rtn_size is true, an existing file will return
    an integer

.. code-block:
    # Boolean Tests

```python
>>> file_exist(r"test_samples\monty.csv")
True
>>> file_exist(r"test_samples\small.csv")
True
>>> file_exist(r"test_samples\monty_lives_here.csv")
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt")
False
```

# File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv",
                rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

#### See also

- [RESET_COUNT](#reset_count)

### cached_exist().addFile

[[find in source code]](blob/master/frontend/cached_exists.py#L600)

```python
def addFile(dirpath, filename, sha_hd, filesize, mtime, img_hash=None):
```

sanitize_filenames - sanitize the filename to windows standards.
    optionally force the rename of the files.

#### Arguments

- `filename` *string* - The number of queries to allow before
    forcing a cache invalidation.

- `dirpath` *string* - The directory path of the file to be added

- `sha_hd` *string* - hexdigest

filesize (integer) : filesize

mtime (integer) : modification time

#### Raises

NotImplementedError : When used in use_modify mode.  DirEntries
    can not be created programmatically, and thus can not be
    passed into addFile.  (*EG* addFile can't be used when
    use_modify mode is on.)

.. code-block:
    # Boolean Tests

```python
>>> file_exist(r"test_samples\monty.csv")
True
>>> file_exist(r"test_samples\small.csv")
True
>>> file_exist(r"test_samples\monty_lives_here.csv")
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt")
False
```

# File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv",
                rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

### cached_exist().addFileDirEntry

[[find in source code]](blob/master/frontend/cached_exists.py#L537)

```python
def addFileDirEntry(fileentry, sha_hd=None, img_hash=None):
```

sanitize_filenames - sanitize the filename to windows standards.
    optionally force the rename of the files.

#### Arguments

- `fileentry` *DirEntry* - The DirEntry of the file to be added

- `sha_hd` *boolean* - The Sha224 HexDigest of the file in question

.. code-block:
   # Boolean Tests

```python
>>> file_exist(r"test_samples\monty.csv")
True
>>> file_exist(r"test_samples\small.csv")
True
>>> file_exist(r"test_samples\monty_lives_here.csv")
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt")
False
```

# File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv",
                rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

### cached_exist().check_count

[[find in source code]](blob/master/frontend/cached_exists.py#L282)

```python
def check_count(dirpath):
```

#### Arguments

- `dirpath` *string* - The path to the files to be sanitized

#### Returns

- `Integer` - Returns # of files in the directory, returning 0
    if the path has not been scanned (or contains no files).
    Returns None if a FileNotFoundError would have been
    raised.

.. code-block:
    # Boolean Tests

```python
>>> file_exist(r"test_samples\monty.csv")
True
>>> file_exist(r"test_samples\I_DONT-EXIST.txt")
False
```

# File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\monty_lives_here.csv",
                rtn_size=True)
False

### cached_exist().check_lastmod

[[find in source code]](blob/master/frontend/cached_exists.py#L335)

```python
def check_lastmod(dirpath):
```

#### Arguments

- `dirpath` *string* - The path to the files

#### Returns

- `Boolean` - True if the last_mods[dirpath] value for the directory
    matches the current newest last modified value in the
    directory.

Returns False, if the files do not match last modified date.

.. code-block:
    # Boolean Tests

### cached_exist().clear_path

[[find in source code]](blob/master/frontend/cached_exists.py#L181)

```python
def clear_path(path_to_clear):
```

clear_path - remove a specific directory from the cached entries

#### Arguments

- `path_to_clear` *string* - the FQPN of the path to remove

.. code-block:
    # Boolean Tests

### cached_exist().clear_scanned_paths

[[find in source code]](blob/master/frontend/cached_exists.py#L164)

```python
def clear_scanned_paths():
```

clear_scanned_paths - remove all cached paths

.. code-block:
    # Boolean Tests

### cached_exist().fexistImgHash

[[find in source code]](blob/master/frontend/cached_exists.py#L1074)

```python
def fexistImgHash(filename=None, rtn_size=False, img_hash=None):
```

Does the file exist?

The filename should be a path included (eg .\test.txt, or fqpn)
filename. The filename is split into directory path (dirpath), and
filename.

The dirpath is used to locate the directory contents in the
dictionary (Associated hashmap).  If it is not located/available,
then it will be
scanned via read_path.

Once the directory is available, a simple lookup is performed on the
list containing the directory & filenames that are contained in the
directory.

#### Arguments

- `filename` *string* - The path enabled filename, eg. .\test.txt,
    c:\users\bschollnick\test.txt.
    The filename is split (os.path.split) into the directory,
    and the filename.

- `rtn_size` *boolean* - If True, and the file exists, return
    filesize

- `sha_hd` *string* - sha hexdigest

#### Returns

- `Boolean` - True if the file exists, or false if it doesn't.
- `Integer` - If rtn_size is true, an existing file will return
    an integer

.. code-block:
    # Boolean Tests

```python
>>> file_exist(r"test_samples\monty.csv")
True
>>> file_exist(r"test_samples\small.csv")
True
>>> file_exist(r"test_samples\monty_lives_here.csv")
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt")
False
```

# File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv",
               rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

### cached_exist().fexistName

[[find in source code]](blob/master/frontend/cached_exists.py#L759)

```python
def fexistName(filename, rtn_size=False):
```

Does the file exist?

The filename should be a path included (eg .\test.txt, or fqpn)
filename.  The filename is split into directory path (dirpath),
and filename.

The dirpath is used to locate the directory contents in the
dictionary (Associated hashmap).  If it is not located/available,
then it will be scanned via read_path.

Once the directory is available, a simple lookup is performed on the
list containing the directory & filenames that are contained in the
directory.

#### Arguments

- `filename` *string* - The path enabled filename, eg. .\test.txt,
    c:\users\bschollnick\test.txt.
    The filename is split (os.path.split) into the directory,
    and the filename.

- `rtn_size` *boolean* - If True, and the file exists, return
    filesize

#### Returns

- `Boolean` - True if the file exists, or false if it doesn't.
- `Integer` - If rtn_size is true, an existing file will return
    an integer

.. code-block:
    # Boolean Tests

```python
>>> file_exist(r"test_samples\monty.csv")
True
>>> file_exist(r"test_samples\small.csv")
True
>>> file_exist(r"test_samples\monty_lives_here.csv")
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt")
False
```

# File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv",
                rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

### cached_exist().fexistSha

[[find in source code]](blob/master/frontend/cached_exists.py#L831)

```python
def fexistSha(filename=None, rtn_size=False, sha_hd=None):
```

Does the file exist?

The filename should be a path included (eg .\test.txt, or fqpn)
filename. The filename is split into directory path (dirpath), and
filename.

The dirpath is used to locate the directory contents in the
dictionary (Associated hashmap).  If it is not located/available,
then it will be
scanned via read_path.

Once the directory is available, a simple lookup is performed on the
list containing the directory & filenames that are contained in the
directory.

#### Arguments

- `filename` *string* - The path enabled filename, eg. .\test.txt,
    c:\users\bschollnick\test.txt.
    The filename is split (os.path.split) into the directory,
    and the filename.

- `rtn_size` *boolean* - If True, and the file exists, return
    filesize

- `sha_hd` *string* - sha hexdigest

#### Returns

- `Boolean` - True if the file exists, or false if it doesn't.
- `Integer` - If rtn_size is true, an existing file will return
    an integer

.. code-block:
    # Boolean Tests

```python
>>> file_exist(r"test_samples\monty.csv")
True
>>> file_exist(r"test_samples\small.csv")
True
>>> file_exist(r"test_samples\monty_lives_here.csv")
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt")
False
```

# File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv",
               rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

### cached_exist().generate_imagehash

[[find in source code]](blob/master/frontend/cached_exists.py#L463)

```python
def generate_imagehash(filename, debug=False):
```

#### Arguments

- `filename` *string* - The FQPN of the file to generate a
    sha256 from

- `hexdigest` *Boolean* - Return as a hexdigest; False - standard
    digest

#### Returns

- `String` - Either a Hexdigest or standard digest of sha256

.. code-block:
    # File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv",
                rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

### cached_exist().generate_sha224

[[find in source code]](blob/master/frontend/cached_exists.py#L419)

```python
def generate_sha224(filename, hexdigest=False, maxsize=0):
```

#### Arguments

- `filename` *string* - The FQPN of the file to generate a
    sha256 from

- `hexdigest` *Boolean* - Return as a hexdigest; False - standard
    digest

#### Returns

- `String` - Either a Hexdigest or standard digest of sha256

.. code-block:
    # File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv",
                rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

### cached_exist().generate_sha256

[[find in source code]](blob/master/frontend/cached_exists.py#L380)

```python
def generate_sha256(filename, hexdigest=False):
```

#### Arguments

- `filename` *string* - The FQPN of the file to generate a
    sha256 from

- `hexdigest` *Boolean* - Return as a hexdigest; False - standard
    digest

#### Returns

- `String` - Either a Hexdigest or standard digest of sha256

.. code-block:
    # File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv",
                rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

### cached_exist().processFile

[[find in source code]](blob/master/frontend/cached_exists.py#L501)

```python
def processFile(dentry):
```

#### Arguments

- `filename` *string* - The filename of the file currently being
    processed

#### Returns

- `Boolean` - True, if the file should be processed, False if not

.. code-block:
    # Boolean Tests

```python
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

### cached_exist().read_path

[[find in source code]](blob/master/frontend/cached_exists.py#L674)

```python
def read_path(dirpath, recursive=False):
```

Read a path using SCANDIR (https://pypi.org/project/scandir/).

#### Arguments

- `dirpath` *string* - The directory path to read

#### Returns

- `boolean` - True successful read the directory,
         False if unable to read

Using the scandir.walk(dirpath).next() functionality to
dump the listing into a set, so that we do not have to iterate
through the generator making it ourselves.

.. code-block:

```python
>>> read_path(r".")
True
>>> read_path(r"c:\turnup\test.me")
False

### cached_exist().return_extended_count

[[find in source code]](blob/master/frontend/cached_exists.py#L229)

```python
def return_extended_count(dirpath):
```

#### Arguments

- `dirpath` *string* - The path to the files to be sanitized

#### Returns

- `Tuple` - A Tuple of Integers.  (fileCount, dirCount)
    fileCount is the # of files in the directory, and
    dirCount is the # of child directories in the directory.

.. code-block:
    # Boolean Tests

### cached_exist().return_fileCount

[[find in source code]](blob/master/frontend/cached_exists.py#L207)

```python
def return_fileCount(dirpath):
```

return the count of files in the cached directory path

#### Arguments

- `dirpath` *string* - The path to the files to be sanitized

#### Returns

- `Integer` - the # of files contained.  If empty or
    non-existent, returns 0

.. code-block:
    # Boolean Tests

### cached_exist().return_imagehash_name

[[find in source code]](blob/master/frontend/cached_exists.py#L1206)

```python
def return_imagehash_name(img_hash=None):
```

import cached_exists
filedb = cached_exists.cached_exist(use_shas=True, FilesOnly=True)
filedb.read_path(".")
filedb.search_sha224_exist(shaHD="49dbafd07e1415c383baa9f61f6381ace7c057da4f90b7e2e19a5c57") # ftypes.py
filedb.return_sha224_name(shaHD="49dbafd07e1415c383baa9f61f6381ace7c057da4f90b7e2e19a5c57")

### cached_exist().return_newest

[[find in source code]](blob/master/frontend/cached_exists.py#L262)

```python
def return_newest(dirpath):
```

### cached_exist().return_sha224_name

[[find in source code]](blob/master/frontend/cached_exists.py#L1013)

```python
def return_sha224_name(shaHD=None):
```

import cached_exists
filedb = cached_exists.cached_exist(use_shas=True, FilesOnly=True)
filedb.read_path(".")
filedb.search_sha224_exist(shaHD="49dbafd07e1415c383baa9f61f6381ace7c057da4f90b7e2e19a5c57") # ftypes.py
filedb.return_sha224_name(shaHD="49dbafd07e1415c383baa9f61f6381ace7c057da4f90b7e2e19a5c57")

### cached_exist().sanitize_filenames

[[find in source code]](blob/master/frontend/cached_exists.py#L132)

```python
def sanitize_filenames(dirpath, allow_rename=False):
```

sanitize_filenames - sanitize the filename to windows standards.
    optionally force the rename of the files.

#### Arguments

- `dirpath` *string* - The path to the files to be sanitized

- `allow_rename` *boolean* - Allow the renaming of the files to
    conform to a self.sanitize_plat (default-Windows)
    platform

.. code-block:
    # Boolean Tests

### cached_exist().search_file_exist

[[find in source code]](blob/master/frontend/cached_exists.py#L919)

```python
def search_file_exist(filename):
```

Does the file exist?

The filename should be a path included (eg .\test.txt, or fqpn)
filename. The filename is split into directory path (dirpath), and
filename.

The dirpath is used to locate the directory contents in the dictionary
(Associated hashmap).  If it is not located/available, then it will be
scanned via read_path.

Once the directory is available, a simple lookup is performed on the
list containing the directory & filenames that are contained in the
directory.

#### Arguments

- `filename` *string* - filename, eg. test.txt, **NOT FQFN**
    test.txt **NOT** c:\users\bschollnick\test.txt

#### Returns

- `Boolean` - True if the file exists, or false if it doesn't.

- `*NOTE*` - This only checks for the prescence of the file, it will not scan
 the drive for the file.  So *ENSURE* that the folder you want to search
 has already been read_path'd.

This is the equivalent of the which command.  eg. Which directory is
this file exist in?

- `..` *code-block:* - python

```python
>>> clear_scanned_paths()
>>> search_exist("monty.csv")
(False, None)
>>> read_path("test_samples")
True
>>> search_exist("monty.csv")
(True, 'test_samples')

### cached_exist().search_imagehash_exist

[[find in source code]](blob/master/frontend/cached_exists.py#L1159)

```python
def search_imagehash_exist(img_hash=None):
```

Does the file exist?

The filename should be a path included (eg .\test.txt, or fqpn)
filename. The filename is split into directory path (dirpath), and
filename.

The dirpath is used to locate the directory contents in the dictionary
(Associated hashmap).  If it is not located/available, then it will be
scanned via read_path.

Once the directory is available, a simple lookup is performed on the
list containing the directory & filenames that are contained in the
directory.

#### Arguments

- `shaHD` *string* - Hexdigest

#### Returns

- `Tupple` - Element 0 - Boolean - True if the file exists,
            or false if it doesn't.
        Element 1 - String - Directory file was found in.

- `*NOTE*` - This only checks for the prescence of the file, it will not scan
 the drive for the file.  So *ENSURE* that the folder you want to search
 has already been read_path'd.

This is the equivalent of the which command.  eg. Which directory is
this file exist in?

- `..` *code-block:* - python

```python
>>> clear_scanned_paths()
>>> search_exist("monty.csv")
(False, None)
>>> read_path("test_samples")
True
>>> search_exist("monty.csv")
(True, 'test_samples')

### cached_exist().search_sha224_exist

[[find in source code]](blob/master/frontend/cached_exists.py#L966)

```python
def search_sha224_exist(shaHD=None):
```

Does the file exist?

The filename should be a path included (eg .\test.txt, or fqpn)
filename. The filename is split into directory path (dirpath), and
filename.

The dirpath is used to locate the directory contents in the dictionary
(Associated hashmap).  If it is not located/available, then it will be
scanned via read_path.

Once the directory is available, a simple lookup is performed on the
list containing the directory & filenames that are contained in the
directory.

#### Arguments

- `shaHD` *string* - Hexdigest

#### Returns

- `Tupple` - Element 0 - Boolean - True if the file exists,
            or false if it doesn't.
        Element 1 - String - Directory file was found in.

- `*NOTE*` - This only checks for the prescence of the file, it will not scan
 the drive for the file.  So *ENSURE* that the folder you want to search
 has already been read_path'd.

This is the equivalent of the which command.  eg. Which directory is
this file exist in?

- `..` *code-block:* - python

```python
>>> clear_scanned_paths()
>>> search_exist("monty.csv")
(False, None)
>>> read_path("test_samples")
True
>>> search_exist("monty.csv")
(True, 'test_samples')

### cached_exist().search_sha224_exist

[[find in source code]](blob/master/frontend/cached_exists.py#L1027)

```python
def search_sha224_exist(shaHD=None):
```

Does the file exist?

The filename should be a path included (eg .\test.txt, or fqpn)
filename. The filename is split into directory path (dirpath), and
filename.

The dirpath is used to locate the directory contents in the dictionary
(Associated hashmap).  If it is not located/available, then it will be
scanned via read_path.

Once the directory is available, a simple lookup is performed on the
list containing the directory & filenames that are contained in the
directory.

#### Arguments

- `shaHD` *string* - Hexdigest

#### Returns

- `Tupple` - Element 0 - Boolean - True if the file exists,
            or false if it doesn't.
        Element 1 - String - Directory file was found in.

- `*NOTE*` - This only checks for the prescence of the file, it will not scan
 the drive for the file.  So *ENSURE* that the folder you want to search
 has already been read_path'd.

This is the equivalent of the which command.  eg. Which directory is
this file exist in?

- `..` *code-block:* - python

```python
>>> clear_scanned_paths()
>>> search_exist("monty.csv")
(False, None)
>>> read_path("test_samples")
True
>>> search_exist("monty.csv")
(True, 'test_samples')

### cached_exist().set_reset_count

[[find in source code]](blob/master/frontend/cached_exists.py#L367)

```python
def set_reset_count(reset_count=RESET_COUNT):
```

#### Arguments

- `reset_count` *integer* - The number of queries to allow before
    forcing a cache invalidation.

.. code-block:

```python
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

#### See also

- [RESET_COUNT](#reset_count)

## clear_scanned_paths

[[find in source code]](blob/master/frontend/cached_exists.py#L1219)

```python
def clear_scanned_paths():
```

Clear the scanned path datastore

## file_exist

[[find in source code]](blob/master/frontend/cached_exists.py#L1272)

```python
def file_exist(filename, rtn_size=False):
```

Does the file exist?

The filename should be a path included (eg .\test.txt, or fqpn)
filename. The filename is split into directory path (dirpath), and
filename.

The dirpath is used to locate the directory contents in the dictionary
(Associated hashmap).  If it is not located/available, then it will be
scanned via read_path.

Once the directory is available, a simple lookup is performed on the
list containing the directory & filenames that are contained in the
directory.

#### Arguments

- `filename` *string* - The path enabled filename, eg. .\test.txt,
    c:\users\bschollnick\test.txt.
    The filename is split (os.path.split) into the directory,
    and the filename.

- `rtn_size` *boolean* - If True, and the file exists, return filesize

#### Returns

- `Boolean` - True if the file exists, or false if it doesn't.
- `Integer` - If rtn_size is true, an existing file will return
    an integer

.. code-block:
    # Boolean Tests

```python
>>> file_exist(r"test_samples\monty.csv")
True
>>> file_exist(r"test_samples\small.csv")
True
>>> file_exist(r"test_samples\monty_lives_here.csv")
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt")
False
```

# File size Tests

```python
>>> file_exist(r"test_samples\monty.csv", rtn_size=True)
76
>>> file_exist(r"test_samples\small.csv", rtn_size=True)
44
>>> file_exist(r"test_samples\monty_lives_here.csv", rtn_size=True)
False
>>> file_exist(r"test_samples\I_DONT-EXIST.txt", rtn_size=True)
False

## read_path

[[find in source code]](blob/master/frontend/cached_exists.py#L1227)

```python
def read_path(dirpath, recursive=False):
```

Read a path using SCANDIR (https://pypi.org/project/scandir/).

#### Arguments

- `dirpath` *string* - The directory path to read

#### Returns

- `boolean` - True successful read the directory,
         False if unable to read

Using the scandir.walk(dirpath).next() functionality to dump the listing
    into a set, so that we do not have to iterate through the generator
    making it ourselves.

.. code-block:

```python
>>> read_path(r".")
True
>>> read_path(r"c:\turnup\test.me")
False

## search_exist

[[find in source code]](blob/master/frontend/cached_exists.py#L1345)

```python
def search_exist(filename):
```

Does the file exist?

The filename should be a path included (eg .\test.txt, or fqpn) filename.
The filename is split into directory path (dirpath), and filename.

The dirpath is used to locate the directory contents in the dictionary
(Associated hashmap).  If it is not located/available, then it will be
scanned via read_path.

Once the directory is available, a simple lookup is performed on the
list containing the directory & filenames that are contained in the
directory.

#### Arguments

- `filename` *string* - filename, eg. test.txt, **NOT FQFN**
    test.txt **NOT** c:\users\bschollnick\test.txt

#### Returns

- `Boolean` - True if the file exists, or false if it doesn't.

- `*NOTE*` - This only checks for the prescence of the file, it will not scan
 the drive for the file.  So *ENSURE* that the folder you want to search
 has already been read_path'd.

This is the equivalent of the which command.  eg. Which directory is this
 file exist in?

- `..` *code-block:* - python

```python
>>> clear_scanned_paths()
>>> search_exist("monty.csv")
(False, None)
>>> read_path("test_samples")
True
>>> search_exist("monty.csv")
(True, 'test_samples')
