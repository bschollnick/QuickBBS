# -*- coding: utf-8 -*-
"""
Unified Archive support for Python.

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
"""

#		Gallery Comic Support
#
#
from __future__ import absolute_import
from __future__ import print_function
import base64
import exceptions
import os
import os.path
import zipfile
import rarfile

class NotInitializedYet(exceptions.Exception):
    """
    General Purpose Exception Stub.

    Called if self.handler in CompressedFile has not been
    assigned, yet, the code has been asked to process (eg Open) the
    compressed file.
    """
    pass


class CompressedFile(object):
    r"""
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

Example:

filename='test.zip'
archive_file = archives2.id_cfile_by_sig(filename)
archive_file.get_listings()
print archive_file.listings
print filename, 'is a', cf.mime_type, 'file'
    """
    extensions = None
    mime_type = None
    filename = None
    listings = []
    handler = None
    signature = None

    def __init__(self, fname):
        """
        filename (str): The Fully Qualified Filename to the archive file

        :param filename: The Fully Qualified Filename to the archive file
        :type filename: string

        Initialization routines for Archive2.

        Inputs -
                 Filename - The fully qualified filename for the archive file

        Returns - None
        """
        self.filename = os.path.realpath(fname)
        self.listings = []

    @classmethod
    def is_signature(cls, data):
        """
        data (bool): The signature bytes from the archive file.

        Checks the archive signature (self.signature) against the xxx bytes
        from the file header.

        If they match, returns True, else Returns False.
        """
        return data.startswith(cls.signature)

    def _open(self):
        """
        Attempts to use self.handler to open the file.
        self.handler is normally set automatically by id_cfile_by_sig.
        If self.handler is not set, then it will raise NotInitializedYet.

        Inputs - None

        Returns - Handler as assigned by self.handler
       """
        if self.handler != None:
# pylint: disable=E1102
            try:
                return self.handler(self.filename, 'r')
            except rarfile.NeedFirstVolume:
                return None
            except rarfile.TypeError:
                return None
# pylint: enable=E1102
        else:
            raise NotInitializedYet

    def return_mime(self):
        """
        Return the stored mimetype for the archive file.

        Inputs - None
        Returns - If a recognized archive file is loaded, the mimetype of
                  said archive.  Otherwise, None.
        """
        if self.mime_type != None:
            return self.mime_type
        else:
            raise NotInitializedYet


    def get_listings(self):
        """
        Load the listings from the archive into self.listings.

        inputs - None
        returns - None
        """
        self.listings = []
        handle = self._open
        if handle() is None:
            return False

        with handle() as cfile:
            for afn in cfile.namelist():
                if not (afn.startswith("__MACOSX") or
                        os.path.split(afn)[1] == ""):
                    self.listings.append(afn)
            return True

        return False

    def extract_mem_file(self, fname):
        """
        Extract filename out of the archive, and return it as a blob.

        inputs - filename to extract
        returns - blob from the archive.
        """
        handle = self._open
        if handle is None:
            return None

        with handle() as cfile:
            try:
                return cfile.read(fname)
            except TypeError:
                return None
            except rarfile.RarCannotExec:
                print ("Unable to find RAR.  Please Install RAR.")
                return None

    def extract_mem_file64(self, fname):
        """
        Extract filename out of the archive, and return it as a blob.

        inputs - filename to extract
        returns - blob from the archive.
        """
        translate = {'JPG' : 'JPEG',
                     'JPEG' : 'JPEG',
                     'PNG' : 'PNG',
                     'GIF' : 'GIF',
                     'BMP' : 'BMP',
                     'EPS' : 'EPS',
                     'MSP' : 'MSP',
                     'PCX' : 'PCX',
                     'PPM' : 'PPM',
                     'TIF' : 'TIF',
                     'TIFF' : 'TIF'}

        handle = self._open
        if handle is None:
            return None
        fileext = os.path.splitext(fname.lower())[1][1:]

        with handle() as cfile:
            data = "data:image/%s;base64," % translate[fileext.upper()].lower()
            try:
                data += base64.b64encode(cfile.read(fname))
                return data
            except TypeError:
                print ("Type error")
                return None
            except rarfile.RarCannotExec:
                print ("Unable to find RAR.  Please Install RAR.")
                return None

signatures = {'\x50\x4b\x03\x04':(['zip', 'cbz'],
                                  'compressed/zip',
                                  zipfile.ZipFile),
              '\x52\x61\x72\x21':(['rar', 'cbr'],
                                  'application/x-rar-compressed',
                                  rarfile.RarFile)}

sign_byte_count = 4

# factory function to create a suitable instance for accessing files
def id_cfile_by_sig(fname):
    """
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

Example:

filename='test.zip'
archive_file = archives2.id_cfile_by_sig(filename)
archive_file.get_listings()
print archive_file.listings
print filename, 'is a', cf.mime_type, 'file'
    """
    if os.path.isfile(fname):
        with open(fname, 'rb') as cfile:
            start_of_file = cfile.read(sign_byte_count)
            cfile.seek(0)
            if start_of_file in signatures:
                identified = CompressedFile(fname)
                identified.extensions = signatures[start_of_file][0]
                identified.mime_type = signatures[start_of_file][1]
                identified.handler = signatures[start_of_file][2]
                return identified
    return None


if __name__ == "__main__":
    filename = 'test.zip'
    cf = id_cfile_by_sig(filename)
    if cf is not None:
        print(filename, 'is a', cf.mime_type, 'file')
