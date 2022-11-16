# Archives3

> Auto-generated documentation for [frontend.archives3](blob/master/frontend/archives3.py) module.

Unified Archive support for Python.

- [Quickbbs](../README.md#quickbbs-index) / [Modules](../MODULES.md#quickbbs-modules) / [Frontend](index.md#frontend) / Archives3
    - [CompressedFile](#compressedfile)
        - [CompressedFile().extract_mem_file](#compressedfileextract_mem_file)
        - [CompressedFile().extract_mem_file64](#compressedfileextract_mem_file64)
        - [CompressedFile().get_listings](#compressedfileget_listings)
        - [CompressedFile.is_signature](#compressedfileis_signature)
        - [CompressedFile().return_mime](#compressedfilereturn_mime)
    - [NotInitializedYet](#notinitializedyet)
    - [id_cfile_by_sig](#id_cfile_by_sig)

Adds:

* ZIP / CBZ
* RAR / CBR

Targeted intent is for Directory Caching, but usable in other venues.

The current model, is expanded from:

http://stackoverflow.com/questions/13044562/
    python-mechanism-to-identify-compressed-file-type-and-uncompress

Which gave me the spark on a sensible manner to deal with signature and
managing via the object model.

More File signatures are avialable here:

http://www.garykessler.net/library/file_sigs.html

Mimetype Information from here:

http://www.freeformatter.com/mime-types-list.html

Suggested workflow:

1) Initialize by using id_cfile_by_signature
    a) This will a populated class (with filename), archive listings will not
       be populated

2) Use the get_listings function to get the listings for the compressed file
3) Use extract_mem_file to pull out individual files, as needed.

Next steps:

Create a batch extractor?  To increase efficiency?

Zip, RAR are supported, what other formats might be useful?
    ?? PDF? - Technically not a archive, and will need to use Ghostscript to
              create extracted pages

## CompressedFile

[[find in source code]](blob/master/frontend/archives3.py#L70)

```python
class CompressedFile():
    def __init__(fname):
```

The mainstay of the Archive2 code.

This object is the framework that the inherited archive types are
based off of.

extensions - is a list of the file extensions that the archive is known
             to use.  For example, a zip file would be ['zip', 'cbz'].
             Currently, this is not used, but in the future it maybe.

- Possible future uses:
    - Check for archive by filename (with verification by
      signature done after matching by filename)

mime_type - The standard mimetype for the archive ()
            For example, for zip, it is 'compressed/zip'.
            Can be used, to identify the mimetype to a web server.

filename - Fully qualified local system Filename to the archive
           (eg c:\users\JohnCleese\archives\scripts101.zip)

listings - default value []

This contains the listings of the archive file.

**This is populated by the get_listings() function.**

This is somewhat non-intuitive.  But the logic is that
the programmer may want to add, remove, etc.  Open just
opens the the file, so that you can manipulate the
underlying archive file.

handler - Is the "pointer" to the archiver function used to manipulate
          the archive file.  For example:

zip file - zipfile.ZipFile
rar file - rarfile.RarFile

**This is normally populated by the id_cfile_by_sig function.**

signature - This is the "magic" signature that is used to identify
            the archive file.  It is used to compare the first xx bytes
            of the archive.  If it matches, then it is that type of
            archive.

#### Examples

filename='test.zip'
archive_file = archives2.id_cfile_by_sig(filename)
archive_file.get_listings()
print archive_file.listings
print filename, 'is a', cf.mime_type, 'file'

### CompressedFile().extract_mem_file

[[find in source code]](blob/master/frontend/archives3.py#L219)

```python
def extract_mem_file(fname):
```

Extract filename out of the archive, and return it as a blob.

inputs - filename to extract
returns - blob from the archive.

### CompressedFile().extract_mem_file64

[[find in source code]](blob/master/frontend/archives3.py#L239)

```python
def extract_mem_file64(fname):
```

Extract filename out of the archive, and return it as a base64 blob.

inputs - filename to extract
returns - blob from the archive.

### CompressedFile().get_listings

[[find in source code]](blob/master/frontend/archives3.py#L195)

```python
def get_listings():
```

Load the listings from the archive into self.listings.

inputs - None
returns - None

### CompressedFile.is_signature

[[find in source code]](blob/master/frontend/archives3.py#L148)

```python
@classmethod
def is_signature(data):
```

data (bool): The signature bytes from the archive file.

Checks the archive signature (self.signature) against the xxx bytes
from the file header.

If they match, returns True, else Returns False.

### CompressedFile().return_mime

[[find in source code]](blob/master/frontend/archives3.py#L182)

```python
def return_mime():
```

Return the stored mimetype for the archive file.

Inputs - None
Returns - If a recognized archive file is loaded, the mimetype of
          said archive.  Otherwise, None.

## NotInitializedYet

[[find in source code]](blob/master/frontend/archives3.py#L59)

```python
class NotInitializedYet(Exception):
```

General Purpose Exception Stub.

Called if self.handler in CompressedFile has not been
assigned, yet, the code has been asked to process (eg Open) the
compressed file.

## id_cfile_by_sig

[[find in source code]](blob/master/frontend/archives3.py#L320)

```python
def id_cfile_by_sig(fname):
```

Effectively the core function of the module.

It established and configures the archive functionality for the
filename passed to it.

Inputs - Fully qualified local filepathname of the archive file

Returns - The initialized archive class, that is configured to work
          with the archive (eg. ZIPFile class, or RarFile)

This function will read 128 bytes from the beginning of the file
and then step through the ARCHIVE_CLASSES, checking the signature
of each ARCHIVE_CLASSES, against the file contents.

If it finds a match, it will then return that class with the proper
filename.

#### Examples

filename='test.zip'
archive_file = archives2.id_cfile_by_sig(filename)
archive_file.get_listings()
print archive_file.listings
print filename, 'is a', cf.mime_type, 'file'
