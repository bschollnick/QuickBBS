"""
:Module: Directory Caching
:Date: 2015-02-17
:Platforms: Mac, Windows, Unix (Tested under Mac OS X)
:Version: 1
:Authors:
    - Benjamin Schollnick


:Description:
    Used to cache and speed up Directory listings.  The Gallery project
    uses it to cache all file and directory information.

**Modules Used (Batteries Included)**:

   * os
   * os.path
   * stat
   * string
   * time

**Required 3rd Party Modules**:

   * Scandir - https://github.com/benhoyt/scandir
        * scandir is a module which provides a generator version of \
           os.listdir() that also exposes the extra file information the \
           operating system returns when you iterate a directory. \
           Generally 2-3 (or more) times faster than the standard library. \
           (It's quite noticeable!)

   * natsort - https://github.com/xolox/python-naturalsort
        * Used for natural sorting when returning alpha results

:Concept:
    The Directory Caching module was the first step in speeding up processing of
    **massive** directories (2K - 4K) files for the gallery.

    The first speed up was derived from using Scandir.  The second speed up was
    due to caching the results, and monitoring for changes.

    The library uses two methods to expire the cache:

    1. The library will check for the Modified Times on the Directories.
       If the directory's Last Modified time is newer than the last_scanned_time
       then the directory will be rescanned.
    2.  If the Directory and/or File count in the directory is different from
        the last time the directory was scanned, it will be rescanned.

**Note**:

* The second method (#2) of expiration does cause a small amount of
  performance penalty, since it has to rescan the directory, but I have
  tried to reduce the penalty as much as possible.

* The library does not normalize the pathnames, I have decided to leave
  data normalization to the application layer.  The Gallery passes
  scan_directory strings as .lower().strip() to normalize the data.

* File Extensions are normalized, as lowercase strings.
   * There are two different file extensions variables.
      * ``file_extension`` is the text only (lower case) file extension
        (e.g. doc)
      * ``dot_extension`` is the file extension with the separator
        (e.g. .doc)

* There are two different filenames variables
   * ``filename`` contains only the filename of the file
     (e.g. **spam_spam.doc**)
   * ``fq_filename`` contains the fully qualified filename of the file\
     (e.g. **/Users/Shared/tasty/spam_spam.doc**)

code::

    cdl = directory_caching.Cache()
    if not cdl.directory_in_cache("/Users/Testuser")
        cdl.smart_read("/Users/Testuser")

    if not cdl.directory_in_cache("/Volumes/Gallery/Albums")
        cdl.smart_read("/Volumes/Gallery/Albums")

    cached_files, cached_dirs = cdl.return_sorted(
                    scan_directory="/Volumes/Gallery/Albums",
                    sort_by=SORT_BY_NAME, reverse=False)

    if cdl.directory_changed(scan_directory="/Users/Testuser"):
        cdl.smart_read("/Users/Testuser")

    if cdl.directory_changed(scan_directory="/Volumes/Gallery/Albums"):
        cdl.smart_read("/Volumes/Gallery/Albums")

**Note**:

    smart_read, will check to see if the directory has changed.  So the
    example above is not optimized.

        code::

            if cdl.directory_changed(scan_directory="/Volumes/Gallery/Albums"):
                cdl.smart_read("/Volumes/Gallery/Albums")

    Can be rewritten simply as:

        code::

            cdl.smart_read("/Volumes/Gallery/Albums")

"""
#####################################################
#   Batteries Included imports
import exceptions
import os
import os.path
import stat
import string
import time

#   Required third party
import natsort  # https://github.com/xolox/python-naturalsort
import scandir  # https://github.com/benhoyt/scandir

SORT_BY_NAME = 0
SORT_BY_MODIFIED = 1
SORT_BY_CREATION = 2
#####################################################
class DirEntry(object):
    """
    Args:
        path (str): The path of the file to wrap
        field_storage (FileStorage): The :class:`FileStorage` instance to wrap
        temporary (bool): Whether or not to delete the file when the File
           instance is destructed

    Returns:
        BufferedFileStorage: A buffered writable file descriptor

    The is the template class for the cache objects.
    Used to store data regarding the files or subdirectories.

    * Directory Only Data

       * ``number_files`` - It contains the number of files, \
            in the directory.
       * ``number_dirs`` - It contains the number of subdirectories\
            in the directory.
       * ``directoryname`` - Contains the directory name (not pathname)
       * ``filename`` - is blank, the directory equivalent is \
            directoryname.

    * Common Data
       * ``file_extension`` - Contains the file extension of the file\
            for a directory, "dir" is placed in the file extension.
       * ``dot_extension`` - See ``file_extension``.  This has the \
            "." prefix.  Otherwise identical to ``file_extension``.
       * ``fq_filename`` - For files, ``fq_filename`` will be the\
            absolute path to the file.  For directories, fq_filename\
            will also point to the absolute path to the directory.
       * ``human_st_mtime`` - This is a human readable last modified
          * timetime.asctime(time.localtime(data.st[stat.ST_MTIME]))
       * ``parentdirectory`` - Contains the absolute pathname of the\
            parent directory that contains the file/directory.
       * ``st`` - Contains the statistics for the file/directory
          * ``st_mode`` - FileMode, iNode protection mode
          * ``st_ino`` - iNode Number
          * ``st_dev`` - Device iNode resides on
          * ``st_nlink`` - Number of Links to the iNode
          * ``st_uid`` - User Id of the Owner
          * ``st_gid`` - Group id of the owner
          * ``st_size`` - Size in bytes of file object
          * ``st_atime`` - Time of last modification
          * ``st_mtime`` - Last modification time
          * ``st_ctime`` - creation time, as reported by OS

    * File only data
       * ``directoryname`` - Will be Blank (it is not a directory)\
       * ``filename`` - Contains the filename of the file, for \
            directories this is blank.

    """

#####################################################
    def __init__(self):
        """
        structure for storing the data in the cache.
        """
        self.number_files = None
        self.number_dirs = None
        self.parentdirectory = None
        self.directoryname = None
        self.file_extension = None
        self.dot_extension = None
        self.filename = None
        self.fq_filename = None
        self.st = None
        self.human_st_mtime = None

#####################################################
class Cache(object):
    """
    This is the mainstay of the Directory Caching engine.

    Establishes the Baseline Settings for the Cache.

    * ``files_to_ignore`` = ['.ds_store', '.htaccess']
        * Contains a list of filenames that are to be ignored, and not
          added to cache if they are in a folder.
        * By default .ds_store, and .htaccess files are ignored.
        * These items must be lowercased.  Internally all filenames are
          normalized to lowercase.
    * ``acceptable_extensions`` = [] # See Note #1
        * If this is set, this becomes a "reverse" filter. Only files
          that contain a file extension that is in this list, will be
          "detected" and cached.
        * An empty list [], indicates **all** files should be accepted.
        * By default, all files are allowed / accepted.
        * As above, these extensions need to be normalized in lowercase.
    * ''hidden_dot_files'', boolean value.  If true, any file that starts
        with a . will be ignored.  Otherwise, they will be added to the cache.

    **Note:**

    1. These are ``file extensions`` (e.g. doc), not dot_extensions
       (e.g. .doc)

    """
#####################################################
    def __init__(self):
        """
        Setup and establish the working implementation for directory caching.


        """
        # User Changable Settings
        self.files_to_ignore = ['.ds_store', '.htaccess']
        self.hidden_dot_files = True
        self.acceptable_extensions = []
        self.filter_filenames = None
        self.root_path = None
            # This is the path in the OS that is being examined
            #    (e.g. /Volumes/Users/username/)
        self.d_cache = {}
#####################################################
    def _scan_directory_list(self, scan_directory):
        """
        Args:
            scan_directory (str): The fully qualified pathname to examine

        Returns:
            None

        Scan the directory "scan_directory", and save it to the
        self.d_cache dictionary.

        **Low Level function, intended to be used by the populate function.**

        scan_directory is matched absolutely, case sensitive,
        string is stripped(), but otherwise left alone.

        Highly recommend using a normalization routine on the
        scan_directory string before sending it to cache.
        """
        directories = {}
        files = {}

        norm_dir_name = scan_directory.strip()
        self.d_cache[norm_dir_name] = {}
        self.d_cache[norm_dir_name]["last_sort"] = None

        for s_entry in scandir.scandir(scan_directory):
            data = DirEntry()
            data.st = s_entry.lstat()
            if self.filter_filenames != None:
                orig_name = s_entry.name
                clean_name = self.filter_filenames(orig_name)
                if orig_name != clean_name:
                    try:
                        os.rename(os.path.join(s_entry._path, orig_name),
                                  os.path.join(os.path.realpath(\
                                               scan_directory).strip(),
                                               clean_name))
                    except exceptions.OSError:
                        pass
            else:
                clean_name = s_entry.name

            data.fq_filename = os.path.join(
                os.path.realpath(scan_directory.strip()),
                clean_name)
            data.parentdirectory = os.path.join(
                os.path.split(scan_directory)[0:-1])
            data.human_st_mtime = time.asctime(
                time.localtime(data.st[stat.ST_MTIME]))
            if clean_name.strip().lower() in self.files_to_ignore:
                continue
            if self.hidden_dot_files:
                if clean_name.startswith("."):
                    continue

            if s_entry.is_dir():
                data.filename = ""
                data.directoryname = clean_name
                data.dot_extension = ".dir"
                data.file_extension = "dir"

                (data.number_files,
                 data.number_dirs) = self._return_file_dir_count(\
                       data.fq_filename)
                directories[clean_name] = data
            else:
                data.filename = clean_name
                data.directoryname = scan_directory
                data.dot_extension = string.lower(\
                                os.path.splitext(clean_name)[1])
                data.file_extension = data.dot_extension[1:]
                if self.acceptable_extensions == []:
                    #
                    #   There are no non-acceptable files.
                    #
                    files[clean_name] = data
                elif data.file_extension.lower() in self.acceptable_extensions:
                    #
                    #   Filter by extensions
                    #
                    files[s_entry.name.strip()] = data
        self.d_cache[norm_dir_name]["files"] = files
        self.d_cache[norm_dir_name]["dirs"] = directories
        self.d_cache[norm_dir_name]["last_scanned_time"] = time.time()
        self.d_cache[norm_dir_name]["last_sort"] = None
        return

#####################################################
    def _return_file_dir_count(self, scan_directory):
        """
        Args:
            scan_directory (str): The fully qualified pathname to examine

        Returns:
            (File_count, dir_count) - Tupple of Integers

        This is a internal use only function.

        It returns the number of files, and directories in the scan_directory.
        This is the actual file system, and not cached directories.

        * Primarily used to in directory_changed to help highlight directories
          that have changed, but the last_modified has not been updated.
        * Also used in _scan_directory_list, to help populate the directory
          count of files / dirs.
        """
        scan_directory = os.path.realpath(scan_directory).strip()
        fcount = 0
        dcount = 0
        for s_entry in scandir.scandir(scan_directory):
            if s_entry.is_dir():
                dcount += s_entry.is_dir()
            else:
                if s_entry.name.strip().lower() in self.files_to_ignore:
                    continue

                if self.acceptable_extensions != []:
                    #
                    #   There are no non-acceptable files.
                    #
                    if not os.path.splitext(s_entry.name)[1][1:].lower() in\
                        self.acceptable_extensions:
                    #
                    #   Filter by extensions
                    #
                        continue

                fcount += s_entry.is_file()
        return (fcount, dcount)

#####################################################
    def directory_in_cache(self, scan_directory):
        """
        Args:
            scan_directory (str): The path of the file to wrap

        Returns:
            Boolean

        Return Values

        * True - Directory is in the cache
        * False - Directory is not in the cache

        This simply returns a boolean, indicating if the scan_directory is
        present in the cache.
        """
        scan_directory = os.path.realpath(scan_directory).strip()
        return scan_directory in self.d_cache.keys()

#####################################################
    def return_current_directory_offset(self,
                                        scan_directory,
                                        current_directory,
                                        offset=0,
                                        sort_type=0,
                                        reverse=False):
        """
    Args:
        scan_directory (str): The fully qualified pathname to examine
        current_directory (str): The current directory name
        offset (int): The offset modifier
        sort_type (int): Which sort to apply to the listings

    Returns, list containing:
        (Integer, string)

        Integer: The newly calculated offset
        String: The Directory name of the new offset

    return the offset of the next or previous directory, in \
    scan_directory, where current_directory is the current_directory\
    that you are residing in from the scan_directory.

    e.g. /Users/Benjamin is the scan_directory, you are in Movies.  So
    current_directory is Movies.

    Used for calculating the previous / next directory in the gallery.

    offset value examples
        *  0 - return current directories offset
        * -1 - return the previous directory
        * +1 - return the next directory in the list

    Code::
       import directory_caching
       cdl = directory_caching.Cache()
       cdl.smart_read( "/Users/Benjamin" )
       dirs = cdl.return_sort_name(scan_directory="/Users/Benjamin")[1]
       print dirs[cdl.return_current_directory_offset(
                    scan_directory = "/Users/Benjamin",
                    current_directory="Movies", offset=0)]
       print dirs[cdl.return_current_directory_offset(
                    scan_directory = "/Users/Benjamin",
                    current_directory="Movies", offset=2)]
       print dirs[cdl.return_current_directory_offset(
                    scan_directory = "/Users/Benjamin",
                    current_directory="Movies", offset=-2)]

        """
        scan_directory = os.path.realpath(scan_directory).strip()
        self.smart_read(scan_directory)
        dirs = self.return_sorted(scan_directory,
                                  sort_by=sort_type,
                                  reverse=reverse)[1]
        current_offset = None
        for dir_entry in range(0, len(dirs)):
            if dirs[dir_entry][0].lower().strip() ==\
                current_directory.lower().strip():
                current_offset = dir_entry
                break
        if offset == 0:
            return (current_offset, dirs[current_offset+offset][0])

        if current_offset == None or len(dirs) <= 1:
            #
            #   current_offset == None - Empty Directory?
            #           Was not found in the for loop.
            #
            #   len(dirs) == 1, only one directory, there are no previous or
            #       next directories.
            #
            return (None, None)

        if offset < 0:
            #
            #   Negative Offset
            #
            if current_offset + offset >= 0:
                # offset is negative X
                return (current_offset + offset, dirs[current_offset+offset][0])
            else:
                return (None, None)
        else:
            if current_offset + offset > len(dirs)-1:
                #   len is 1 based, current_offset is 0 based.
                return (None, None)
            else:
                return (current_offset + offset, dirs[current_offset+offset][0])


#####################################################
    def directory_changed(self, scan_directory):
        """
    Args:
        scan_directory (str): The fully qualified pathname to examine

    Returns:
        Boolean

    Return Values

    * True - The directory has changed since being added to the cache
    * False - The directory has **not** changed since being added to the cache

    Pass the target directory as scan_directory.

    There is two checks being made to decide on the validity of the cache.

    1. Check the last modified time on the directory vs the
        **last_scanned_time** in the cached data.
    2. Check the number of files and directories in the cached copy for any
       differences.

        """
        if self.directory_in_cache(scan_directory):
            #   Is in cache
            scan_directory = os.path.realpath(scan_directory).strip()
            st = os.stat(scan_directory)
            #   Return true if modified time on directory is newer Cached Time.
            if self.d_cache[scan_directory].has_key("last_scanned_time"):
                if st[stat.ST_MTIME] > self.d_cache[scan_directory]\
                    ["last_scanned_time"]:
                    return True
            else:
                return False

            if (len(self.d_cache[scan_directory]["files"]),\
                len(self.d_cache[scan_directory]["dirs"])) !=\
                    self._return_file_dir_count(scan_directory):
                return True
        else:
            #   Does not exist in Cache, so force a load.
            return True

#####################################################
    def smart_read(self, scan_directory):
        """
    Args:
        scan_directory (str): The fully qualified pathname to examine

    Returns:
        None

    This is a wrapper around the Read and changed functions.

    The scan_directory is passed in, converted to a normalized form,
    and then checked to see if it exists in the cache.

    If it doesn't exist (or is expired), then it is read.

    If it already exists *AND* has not expired, it is not
    updated.

    **Net affect, this will ensure the directory is in cache, and
    update to date.**

    In addition, the clean_filename function has been merged into
    _scan_directory.  It will check to see if any filenames in the
    ``scan_directory`` location need to be scrubbed / cleaned.

    This function uses the ``filter_filenames`` variable/pointer to
    check and scrub the filenames.

    If self.filter_filenames is set, this function will call
    self.filter_filenames to test against the file and directory names.

    This feature was added for the gallery, to automate the renaming
    of the directories and files, to ensure that the files and directory
    names are acceptable to the web server and web browser.

    By setting a ``filter_filenames`` function, you can use this as you
    choose.

    By default, this is not turned on.  This is an opt-in feature.

    code::

        import common
        import file_types
        self.cdl = directory_caching.Cache()
        self.cdl.files_to_ignore = file_types.files_to_ignore
        self.cdl.acceptable_extensions = file_types.image_safe_files
        self.cdl.filter_filenames = common.clean_filename2
        print "Priming the cache for %s, please wait" %\
            file_types.locations["albums_root"].lower().strip()
        self.cdl.smart_read(
            file_types.locations["albums_root"].lower().strip())
        print "Pump primed."

    After assigning self.cdl.filter_filenames, every time a directory is
    examined by the caching engine, it will rename the files and directories
    if an invalid filename or directory name is found.

    This check is simply a comparison, the filename is passed to the cleaning
    function, and if the returned filename is different, the file is renamed
    to the new name.

    code::

        if orig_name[1].fq_filename != new_name:
            os.rename(orig_name[1].fq_filename, new_name)

    An example cleaning function, from the Gallery application.

    code::

        def clean_filename2(filename):
        replacements = {'"':"`", "'":"`",
                        ",":"", "#":"",
                        "*":"", "@":"",
                        ":":"-", "|":""}
        filename = replace_all(urllib2.unquote(filename), replacements)
            # Un"quotify" the URL / Filename
        filename = unidecode.unidecode(filename)
            # de-unicode the filename / url
        filename, fileext = os.path.splitext(filename)
        filename = filename.strip() + fileext.strip()
            # remove extra spaces from filename and file extension.
            # e.g.  "this is the filename .txt" -> "this is the filename.txt"
        return filename


        """
        scan_directory = os.path.realpath(scan_directory).strip()
        if self.directory_changed(scan_directory):
            self._scan_directory_list(scan_directory)

#####################################################
    def return_sorted(self, scan_directory, sort_by=0, reverse=False):
        """
    Args:
        scan_directory (str): The fully qualified pathname to examine
        sort_by (integer / constant):

                SORT_BY_NAME        = 0
                SORT_BY_MODIFIED    = 1
                SORT_BY_CREATION    = 2

        reverse (bool): Is this an ascending or descending (**reverse**) sort

    Returns:
        Tupple: List of sorted Cache entries (text, scandir DirEntry)


    Return sorted list(s) from the Directory Cache for the
    Scanned directory, sorted by name.

    Returns 2 tuples of date, T[0] - Files, and T[1] - Directories
    which contain the data from the cached directory.

        """
        scan_directory = os.path.realpath(scan_directory).strip()
        self.smart_read(scan_directory)
        if self.d_cache[scan_directory]["last_sort"] != sort_by:
            self.d_cache[scan_directory]["last_sort"] = sort_by
            files = self.d_cache[scan_directory]["files"]
            dirs = self.d_cache[scan_directory]["dirs"]
            if sort_by == SORT_BY_NAME:
                files = natsort.natsort(files.items(),
                                        key=lambda t:\
                                            string.lower(t[1].filename),
                                        reverse=reverse)
                dirs = natsort.natsort(dirs.items(),
                                       key=lambda t: string.lower(\
                                            t[1].directoryname),
                                       reverse=reverse)
            elif sort_by == SORT_BY_MODIFIED:
                files = sorted(files.items(),\
                               key=lambda t: t[1].st.st_mtime, reverse=reverse)
                dirs = sorted(dirs.items(),\
                               key=lambda t: t[1].st.st_mtime, reverse=reverse)
            elif sort_by == SORT_BY_CREATION:
                files = sorted(files.items(),\
                               key=lambda t: t[1].st.st_ctime, reverse=reverse)
                dirs = sorted(dirs.items(),\
                               key=lambda t: t[1].st.st_ctime, reverse=reverse)

            self.d_cache[scan_directory]["sort_index"] = files, dirs
        return self.d_cache[scan_directory]["sort_index"]


#####################################################
    def return_sort_name(self, scan_directory, reverse=False):
        """
    Here for backward compatibility versus earlier versions of the library.
    This will eventually be removed.

    Args:
        scan_directory (str): The fully qualified pathname to examine
        reverse (bool): Is this an ascending or descending (**reverse**) sort

    Returns:
        Same as return_sorted.
        """
        return self.return_sorted(scan_directory,
                                  sort_by=SORT_BY_NAME,
                                  reverse=reverse)

#####################################################
    def return_sort_lmod(self, scan_directory, reverse=False):
        """
    Here for backward compatibility versus earlier versions of the library.
    This will eventually be removed.

    Args:
        scan_directory (str): The fully qualified pathname to examine
        reverse (bool): Is this an ascending or descending (**reverse**) sort

    Returns:
        Same as return_sorted.
        """
        return self.return_sorted(scan_directory,
                                  sort_by=SORT_BY_MODIFIED,
                                  reverse=reverse)

#####################################################
    def return_sort_ctime(self, scan_directory, reverse=False):
        """
    Here for backward compatibility versus earlier versions of the library.
    This will eventually be removed.

    Args:
        scan_directory (str): The fully qualified pathname to examine
        reverse (bool): Is this an ascending or descending (**reverse**) sort

    Returns:
        Same as return_sorted.
        """
        return self.return_sorted(scan_directory,
                                  sort_by=SORT_BY_CREATION,
                                  reverse=reverse)
