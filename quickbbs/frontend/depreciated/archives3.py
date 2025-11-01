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

More File signatures are available here:

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

import base64
import os
import os.path
import zipfile
from operator import itemgetter

import rarfile


class NotInitializedYet(Exception):
    """
    General Purpose Exception Stub.

    Called if self.handler in CompressedFile has not been
    assigned, yet, the code has been asked to process (eg Open) the
    compressed file.
    """


class CompressedFile:
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

    def __init__(self, fname: str) -> None:
        """
        Initialize CompressedFile object.

        Args:
            fname: The fully qualified filename to the archive file

        Returns:
            None
        """
        self.filename = os.path.realpath(fname)
        self.listings = []

    @classmethod
    def is_signature(cls, data: bytes) -> bool:
        """
        Check if data matches the archive signature.

        Args:
            data: The signature bytes from the archive file header

        Returns:
            True if signature matches, False otherwise
        """
        return data.startswith(cls.signature)

    def _open(self):
        """
        Open the archive file using the configured handler.

        Returns:
            Archive file handler object (ZipFile, RarFile, etc.) or None on error

        Raises:
            NotInitializedYet: If handler is not set
        """
        if self.handler is not None:
            # pylint: disable=E1102
            try:
                return self.handler(self.filename, "r")
            except rarfile.NeedFirstVolume:
                return None
            except rarfile.TypeError:
                return None
        # pylint: enable=E1102
        else:
            raise NotInitializedYet

    def return_mime(self) -> str:
        """
        Return the stored mimetype for the archive file.

        Returns:
            MIME type string of the archive

        Raises:
            NotInitializedYet: If mime_type is not set
        """
        if self.mime_type is not None:
            return self.mime_type
        raise NotInitializedYet

    def get_listings(self) -> bool:
        """
        Load the file listings from the archive into self.listings.

        Returns:
            True if successful, False if archive cannot be opened
        """
        self.listings = []
        handle = self._open
        if handle() is None:
            return False

        with handle() as cfile:
            count = 0
            for offset, afn in enumerate(cfile.namelist(), start=0):
                if not (afn.startswith("__MACOSX") or os.path.split(afn)[1] == ""):
                    self.listings.append((afn, offset, count))
                    count += 1
            sorted(self.listings, key=itemgetter(0))
            return True

    def extract_mem_file(self, fname: str) -> bytes | None:
        """
        Extract file from archive and return as bytes.

        Args:
            fname: Filename to extract from archive

        Returns:
            File contents as bytes, or None on error
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
                print("Unable to find RAR.  Please Install RAR.")
                return None

    def extract_mem_file64(self, fname: str) -> str | None:
        """
        Extract file from archive and return as base64-encoded data URI.

        Args:
            fname: Filename to extract from archive

        Returns:
            Data URI string with base64-encoded image, or None on error
        """
        translate = {
            "JPG": "JPEG",
            "JPEG": "JPEG",
            "PNG": "PNG",
            "GIF": "GIF",
            "BMP": "BMP",
            "EPS": "EPS",
            "MSP": "MSP",
            "PCX": "PCX",
            "PPM": "PPM",
            "TIF": "TIF",
            "TIFF": "TIF",
        }

        handle = self._open
        if handle is None:
            return None
        fileext = os.path.splitext(fname.lower())[1][1:]
        if fileext.upper() not in translate:
            return None

        with handle() as cfile:
            #
            try:
                data = f"data:image/{translate[fileext.upper()].lower()};base64,{base64.b64encode(cfile.read(fname))}"
                return data
            except TypeError:
                print("Type error")
                return None
            except rarfile.RarCannotExec:
                print("Unable to find RAR.  Please Install RAR.")
                return None


signatures = {
    "\x50\x4b\x03\x04": (
        ["zip", "cbz", "pk3", "pk4"],
        "compressed/zip",
        zipfile.ZipFile,
    ),
    "\x50\x4b\x05\x06": (
        ["zip", "cbz", "pk3", "pk4"],
        "compressed/zip",
        zipfile.ZipFile,
    ),
    "\x50\x4b\x07\x08": (
        ["zip", "cbz", "pk3", "pk4"],
        "compressed/zip",
        zipfile.ZipFile,
    ),
    b"PK\x03\x04": (["zip", "cbz", "pk3", "pk4"], "compressed/zip", zipfile.ZipFile),
    "\x52\x61\x72\x21": (
        ["rar", "cbr"],
        "application/x-rar-compressed",
        rarfile.RarFile,
    ),
    b"Rar!": (["rar", "cbr"], "application/x-rar-compressed", rarfile.RarFile),
    b"\x1f\\9D": (["lzh"], "tar lzh compression", None),
    b"\x1f\\A0": (["lzh"], "tar lzh compression", None),
    b"\x42\x5a\x68": (["bzip", "bz"], "bzip compression", None),
    b"\x37\x7a\xbc\xaf\x27\x1c": (["7z"], "7zip compression", None),
    b"\x1f\x8b": (["gz"], "gzip compression", None),
}

sign_byte_count = 4


# factory function to create a suitable instance for accessing files
def id_cfile_by_sig(fname: str) -> CompressedFile | None:
    """
    Identify and initialize a compressed file by its signature.

    Reads the file header to identify the archive type by signature,
    then returns a configured CompressedFile instance.

    Args:
        fname: Fully qualified pathname to the archive file

    Returns:
        Initialized CompressedFile object configured for the detected
        archive type, or None if file doesn't exist or is unrecognized

    Example:
        >>> archive_file = id_cfile_by_sig('test.zip')
        >>> archive_file.get_listings()
        >>> print(archive_file.listings)
        >>> print(f"{fname} is a {archive_file.mime_type} file")
    """
    if os.path.isfile(fname):
        with open(fname, "rb") as cfile:
            start_of_file = cfile.read(sign_byte_count)
            cfile.seek(0)
            if start_of_file in signatures:
                identified = CompressedFile(fname)
                identified.extensions = signatures[start_of_file][0]
                identified.mime_type = signatures[start_of_file][1]
                identified.handler = signatures[start_of_file][2]
                return identified
            # else:
            #    print("Unidentified: ", start_of_file)
    return None


if __name__ == "__main__":
    filename = "test.rar"
    cf = id_cfile_by_sig(filename)
    if cf is not None:
        print(filename, "is a", cf.mime_type, "file")
