"""
Cached file exists

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

"""
import os
import os.path
import time
# from hashlib import md5
from hashlib import sha224, sha256  # , sha512

import imagehash
# import operator
from pathvalidate import (is_valid_filename, sanitize_filename,
                          sanitize_filepath)
from PIL import Image, UnidentifiedImageError

SCANNED_PATHS = {}
VERIFY_COUNT = 0
RESET_COUNT = 10000  # ( 10K )
Image.MAX_IMAGE_PIXELS = None


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
                 use_filtering=False, use_image_hash=False, image_hasher=imagehash.average_hash):
        self.scanned_paths = {}
        self.sha_paths = {}
        self.image_paths = {}
        self.use_image_hashs = False
        self.last_mods = {}
        self.extended = {}
        self.use_extended = use_extended
        self.use_modify = use_modify
        self.use_shas = use_shas
        self.use_image_hash = use_image_hash
        self.verify_count = 0
        self.reset_count = reset_count
        self.global_count = 0
        self.sanitize_plat = "Windows"
        self.FilesOnly = FilesOnly
        self.AcceptableExtensions = []
        self.IgnoreExtensions = []
        self.IgnoreDotFiles = False
        self.use_filters = use_filtering
        self.MAX_SHA_SIZE = 1024 * 1024 * 10
        self.last_mods["lastScan"] = 0
        self.last_mods["scanInterval"] = 90  # 60 seconds
        self.image_hasher = image_hasher
        #        self.image_hash_size=128
        self.image_hash_size = 64
        self._graphics = [".bmp", ".gif", ".jpg", ".jpeg", ".png", "webp"]
        self._archives = [".zip", ".rar", ".7z", ".lzh", ".gz"]
        self._movies = [".mp4", ".mpg", ".mkv", ".mov", ".avi", ".mp3"]

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
                print(f"Invalid Filename: {filename} --> {new_filename}")
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
        self.last_mods["scanInterval"] = 60  # 60 * 1000 ms = 60 seconds
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
        if dirpath in self.scanned_paths:
            del self.scanned_paths[dirpath]

        if dirpath in self.sha_paths:
            del self.sha_paths[dirpath]

        if dirpath in self.last_mods:
            del self.last_mods[dirpath]

        if dirpath in self.extended:
            del self.extended[dirpath]

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
        fileCount = -1
        dirCount = -1
        for x in self.extended[dirpath]:
            fileCount += self.extended[dirpath][x].is_file()
            dirCount += self.extended[dirpath][x].is_dir()
        if fileCount != -1:
            fileCount += 1

        if dirCount != -1:
            dirCount += 1
        return (fileCount, dirCount)

    def return_newest(self, dirpath):
        #       print("Returning newest for", dirpath)
        dirpath = os.path.normpath(dirpath).title().strip()
        #       print("Updated dirpath: ",dirpath)
        newest = (None, 0, 0)
        olddirpath, oldnewest, lastScan = self.last_mods[dirpath]

        #
        if time.time() - lastScan > self.last_mods["scanInterval"]:
            entries = sorted(os.scandir(dirpath), key=lambda e: e.stat().st_mtime, reverse=True)[0:10]
            entries = sorted(entries, key=lambda e: e.name)  # , reverse=True)
            for entry in entries:
                if self.processFile(entry) and entry.stat().st_mtime > newest[1]:
                    newest = (entry.name.title().strip(), entry.stat().st_mtime, time.time())
            return newest
        else:
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

        # if (self.return_fileCount(dirpath) == 0 or
        if self.last_mods[dirpath] == ('', 0, 0) or self.last_mods[dirpath] == (None, 0, 0):
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

    def generate_sha224(self, filename, hexdigest=False, maxsize=0):
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
        count = 0
        sha = sha224()
        if os.path.isfile(filename):
            with open(filename, 'rb') as sha_file:
                while True:
                    # Reading is buffered, so we can read smaller chunks.
                    chunk = sha_file.read(sha.block_size)
                    count += len(chunk)
                    if not chunk:
                        break
                    sha.update(chunk)
                    if (count != 0 and maxsize != 0 and count >= maxsize):
                        break
        if hexdigest:
            return sha.hexdigest()
        else:
            return sha.digest()

    def generate_imagehash(self, filename, debug=False):
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
        if os.path.isfile(filename):
            try:
                return self.image_hasher(Image.open(filename), hash_size=self.image_hash_size)
            except UnidentifiedImageError:
                if debug:
                    print("Damaged Image File: ", filename)
            except OSError:
                if debug:
                    print("Damaged Image File: ", filename)

        return None

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
        fext = os.path.splitext(dentry.name)[1]
        if self.use_image_hash and fext.lower() not in self._graphics:
            return False

        if not self.use_filters:
            return True

        if self.IgnoreDotFiles and dentry.name.startswith("."):
            return False

        if not self.FilesOnly:
            if dentry.is_dir():
                return True

        if fext.lower() in self.AcceptableExtensions:
            return True
        return False

    def addFileDirEntry(self, fileentry, sha_hd=None, img_hash=None):
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

        if self.use_shas:
            if dirpath not in self.sha_paths:
                self.sha_paths[dirpath] = {}

            self.sha_paths[dirpath][sha_hd] = (fileentry.stat().st_size, filename)

        if self.use_image_hash:
            if dirpath not in self.image_paths:
                self.image_paths[dirpath] = {}

            self.image_paths[dirpath][img_hash] = (fileentry.stat().st_size, filename)

    def addFile(self, dirpath, filename, sha_hd, filesize, mtime, img_hash=None):
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

        Parameters
        ----------
        dirpath
        img_hash
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
            self.sha_paths[dirpath][sha_hd] = (filesize, filename)

        if dirpath not in self.image_paths and self.use_image_hash:
            self.image_paths[dirpath] = {}
        if self.use_image_hash:
            self.image_paths[dirpath][img_hash] = (filesize, filename)

    def read_path(self, dirpath, recursive=False):
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

        Parameters
        ----------
        recursive
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
                fext = os.path.splitext(entry.name)[1].lower()
                if entry.is_file() and self.processFile(entry):
                    #                    print(entry.name, entry.is_file(), self.processFile(entry))
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
                        self.addFileDirEntry(entry, sha)

                    elif self.use_image_hash:
                        try:
                            img_hash = self.generate_imagehash(os.path.join(dirpath,
                                                                            entry))
                            self.addFileDirEntry(entry, sha_hd=None, img_hash=img_hash)
                        except OSError:
                            print("Bad image file:", os.path.join(dirpath, entry))
                    else:
                        self.addFileDirEntry(entry, sha_hd=None, img_hash=None)

                    if self.use_modify:
                        if entry.stat().st_mtime > self.last_mods[dirpath][1]:
                            self.last_mods[dirpath] = (entry.name.title(),
                                                       entry.stat().st_mtime, time.time())

                elif entry.is_dir() and recursive == True:
                    self.read_path(os.path.join(dirpath, entry.name))
                elif entry.is_dir() and self.FilesOnly == False:
                    self.addFileDirEntry(entry, None)


        except StopIteration:
            # print("StopITeration")
            # Most likely a bad path, since we can't iterate through
            # the contents Fail silently, and return False
            return False
        except FileNotFoundError:
            # the dirpath does not exist.
            # print("Target Directory does not exist ", dirpath)
            # sys.exit()
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

    def fexistSha(self, filename=None, rtn_size=False, sha_hd=None):
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

        if filename not in [None, ""]:
            dirpath, filename = os.path.split(filename.title().strip())
            dirpath = os.path.normpath(dirpath)

            if dirpath not in self.scanned_paths:
                self.read_path(dirpath)

        try:
            if self.use_shas:
                if sha_hd == None and filename not in ["", None]:
                    sha_hd = self.generate_sha224(
                        os.path.join(dirpath, filename), hexdigest=True)
                if rtn_size:
                    return self.sha_paths[dirpath][sha_hd][0]
                #                elif rtn_name:
                #                    return self.sha_paths[dirpath][sha_hd][1]

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
        for dirpath in list(self.scanned_paths):
            dirpath = sanitize_filepath(dirpath, platform="Linux")
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
        for dirpath in list(self.sha_paths.keys()):
            if self.fexistSha(dirpath + os.sep, sha_hd=shaHD):
                return (True, dirpath)
        return (False, None)

    def return_sha224_name(self, shaHD=None):
        """
import cached_exists
filedb = cached_exists.cached_exist(use_shas=True, FilesOnly=True)
filedb.read_path(".")
filedb.search_sha224_exist(shaHD="49dbafd07e1415c383baa9f61f6381ace7c057da4f90b7e2e19a5c57") # ftypes.py
filedb.return_sha224_name(shaHD="49dbafd07e1415c383baa9f61f6381ace7c057da4f90b7e2e19a5c57")
        """
        doesExist, DirExistIn = self.search_sha224_exist(shaHD=shaHD)
        if doesExist:
            return self.sha_paths[DirExistIn][shaHD][1]
        else:
            return None

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
        for dirpath in list(self.image_paths.keys()):
            if self.fexistSha(dirpath + os.sep, sha_hd=shaHD):
                return (True, dirpath)
        return (False, None)

    def fexistImgHash(self, filename=None, rtn_size=False, img_hash=None):
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

        if filename not in [None, ""]:
            dirpath, filename = os.path.split(filename.title().strip())
            dirpath = os.path.normpath(dirpath)

            if dirpath not in self.scanned_paths:
                self.read_path(dirpath)

        try:
            if self.use_image_hash:
                if img_hash == None and filename not in ["", None]:
                    img_hash = self.generate_imagehash(os.path.join(dirpath, filename))
                if rtn_size:
                    return self.image_paths[dirpath][img_hash][0]

                return img_hash in self.image_paths[dirpath]

            if rtn_size:
                return self.scanned_paths[dirpath][filename]
            return filename in self.scanned_paths[dirpath]
        except KeyError:
            return False

    def search_imagehash_exist(self, img_hash=None):
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
        for dirpath in list(self.image_paths.keys()):
            if self.fexistImgHash(dirpath + os.sep, img_hash=img_hash):
                return (True, dirpath)
        return (False, None)

    def return_imagehash_name(self, img_hash=None):
        """
    import cached_exists
    filedb = cached_exists.cached_exist(use_shas=True, FilesOnly=True)
    filedb.read_path(".")
    filedb.search_sha224_exist(shaHD="49dbafd07e1415c383baa9f61f6381ace7c057da4f90b7e2e19a5c57") # ftypes.py
    filedb.return_sha224_name(shaHD="49dbafd07e1415c383baa9f61f6381ace7c057da4f90b7e2e19a5c57")
            """
        doesExist, DirExistIn = self.search_imagehash_exist(img_hash=img_hash)
        if doesExist:
            return self.image_paths[DirExistIn][img_hash][1]
        return None


def clear_scanned_paths():
    """
    Clear the scanned path datastore
    """
    global SCANNED_PATHS
    SCANNED_PATHS = {}


def read_path(dirpath, recursive=False):
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
                SCANNED_PATHS[dirpath][entry.name.title()] = \
                    entry.stat().st_size
            elif entry.is_dir() and recursive == True:
                read_path(os.path.join(dirpath, entry.name))

        # SCANNED_PATHS[dirpath] = set(x.lower() for x in directory_data)
    except (StopIteration, OSError):
        print("Bad Path")
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
        # print (os.path.join(dirpath, filename))
        if file_exist(os.path.join(dirpath, filename)):
            return (True, dirpath)
    return (False, None)


if __name__ == "__main__":
    pass
