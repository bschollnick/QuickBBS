"""
Cached file exists

Quick and Fast execution to avoid hitting hard drive to check if a file exists.

from cached_exists import *
test = r"/Volumes/4TB_Drive/sorted_downloads/Python/gallery-dl/exhentai/327687 Ah! My Goddess HQ Gallery"
cache = cached_exist()
cache.read_path(test)
cache.scanned_paths
cache.sha256_paths
cache.read_path(test, sha=True)
cache.scanned_paths
cache.sha256_paths

from cached_exists import *
test = r"/Volumes/4TB_Drive/sorted_downloads/Python/gallery-dl/exhentai/327687 Ah! My Goddess HQ Gallery"
test_file = test+r"/327687_0285_d2e8ec3f4d_giga_animehq_256.jpg"
cache = cached_exist()
cache.read_path(test, sha=True)
cache.sha256_paths

from hashlib import sha256
sha = sha256()
sha.update("hello")
print (sha.digest(), sha.hexdigest())

def get_digest(file_path):
    h = hashlib.sha256()
    with open(file_path, 'rb') as file:
        while True:
            # Reading is buffered, so we can read smaller chunks.
            chunk = file.read(h.block_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def     generate_sha256(filename, hexdigest=False):
    sha = sha256()
    with open(filename, 'rb') as sha_file:
        while True:
            # Reading is buffered, so we can read smaller chunks.
            chunk = sha_file.read(sha.block_size)
            if not chunk:
                break
            sha.update(chunk)
    if hexdigest:
        return sha.hexdigest()
    else:
        return sha.digest()


"""
import os
import os.path
from hashlib import md5
from hashlib import sha256, sha224
from hashlib import sha512
import os

SCANNED_PATHS = {}
VERIFY_COUNT = 0
RESET_COUNT = 10000 # ( 10K )

class cached_exist():
    def     __init__(self, reset_count=RESET_COUNT):
        self.scanned_paths = {}
        self.sha_paths = {}
        self.verify_count = 0
        self.reset_count = reset_count
        self.global_count = 0
#        self.blocksize = int(65536/2)


    def     clear_scanned_paths(self):
        self.scanned_paths = {}
        self.sha_paths = {}
        self.global_count = 0

    def     clear_path(self, path_to_clear):
        dirpath = os.path.normpath(path_to_clear.lower().strip())
        try:
            del self.scanned_paths[dirpath]
        except KeyError:
            pass

        try:
            del self.sha_paths[dirpath]
        except KeyError:
            pass

    def     set_reset_count(self, reset_count=RESET_COUNT):
        self.reset_count = RESET_COUNT

    def     generate_sha256(self, filename, hexdigest=False):
        sha = sha256()
        with open(filename, 'rb') as sha_file:
            while True:
                # Reading is buffered, so we can read smaller chunks.
                chunk = sha_file.read(sha.block_size)
                if not chunk:
                    break
                sha.update(chunk)
        if hexdigest:
            return sha.hexdigest()
        else:
            return sha.digest()

    def     generate_sha224(self, filename, hexdigest=False):
        sha = sha224()
        with open(filename, 'rb') as sha_file:
            while True:
                # Reading is buffered, so we can read smaller chunks.
                chunk = sha_file.read(sha.block_size)
                if not chunk:
                    break
                sha.update(chunk)
        if hexdigest:
            return sha.hexdigest()
        else:
            return sha.digest()


    def     read_path(self, dirpath, sha=False):
        """
            Read a path using SCANDIR (https://pypi.org/project/scandir/).

            Args:

                dirpath (string): The directory path to read

            Returns:

                boolean: True successful read the directory,
                         False if unable to read

            Using the scandir.walk(dirpath).next() functionality to dump the listing
                into a set, so that we do not have to iterate through the generator
                making it ourselves.

            .. code-block:

                >>> read_path(r".")
                True
                >>> read_path(r"c:\\turnup\\test.me")
                False
        """
        try:
            dirpath = os.path.normpath(dirpath.lower().strip())
            directory_data = os.scandir(dirpath)
            self.scanned_paths[dirpath] = {}
            self.sha_paths[dirpath] = {}
            for entry in directory_data:
                if entry.is_file():
                    self.scanned_paths[dirpath][entry.name.lower()] =\
                        entry.stat().st_size
                    if sha:
                        sha = self.generate_sha224(os.path.join(dirpath,
                                                                entry), hexdigest=True)
                        self.sha_paths[dirpath][sha] = entry.stat().st_size
#        except (StopIteration, WindowsError):
        except StopIteration:
            # Most likely a bad path, since we can't iterate through the contents
            # Fail silently, and return False
            return False
        except FileNotFoundError:
            return False
        return True

    def file_exist(self, filename, rtn_size=False, sha_hd=None, sha=False):
        """
            Does the file exist?

            The filename should be a path included (eg .\\test.txt, or fqpn) filename.
            The filename is split into directory path (dirpath), and filename.

            The dirpath is used to locate the directory contents in the dictionary
            (Associated hashmap).  If it is not located/available, then it will be
            scanned via read_path.

            Once the directory is available, a simple lookup is performed on the
            list containing the directory & filenames that are contained in the
            directory.

            Args:

                filename (string): The path enabled filename, eg. .\\test.txt,
                    c:\\users\\bschollnick\\test.txt.
                    The filename is split (os.path.split) into the directory,
                    and the filename.

                rtn_size (boolean): If True, and the file exists, return filesize

            Returns:

                Boolean: True if the file exists, or false if it doesn't.
                Integer: If rtn_size is true, an existing file will return
                    an integer


            .. code-block:
                # Boolean Tests
                >>> file_exist(r"test_samples\\monty.csv")
                True
                >>> file_exist(r"test_samples\\small.csv")
                True
                >>> file_exist(r"test_samples\\monty_lives_here.csv")
                False
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt")
                False

                # File size Tests
                >>> file_exist(r"test_samples\\monty.csv", rtn_size=True)
                76
                >>> file_exist(r"test_samples\\small.csv", rtn_size=True)
                44
                >>> file_exist(r"test_samples\\monty_lives_here.csv", rtn_size=True)
                False
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
                False

        """
        self.verify_count += 1
        if self.verify_count > self.reset_count:
            clear_scanned_paths()

        dirpath, filename = os.path.split(filename.lower().strip())
        dirpath = os.path.normpath(dirpath)
        if dirpath not in self.scanned_paths:
            self.read_path(dirpath, sha=sha)

        try:
            if sha:
                if sha_hd == None:
                    sha_hd = self.generate_sha224(os.path.join(dirpath, filename), hexdigest=True)
                if not rtn_size:
                    return sha_hd in self.sha_paths[dirpath]
                else:
                    return self.sha_paths[dirpath][sha_hd]
            else:
                if not rtn_size:
                    return filename in self.scanned_paths[dirpath]
                return self.scanned_paths[dirpath][filename]
        except KeyError:
            return False


    def search_file_exist(self, filename):
        """
        Does the file exist?

        The filename should be a path included (eg .\\test.txt, or fqpn) filename.
        The filename is split into directory path (dirpath), and filename.

        The dirpath is used to locate the directory contents in the dictionary
        (Associated hashmap).  If it is not located/available, then it will be
        scanned via read_path.

        Once the directory is available, a simple lookup is performed on the
        list containing the directory & filenames that are contained in the
        directory.

        Args:

            filename (string): filename, eg. test.txt, **NOT FQFN**
                test.txt **NOT** c:\\users\\bschollnick\\test.txt

        Returns:
            Boolean: True if the file exists, or false if it doesn't.

        *NOTE*: This only checks for the prescence of the file, it will not scan
         the drive for the file.  So *ENSURE* that the folder you want to search
         has already been read_path'd.

        This is the equivalent of the which command.  eg. Which directory is this
         file exist in?

        .. code-block:: python
        >>> clear_scanned_paths()
        >>> search_exist("monty.csv")
        (False, None)
        >>> read_path("test_samples")
        True
        >>> search_exist("monty.csv")
        (True, 'test_samples')
        """
        filename = filename.lower().strip()
        for dirpath in self.scanned_path:
             if file_exist(os.path.join(dirpath, filename)):
                return (True, dirpath)
        return (False, None)

    def search_sha256_exist(self, sha256hd=None):
        """
        Does the file exist?

        The filename should be a path included (eg .\\test.txt, or fqpn) filename.
        The filename is split into directory path (dirpath), and filename.

        The dirpath is used to locate the directory contents in the dictionary
        (Associated hashmap).  If it is not located/available, then it will be
        scanned via read_path.

        Once the directory is available, a simple lookup is performed on the
        list containing the directory & filenames that are contained in the
        directory.

        Args:

            filename (string): filename, eg. test.txt, **NOT FQFN**
                test.txt **NOT** c:\\users\\bschollnick\\test.txt

        Returns:
            Boolean: True if the file exists, or false if it doesn't.

        *NOTE*: This only checks for the prescence of the file, it will not scan
         the drive for the file.  So *ENSURE* that the folder you want to search
         has already been read_path'd.

        This is the equivalent of the which command.  eg. Which directory is this
         file exist in?

        .. code-block:: python
        >>> clear_scanned_paths()
        >>> search_exist("monty.csv")
        (False, None)
        >>> read_path("test_samples")
        True
        >>> search_exist("monty.csv")
        (True, 'test_samples')
        """
        filename = filename.lower().strip()
        for dirpath in self.scanned_path:
             if file_exist(os.path.join(dirpath, filename)):
                return (True, dirpath)
        return (False, None)










def clear_scanned_paths():
    """
    Clear the scanned path datastore
    """
    global SCANNED_PATHS
    SCANNED_PATHS = {}

def read_path(dirpath):
    """
        Read a path using SCANDIR (https://pypi.org/project/scandir/).

        Args:

            dirpath (string): The directory path to read

        Returns:

            boolean: True successful read the directory,
                     False if unable to read

        Using the scandir.walk(dirpath).next() functionality to dump the listing
            into a set, so that we do not have to iterate through the generator
            making it ourselves.

        .. code-block:

            >>> read_path(r".")
            True
            >>> read_path(r"c:\\turnup\\test.me")
            False
    """
    try:
        dirpath = os.path.normpath(dirpath.lower().strip())
        directory_data = os.scandir(dirpath)
        SCANNED_PATHS[dirpath] = {}
        for entry in directory_data:
            if entry.is_file:
                SCANNED_PATHS[dirpath][entry.name.lower()] =\
                    entry.stat().st_size
        #SCANNED_PATHS[dirpath] = set(x.lower() for x in directory_data)
    except (StopIteration, WindowsError):
        # Most likely a bad path, since we can't iterate through the contents
        # Fail silently, and return False
        return False

    return True

def file_exist(filename, rtn_size=False):
    """
        Does the file exist?

        The filename should be a path included (eg .\\test.txt, or fqpn) filename.
        The filename is split into directory path (dirpath), and filename.

        The dirpath is used to locate the directory contents in the dictionary
        (Associated hashmap).  If it is not located/available, then it will be
        scanned via read_path.

        Once the directory is available, a simple lookup is performed on the
        list containing the directory & filenames that are contained in the
        directory.

        Args:

            filename (string): The path enabled filename, eg. .\\test.txt,
                c:\\users\\bschollnick\\test.txt.
                The filename is split (os.path.split) into the directory,
                and the filename.

            rtn_size (boolean): If True, and the file exists, return filesize

        Returns:

            Boolean: True if the file exists, or false if it doesn't.
            Integer: If rtn_size is true, an existing file will return
                an integer


        .. code-block:
            # Boolean Tests
            >>> file_exist(r"test_samples\\monty.csv")
            True
            >>> file_exist(r"test_samples\\small.csv")
            True
            >>> file_exist(r"test_samples\\monty_lives_here.csv")
            False
            >>> file_exist(r"test_samples\\I_DONT-EXIST.txt")
            False

            # File size Tests
            >>> file_exist(r"test_samples\\monty.csv", rtn_size=True)
            76
            >>> file_exist(r"test_samples\\small.csv", rtn_size=True)
            44
            >>> file_exist(r"test_samples\\monty_lives_here.csv", rtn_size=True)
            False
            >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
            False

    """
    global VERIFY_COUNT
    global RESET_COUNT
    VERIFY_COUNT += 1
    if VERIFY_COUNT > RESET_COUNT:
        clear_scanned_paths()

    dirpath, filename = os.path.split(filename.lower().strip())
    dirpath = os.path.normpath(dirpath)
    if dirpath not in SCANNED_PATHS:
#        print "\t* Caching: ", dirpath
        read_path(dirpath)
    try:
        if not rtn_size:
            return filename in SCANNED_PATHS[dirpath]
        return SCANNED_PATHS[dirpath][filename]
    except KeyError:
        return False

def search_exist(filename):
    """
    Does the file exist?

    The filename should be a path included (eg .\\test.txt, or fqpn) filename.
    The filename is split into directory path (dirpath), and filename.

    The dirpath is used to locate the directory contents in the dictionary
    (Associated hashmap).  If it is not located/available, then it will be
    scanned via read_path.

    Once the directory is available, a simple lookup is performed on the
    list containing the directory & filenames that are contained in the
    directory.

    Args:

        filename (string): filename, eg. test.txt, **NOT FQFN**
            test.txt **NOT** c:\\users\\bschollnick\\test.txt

    Returns:
        Boolean: True if the file exists, or false if it doesn't.

    *NOTE*: This only checks for the prescence of the file, it will not scan
     the drive for the file.  So *ENSURE* that the folder you want to search
     has already been read_path'd.

    This is the equivalent of the which command.  eg. Which directory is this
     file exist in?

    .. code-block:: python
    >>> clear_scanned_paths()
    >>> search_exist("monty.csv")
    (False, None)
    >>> read_path("test_samples")
    True
    >>> search_exist("monty.csv")
    (True, 'test_samples')
    """
    filename = filename.lower().strip()
    for dirpath in SCANNED_PATHS:
        #print (os.path.join(dirpath, filename))
        if file_exist(os.path.join(dirpath, filename)):
            return (True, dirpath)
    return (False, None)


if __name__ == "__main__":
    pass
