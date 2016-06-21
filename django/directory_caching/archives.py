"""
Unified Archive support for Directory Caching.

Adds:

* ZIP / CBZ
* RAR / CBR

Support to the directory caching code.
"""

#		Gallery Comic Support
#
#
import exceptions
import os
import os.path
import rarfile  # https://github.com/markokr/rarfile
import zipfile

rarfile.PATH_SEP = '/'

RAR_FILE_TYPES = [".cbr", ".rar"]
ZIP_FILE_TYPES = [".cbz", ".zip"]

ARCHIVE_FILE_TYPES = RAR_FILE_TYPES + ZIP_FILE_TYPES

def return_archive_listing(fqfn):
    """
    Returns listings in raw order for the ZIP / CBZ / CBR / RAR archive

    Inputs:

    * Archive FQFN

    Outputs:

    * If successful, a list of filenames from the zipfile
    * If failed, returns NONE
    """
    file_extension = os.path.splitext(fqfn)[1].lower().strip()
    if file_extension in RAR_FILE_TYPES:
        try:
            rfile = rarfile.RarFile(fqfn, 'r')
            data = []
            for afn in rfile.namelist():
                if afn.startswith("__MACOSX") or os.path.split(afn)[1] == "":
                    pass
                else:
                    data.append(afn)
        except rarfile.BadRarFile, rarfile.NotRarFile:
            data = None
        except rarfile.NeedFirstVolume, exceptions.IOError:
            data = None
    elif file_extension in ZIP_FILE_TYPES:
        try:
            zipfile.is_zipfile(fqfn)
            zfile = zipfile.ZipFile(fqfn, 'r')
            data = []
            for afn in zfile.namelist():
                if afn.startswith("__MACOSX") or os.path.split(afn)[1] == "":
                    pass
                else:
                    data.append(afn)
        except zipfile.BadZipfile, zipfile.LargeZipFile:
            data = None
        except exceptions.IOError:
            data = None
    return data

def return_archive_contents(fqfn, filename):
    """
    Return the data from an archive file.

    inputs:

    * The FQFN of the archive file
    * The FILENAME of the archive member to be returned

    outputs:

    * If successful the raw data stream from the archive
    * If failed, None

    """
    file_extension = os.path.splitext(fqfn)[1].lower().strip()
    if file_extension in RAR_FILE_TYPES:
        try:
            rfile = rarfile.RarFile(fqfn, 'r')
            return rfile.read(filename)
        except exceptions.TypeError:
            pass
        except rarfile.BadRarFile, rarfile.NotRarFile:
            pass
        except rarfile.NeedFirstVolume:
            pass
        return None
    elif file_extension in ZIP_FILE_TYPES:
        try:
            zfile = zipfile.ZipFile(fqfn, 'r')
            return zfile.read(filename)
        except exceptions.IOError:
            return None
