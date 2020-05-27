"""
Cached file exists

Quick and Fast execution to avoid hitting hard drive to check if a file exists.

"""
import os
import os.path
#from hashlib import md5
from hashlib import sha224, sha256, sha512
import time

#import operator
from pathvalidate import is_valid_filename, sanitize_filename

SCANNED_PATHS = {}
VERIFY_COUNT = 0
RESET_COUNT = 10000  # ( 10K )

class cached_exist():
    """
        Cached Exist functionality - Caching engine to detect by filename,
            and SHA224.   Can use last modification and file / dir count to
            identify cache invalidation.

        Args:

            reset_count (integer): The number of queries to allow before
                forcing a cache invalidation.

            use_modify (boolean): Store & Use the last modified date of
                the contents of the directory for cache invalidation.

            use_shas (boolean): Store & Use SHA224 for the files that
                are scanned.

            FilesOnly (boolean): Ignore directories

            use_extended (boolean): Store direntries, and break out
                directory & files counts.

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
            >>> file_exist(r"test_samples\\monty_lives_here.csv",
                            rtn_size=True)
            False
            >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
            False

    """
    def __init__(self, reset_count=RESET_COUNT, use_modify=False,
                 use_shas=False, FilesOnly=True, use_extended=False,
                 use_filtering=False):
        self.scanned_paths = {}
        self.sha_paths = {}
        self.last_mods = {}
        self.extended = {}
        self.use_extended = use_extended
        self.use_modify = use_modify
        self.use_shas = use_shas
        self.verify_count = 0
        self.reset_count = reset_count
        self.global_count = 0
        self.sanitize_plat = "Windows"
        self.FilesOnly = FilesOnly
        self.AcceptableExtensions = []
        self.IgnoreExtensions = []
        self.IgnoreDotFiles = False
        self.use_filters = use_filtering
        self.MAX_SHA_SIZE = 1024*1024*10
        self.last_mods["lastScan"] = 0
        self.last_mods["scanInterval"] = 90 # 60 seconds

    def sanitize_filenames(self, dirpath, allow_rename=False):
        """
            sanitize_filenames - sanitize the filename to windows standards.
                optionally force the rename of the files.

            Args:

                dirpath (string): The path to the files to be sanitized

                allow_rename (boolean): Allow the renaming of the files to
                    conform to a self.sanitize_plat (default-Windows)
                    platform

            .. code-block:
                # Boolean Tests
        """

        refresh = False
        dirpath = os.path.normpath(dirpath.title().strip())
        for filename in self.scanned_paths[dirpath]:
            if not is_valid_filename(filename, platform=self.sanitize_plat):
                new_filename = sanitize_filename(filename,
                                                 platform=self.sanitize_plat)
                print("Invalid Filename: %s --> %s" % (filename, new_filename))
                if allow_rename:
                    refresh = True
                    os.rename(os.path.join(dirpath, filename),
                              os.path.join(dirpath, new_filename))
        if refresh:
            self.clear_path(dirpath)
            self.read_path(dirpath)

    def clear_scanned_paths(self):
        """
            clear_scanned_paths - remove all cached paths

            .. code-block:
                # Boolean Tests
        """
        self.scanned_paths = {}
        self.sha_paths = {}
        self.last_mods = {}
        self.last_mods["lastScan"] = 0
        self.last_mods["scanInterval"] = 60*100 # 60 * 1000 ms = 60 seconds
        self.extended = {}
        self.global_count = 0
        self.verify_count = 0
        self.reset_count = 0

    def clear_path(self, path_to_clear):
        """
            clear_path - remove a specific directory from the cached entries

            Args:

                path_to_clear (string): the FQPN of the path to remove


            .. code-block:
                # Boolean Tests
        """
        dirpath = os.path.normpath(path_to_clear.title().strip())
        try:
            del self.scanned_paths[dirpath]
            del self.sha_paths[dirpath]
            del self.last_mods[dirpath]
            self.last_mods["lastScan"] = 0
            self.last_mods["scanInterval"] = 60*100 # 60 * 1000 ms = 60 seconds
            del self.extended[dirpath]
        except KeyError:
            pass

    def return_fileCount(self, dirpath):
        """
            return the count of files in the cached directory path

            Args:

                dirpath (string): The path to the files to be sanitized


             Returns:

                Integer: the # of files contained.  If empty or
                    non-existent, returns 0


            .. code-block:
                # Boolean Tests
            """
        if dirpath in self.scanned_paths:
            return len(self.scanned_paths[dirpath])
        return 0

    def return_extended_count(self, dirpath):
        """

            Args:

                dirpath (string): The path to the files to be sanitized


             Returns:

                Tuple: A Tuple of Integers.  (fileCount, dirCount)
                    fileCount is the # of files in the directory, and
                    dirCount is the # of child directories in the directory.



            .. code-block:
                # Boolean Tests

        """
        dirpath = os.path.normpath(dirpath.title().strip())
        fileCount = 0
        dirCount = 0
        for x in self.extended[dirpath]:
            fileCount += self.extended[dirpath][x].is_file()
            dirCount += self.extended[dirpath][x].is_dir()
        return (fileCount, dirCount)

    def return_newest(self, dirpath):
        dirpath = os.path.normpath(dirpath).title().strip()
        newest = ('', 0)
        olddirpath, oldnewest, lastScan = self.last_mods[dirpath]
#        print( time.time(), time.time() - lastScan, lastScan, self.last_mods["scanInterval"])
        if time.time() - lastScan > self.last_mods["scanInterval"]:
#            print("Calculating newest")
            for entry in os.scandir(dirpath):
                if entry.stat().st_mtime > newest[1]:
                    newest = (entry.name.title(), entry.stat().st_mtime, time.time())
        else:
#            print("Cached newest")
            newest = self.last_mods[dirpath]
        return newest


    def check_count(self, dirpath):
        """

            Args:

                dirpath (string): The path to the files to be sanitized


             Returns:

                Integer: Returns # of files in the directory, returning 0
                    if the path has not been scanned (or contains no files).
                    Returns None if a FileNotFoundError would have been
                    raised.


            .. code-block:
                # Boolean Tests
                >>> file_exist(r"test_samples\\monty.csv")
                True
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt")
                False

                # File size Tests
                >>> file_exist(r"test_samples\\monty.csv", rtn_size=True)
                76
                >>> file_exist(r"test_samples\\monty_lives_here.csv",
                                rtn_size=True)
                False
        """
        #
        #   update with processFile support
        #
        fs_filecount = 0
        dirpath = os.path.normpath(dirpath.title().strip())
        if dirpath not in self.scanned_paths:
            return 0

        try:
            for x in list(os.scandir(dirpath)):
                if self.processFile(x):
                    if self.FilesOnly and x.is_dir():
                        pass
                    else:
                        fs_filecount += 1
        except FileNotFoundError:
            return None
        except StopIteration:
            return None

            # The count of files in the dirpath directory
        return self.return_fileCount(dirpath) == fs_filecount

    def check_lastmod(self, dirpath):
        """
            Args:

                dirpath (string): The path to the files


             Returns:

                Boolean: True if the last_mods[dirpath] value for the directory
                    matches the current newest last modified value in the
                    directory.

                    Returns False, if the files do not match last modified date.


            .. code-block:
                # Boolean Tests
        """
        dirpath = os.path.normpath(dirpath.title().strip())
        # Get the currently defined lastmod for the latest file in memory
        if dirpath not in self.last_mods:
            return False

        #if (self.return_fileCount(dirpath) == 0 or
        if self.last_mods[dirpath] == ('', 0, 0):
            return False

        newest = self.return_newest(dirpath)
        return self.last_mods[dirpath] == newest


    def set_reset_count(self, reset_count=RESET_COUNT):
        """
            Args:

                reset_count (integer): The number of queries to allow before
                    forcing a cache invalidation.

            .. code-block:
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
                False
        """
        self.reset_count = reset_count

    def generate_sha256(self, filename, hexdigest=False):
        """
            Args:

                filename (string): The FQPN of the file to generate a
                    sha256 from

                hexdigest (Boolean): Return as a hexdigest; False - standard
                    digest

            Returns:

                String: Either a Hexdigest or standard digest of sha256

            .. code-block:
                # File size Tests
                >>> file_exist(r"test_samples\\monty.csv", rtn_size=True)
                76
                >>> file_exist(r"test_samples\\small.csv", rtn_size=True)
                44
                >>> file_exist(r"test_samples\\monty_lives_here.csv",
                                rtn_size=True)
                False
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
                False
        """
        sha = sha256()
        if os.path.isfile(filename):
            with open(filename, 'rb') as sha_file:
                while True:
                    # Reading is buffered, so we can read smaller chunks.
                    chunk = sha_file.read(sha.block_size)
                    if not chunk:
                        break
                    sha.update(chunk)
            if hexdigest:
                return sha.hexdigest()
        return sha.digest()

    def generate_sha224(self, filename, hexdigest=False):
        """
            Args:

                filename (string): The FQPN of the file to generate a
                    sha256 from

                hexdigest (Boolean): Return as a hexdigest; False - standard
                    digest

            Returns:

                String: Either a Hexdigest or standard digest of sha256

            .. code-block:
                # File size Tests
                >>> file_exist(r"test_samples\\monty.csv", rtn_size=True)
                76
                >>> file_exist(r"test_samples\\small.csv", rtn_size=True)
                44
                >>> file_exist(r"test_samples\\monty_lives_here.csv",
                                rtn_size=True)
                False
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
                False
        """
        sha = sha224()
        if os.path.isfile(filename):
            with open(filename, 'rb') as sha_file:
                while True:
                    # Reading is buffered, so we can read smaller chunks.
                    chunk = sha_file.read(sha.block_size)
                    if not chunk:
                        break
                    sha.update(chunk)
            if hexdigest:
                return sha.hexdigest()
        return sha.digest()

    def processFile(self, dentry):
        """
            Args:

                filename (string): The filename of the file currently being
                    processed


             Returns:

                Boolean: True, if the file should be processed, False if not


            .. code-block:
                # Boolean Tests
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
                False
        """
        if not self.use_filters:
            return True

        fext = os.path.splitext(dentry.name)[1]
        if self.IgnoreDotFiles and dentry.name.startswith("."):
            return False

        if not self.FilesOnly:
            if dentry.is_dir():
                return True

        if fext.lower() in self.AcceptableExtensions:
            return True
        return False

    def addFileDirEntry(self, fileentry, sha_hd):
        """
            sanitize_filenames - sanitize the filename to windows standards.
                optionally force the rename of the files.

            Args:

                fileentry (DirEntry): The DirEntry of the file to be added

                sha_hd (boolean): The Sha224 HexDigest of the file in question

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
                >>> file_exist(r"test_samples\\monty_lives_here.csv",
                                rtn_size=True)
                False
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
                False
        """
        dirpath = os.path.normpath(os.path.split(
            fileentry.path.strip())[0]).title()
        filename = fileentry.name.strip().title()
        if dirpath not in self.scanned_paths:
            self.scanned_paths[dirpath] = {}

        if not self.use_modify:
            self.scanned_paths[dirpath][filename] = fileentry.stat().st_size
        else:
            self.scanned_paths[dirpath][filename] = fileentry.stat().st_mtime

        if dirpath not in self.extended and self.use_extended:
            self.use_extended[dirpath] = {}
        if self.use_extended:
            self.extended[dirpath][filename] = fileentry

        if dirpath not in self.sha_paths and self.use_shas:
            self.sha_paths[dirpath] = {}
        if self.use_shas:
            self.sha_paths[dirpath][sha_hd] = fileentry.stat().st_size

    def addFile(self, dirpath, filename, sha_hd, filesize, mtime):
        """
            sanitize_filenames - sanitize the filename to windows standards.
                optionally force the rename of the files.

            Args:

                filename (string): The number of queries to allow before
                    forcing a cache invalidation.

                dirpath (string): The directory path of the file to be added

                sha_hd (string): hexdigest

                filesize (integer) : filesize

                mtime (integer) : modification time

            Raises:

                NotImplementedError : When used in use_modify mode.  DirEntries
                    can not be created programmatically, and thus can not be
                    passed into addFile.  (*EG* addFile can't be used when
                    use_modify mode is on.)

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
                >>> file_exist(r"test_samples\\monty_lives_here.csv",
                                rtn_size=True)
                False
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
                False
        """
        dirpath = dirpath.title().strip()
        filename = filename.strip().title()

        if dirpath not in self.scanned_paths:
            self.scanned_paths[dirpath] = {}

        if not self.use_modify:
            self.scanned_paths[dirpath][filename] = filesize
        else:
            self.scanned_paths[dirpath][filename] = mtime

        if self.use_extended:
            raise NotImplementedError
            # $self.extended[dirpath][filename] = None

        if dirpath not in self.sha_paths and self.use_shas:
            self.sha_paths[dirpath] = {}
        if self.use_shas:
            self.sha_paths[dirpath][sha_hd] = filesize

    def read_path(self, dirpath):
        """
            Read a path using SCANDIR (https://pypi.org/project/scandir/).

            Args:

                dirpath (string): The directory path to read

            Returns:

                boolean: True successful read the directory,
                         False if unable to read

            Using the scandir.walk(dirpath).next() functionality to
            dump the listing into a set, so that we do not have to iterate
            through the generator making it ourselves.

            .. code-block:

                >>> read_path(r".")
                True
                >>> read_path(r"c:\\turnup\\test.me")
                False
        """
        dirpath = os.path.normpath(dirpath.title().strip())
        if (self.check_count(dirpath) == True and
                self.check_lastmod(dirpath) == True):
            # Skip, no need for refresh
            return True

        try:
            self.scanned_paths[dirpath] = {}
            self.sha_paths[dirpath] = {}
            self.extended[dirpath] = {}
            self.last_mods[dirpath] = ('', 0, 0)
            directory_data = os.scandir(dirpath)
            for entry in directory_data:
#                print(entry.name, self.processFile(entry))
                if self.processFile(entry):
                    sha = None
                    if self.use_shas:
                        if self.MAX_SHA_SIZE not in [None, 0]:
                            if self.MAX_SHA_SIZE > entry.stat().st_size:
                                sha = self.generate_sha224(os.path.join(dirpath,
                                                                        entry),
                                                           hexdigest=True)
                        else:
                            sha = self.generate_sha224(os.path.join(dirpath,
                                                                    entry),
                                                       hexdigest=True)

                    if self.use_modify:
                        if entry.stat().st_mtime > self.last_mods[dirpath][1]:
                            self.last_mods[dirpath] = (entry.name.title(),
                                                       entry.stat().st_mtime, time.time())

                    self.addFileDirEntry(entry, sha)

        except StopIteration:
            #print("StopITeration")
            # Most likely a bad path, since we can't iterate through
            # the contents Fail silently, and return False
            return False
        except FileNotFoundError:
            # the dirpath does not exist.
            #print("Target Directory does not exist ", dirpath)
            #sys.exit()
            return False
        return True

    def fexistName(self, filename, rtn_size=False):
        """
            Does the file exist?

            The filename should be a path included (eg .\\test.txt, or fqpn)
            filename.  The filename is split into directory path (dirpath),
            and filename.

            The dirpath is used to locate the directory contents in the
            dictionary (Associated hashmap).  If it is not located/available,
            then it will be scanned via read_path.

            Once the directory is available, a simple lookup is performed on the
            list containing the directory & filenames that are contained in the
            directory.

            Args:

                filename (string): The path enabled filename, eg. .\\test.txt,
                    c:\\users\\bschollnick\\test.txt.
                    The filename is split (os.path.split) into the directory,
                    and the filename.

                rtn_size (boolean): If True, and the file exists, return
                    filesize

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
                >>> file_exist(r"test_samples\\monty_lives_here.csv",
                                rtn_size=True)
                False
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
                False

        """
        self.verify_count += 1
        if self.verify_count > self.reset_count:
            clear_scanned_paths()

        dirpath, filename = os.path.split(filename.title().strip())
        dirpath = os.path.normpath(dirpath)
        if dirpath not in self.scanned_paths:
            self.read_path(dirpath)

        try:
            if not rtn_size:
                return filename in self.scanned_paths[dirpath]
            return self.scanned_paths[dirpath][filename]
        except KeyError:
            return False

    def fexistSha(self, filename, rtn_size=False, sha_hd=None):
        """
            Does the file exist?

            The filename should be a path included (eg .\\test.txt, or fqpn)
            filename. The filename is split into directory path (dirpath), and
            filename.

            The dirpath is used to locate the directory contents in the
            dictionary (Associated hashmap).  If it is not located/available,
            then it will be
            scanned via read_path.

            Once the directory is available, a simple lookup is performed on the
            list containing the directory & filenames that are contained in the
            directory.

            Args:

                filename (string): The path enabled filename, eg. .\\test.txt,
                    c:\\users\\bschollnick\\test.txt.
                    The filename is split (os.path.split) into the directory,
                    and the filename.

                rtn_size (boolean): If True, and the file exists, return
                    filesize

                sha_hd (string): sha hexdigest

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
                >>> file_exist(r"test_samples\\monty_lives_here.csv",
                               rtn_size=True)
                False
                >>> file_exist(r"test_samples\\I_DONT-EXIST.txt", rtn_size=True)
                False

        """
        self.verify_count += 1
        if self.verify_count > self.reset_count:
            clear_scanned_paths()

        dirpath, filename = os.path.split(filename.title().strip())
        dirpath = os.path.normpath(dirpath)
        if dirpath not in self.scanned_paths:
            self.read_path(dirpath)

        try:
            if self.use_shas:
                if sha_hd == None:
                    sha_hd = self.generate_sha224(
                        os.path.join(dirpath, filename), hexdigest=True)
                if rtn_size:
                    return self.sha_paths[dirpath][sha_hd]
                return sha_hd in self.sha_paths[dirpath]
            if rtn_size:
                return self.scanned_paths[dirpath][filename]
            return filename in self.scanned_paths[dirpath]
        except KeyError:
            return False

    def search_file_exist(self, filename):
        """
        Does the file exist?

        The filename should be a path included (eg .\\test.txt, or fqpn)
        filename. The filename is split into directory path (dirpath), and
        filename.

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

        This is the equivalent of the which command.  eg. Which directory is
        this file exist in?

        .. code-block:: python
        >>> clear_scanned_paths()
        >>> search_exist("monty.csv")
        (False, None)
        >>> read_path("test_samples")
        True
        >>> search_exist("monty.csv")
        (True, 'test_samples')
        """
        filename = filename.title().strip()
        for dirpath in self.scanned_paths:
            if self.fexistName(os.path.join(dirpath, filename)):
                return (True, dirpath)
        return (False, None)

    def search_sha224_exist(self, shaHD=None):
        """
        Does the file exist?

        The filename should be a path included (eg .\\test.txt, or fqpn)
        filename. The filename is split into directory path (dirpath), and
        filename.

        The dirpath is used to locate the directory contents in the dictionary
        (Associated hashmap).  If it is not located/available, then it will be
        scanned via read_path.

        Once the directory is available, a simple lookup is performed on the
        list containing the directory & filenames that are contained in the
        directory.

        Args:

            shaHD (string): Hexdigest


        Returns:
            Tupple: Element 0 - Boolean - True if the file exists,
                        or false if it doesn't.
                    Element 1 - String - Directory file was found in.

        *NOTE*: This only checks for the prescence of the file, it will not scan
         the drive for the file.  So *ENSURE* that the folder you want to search
         has already been read_path'd.

        This is the equivalent of the which command.  eg. Which directory is
        this file exist in?

        .. code-block:: python
        >>> clear_scanned_paths()
        >>> search_exist("monty.csv")
        (False, None)
        >>> read_path("test_samples")
        True
        >>> search_exist("monty.csv")
        (True, 'test_samples')
        """
        for dirpath in self.sha_paths:
            if self.fexistSha(shaHD):
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
        dirpath = os.path.normpath(dirpath.title().strip())
        directory_data = os.scandir(dirpath)
        SCANNED_PATHS[dirpath] = {}
        for entry in directory_data:
            if entry.is_file:
                SCANNED_PATHS[dirpath][entry.name.title()] =\
                    entry.stat().st_size
        #SCANNED_PATHS[dirpath] = set(x.lower() for x in directory_data)
    except (StopIteration, OSError):
        # Most likely a bad path, since we can't iterate through the contents
        # Fail silently, and return False
        return False

    return True


def file_exist(filename, rtn_size=False):
    """
        Does the file exist?

        The filename should be a path included (eg .\\test.txt, or fqpn)
        filename. The filename is split into directory path (dirpath), and
        filename.

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

    dirpath, filename = os.path.split(filename.title().strip())
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
    filename = filename.title().strip()
    for dirpath in SCANNED_PATHS:
        #print (os.path.join(dirpath, filename))
        if file_exist(os.path.join(dirpath, filename)):
            return (True, dirpath)
    return (False, None)


if __name__ == "__main__":
    pass
