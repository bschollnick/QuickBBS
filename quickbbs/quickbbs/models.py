"""
Django Models for quickbbs
"""

import hashlib
import io
import os
import pathlib
import time
import uuid
from functools import lru_cache

# from aiofile import AIOFile, Reader
# from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models import Count
from django.db.models.query import QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse
from filetypes.models import filetypes, get_ftype_dict
from ranged_fileresponse import RangedFileResponse
from thumbnails.models import ThumbnailFiles

from quickbbs.common import get_dir_sha, normalize_fqpn
from quickbbs.natsort_model import NaturalSortField


class Owners(models.Model):
    """
    Start of a permissions based model.
    """

    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, blank=True, db_index=True
    )
    ownerdetails = models.OneToOneField(
        User, on_delete=models.CASCADE, db_index=True, default=None
    )

    class Meta:
        verbose_name = "Ownership"
        verbose_name_plural = "Ownership"


class Favorites(models.Model):
    """
    Start of setting up a users based favorites for gallery items
    """

    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, blank=True, db_index=True
    )


class IndexDirs(models.Model):
    """
    The master index for Directory / Folders in the Filesystem for the gallery.
    """

    fqpndirectory = models.CharField(
        db_index=False, max_length=384, default="", unique=True, blank=True
    )  # True fqpn name

    dir_fqpn_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )  # sha of the directory fqpn
    dir_parent_sha256 = models.CharField(
        db_index=True, null=True, default=None, unique=False, max_length=64
    )  # Is the FQPN of the parent directory (eg /var/albums/test)

    lastscan = models.FloatField(
        db_index=True, default=None
    )  # Stored as Unix TimeStamp (ms)
    lastmod = models.FloatField(
        db_index=True, default=None
    )  # Stored as Unix TimeStamp (ms)
    name_sort = NaturalSortField(for_field="fqpndirectory", max_length=384, default="")
    is_generic_icon = models.BooleanField(
        default=False, db_index=True
    )  # File is to be ignored
    delete_pending = models.BooleanField(
        default=False, db_index=True
    )  # File is to be deleted,
    filetype = models.ForeignKey(
        filetypes,
        to_field="fileext",
        on_delete=models.CASCADE,
        db_index=True,
        default=".dir",
        related_name="dirs_filetype_data",
    )
    thumbnail = models.ForeignKey(
        "IndexData",
        on_delete=models.CASCADE,
        related_name="dir_thumbnail",
        null=True,
        default=None,
    )
    file_links = models.ManyToManyField(
        "IndexData",
        default=None,
        related_name="file_links",
    )

    class Meta:
        verbose_name = "Master Directory Index"
        verbose_name_plural = "Master Directory Index"

    @staticmethod
    def add_directory(fqpn_directory, thumbnail=b"") -> "IndexDirs":
        """
        Create a new directory entry or get existing one
        :param fqpn_directory: The fully qualified pathname for the directory
        :param thumbnail: thumbnail image to store for the thumbnail/cover art
        :return: Database record
        """
        Path = pathlib.Path(fqpn_directory)
        fqpn_directory = normalize_fqpn(str(Path.resolve()))
        parent_dir = normalize_fqpn(str(Path.parent.resolve()))
        # Prepare the defaults for fields that should be set on creation
        defaults = {
            "fqpndirectory": normalize_fqpn(fqpn_directory),
            "lastmod": os.path.getmtime(fqpn_directory),
            "lastscan": time.time(),
            "filetype": filetypes(fileext=".dir"),
            "dir_fqpn_sha256": get_dir_sha(fqpn_directory),
            "dir_parent_sha256": get_dir_sha(parent_dir),
            "is_generic_icon": False,
            "thumbnail": None,
        }

        # Use get_or_create with fqpndirectory as the unique lookup field
        new_rec, created = IndexDirs.objects.update_or_create(
            dir_fqpn_sha256=defaults["dir_fqpn_sha256"],
            defaults=defaults,
            create_defaults=defaults,
        )
        found = not created
        return found, new_rec

    def invalidate_thumb(self) -> None:
        """
        Invalidate the thumbnail for the directory.  This is used when the directory
        is deleted, and the thumbnail is no longer valid.

        :return: None
        """
        print("Invalidating generic thumbnail for ", self.fqpndirectory)
        self.thumbnail
        self.is_generic_icon = False
        self.save()

    # def associate_files(self) -> None:
    #     """
    #     Associate files with the directory.
    #     :return: None
    #     """
    #     # Get all files in the directory
    #     files = IndexData.objects.filter(home_directory=self.pk)
    #     for file in files:
    #         file.directory = self
    #         file.save()

    def get_dir_sha(self) -> str:
        """
        Return the SHA256 hash of the file as a hexdigest string

        Args:
            fqfn (str) : The fully qualified filename of the file to be hashed

        :return: The SHA256 hash of the file + fqfn as a hexdigest string
        """
        return get_dir_sha(self.fqpndirectory)

    @property
    def virtual_directory(self) -> str:
        """
        Return the virtual directory name of the directory.
        This is used to return the directory name without the full path.
        :return: String
        """
        return str(pathlib.Path(self.fqpndirectory).name)

    @property
    def numdirs(self) -> None:
        """
        Place holder for backward compatibility reasons (matching the numdirs attribute
        of IndexData)
        :return: None
        """
        return None

    @property
    def numfiles(self) -> None:
        """
        Place holder for backward compatibility reasons (matching the numdirs attribute
        of IndexData)
        :return: None
        """
        return None

    @property
    def name(self) -> str:
        """
        Return the directory name of the directory.
        :return: String
        """
        return str(pathlib.Path(self.fqpndirectory).name)

    @staticmethod
    def delete_directory(fqpn_directory, cache_only=False) -> None:
        """
        Delete the Index_Dirs data for the fqpn_directory, and ensure that all
        IndexData records are wiped as well.
        :param fqpn_directory: text string of fully qualified pathname of the directory
        :param cache_only: Do not perform a delete on the Index_Dirs data
        :return:
        """
        # pylint: disable-next=import-outside-toplevel
        from cache_watcher.models import Cache_Storage

        dir_sha256 = get_dir_sha(normalize_fqpn(fqpn_directory))
        Cache_Storage.remove_from_cache_sha(dir_sha256)
        if not cache_only:
            IndexDirs.objects.filter(dir_fqpn_sha256=dir_sha256).delete()

    def do_files_exist(self, additional_filters=None) -> bool:
        if additional_filters is None:
            additional_filters = {}
        return self.IndexData_entries.filter(
            home_directory=self.pk, delete_pending=False, **additional_filters
        ).exists()

    def get_file_counts(self) -> int:
        """
        Return the number of files that are in the database for the current directory
        :return: Integer - Number of files in the database for the directory
        """
        return self.IndexData_entries.filter(delete_pending=False).count()
        # return IndexData.objects.filter(
        #    home_directory=self.pk, delete_pending=False
        # ).count()

    def get_dir_counts(self) -> int:
        """
        Return the number of directories that are in the database for the current directory
        :return: Integer - Number of directories
        """
        return IndexDirs.objects.filter(
            dir_parent_sha256=self.dir_fqpn_sha256, delete_pending=False
        ).count()

    def get_count_breakdown(self) -> dict:
        """
        Return the count of items in the directory, broken down by filetype.
        :return: dictionary, where the key is the filetype (e.g. "dir", "jpg", "mp4"),
        and the value is the number of items of that filetype.
        A special "all_files" key is used to store the # of all items in the directory (except
        for directories).  (all_files is the sum of all file types, except "dir")
        """
        filetypes_dict = get_ftype_dict()
        d_files = self.files_in_dir()
        totals = {}
        for key in filetypes_dict.keys():
            totals[key[1:]] = d_files.filter(filetype__fileext=key).count()

        totals["dir"] = self.get_dir_counts()
        totals["all_files"] = self.get_file_counts()
        return totals

    @lru_cache(maxsize=100)
    def return_parent_directory(self) -> "QuerySet[IndexDirs]":
        """
        Return the database object of the parent directory to the current directory
        :return: database record of parent directory
        """
        parent = pathlib.Path(self.fqpndirectory).parent
        parent_dir = IndexDirs.objects.filter(fqpndirectory=str(parent) + os.sep)
        return parent_dir

    @lru_cache(maxsize=1000)
    @staticmethod
    def search_for_directory_by_sha(sha_256) -> tuple[bool, "IndexDirs"]:
        """
        Return the database object matching the dir_fqpn_sha256
        :param sha_256: The SHA-256 hash of the directory's fully qualified pathname
        :return: A boolean representing the success of the search, and the resultant record
        """
        try:
            record = IndexDirs.objects.get(
                dir_fqpn_sha256=sha_256,
                delete_pending=False,
            )
            return (True, record)
        except IndexDirs.DoesNotExist:
            return (False, IndexDirs.objects.none())  # return an empty query set

    @lru_cache(maxsize=1000)
    @staticmethod
    def search_for_directory(fqpn_directory) -> tuple[bool, "IndexDirs"]:
        """
        Return the database object matching the fqpn_directory
        :param fqpn_directory: The fully qualified pathname of the directory
        :return: A boolean representing the success of the search, and the resultant record
        """
        Path = pathlib.Path(fqpn_directory)
        fqpn_directory = normalize_fqpn(str(Path.resolve()))
        try:
            record = IndexDirs.objects.get(
                dir_fqpn_sha256=get_dir_sha(fqpn_directory),
                delete_pending=False,
            )
            return (True, record)
        except IndexDirs.DoesNotExist:
            return (False, IndexDirs.objects.none())  # return an empty query set

    @staticmethod
    def return_by_sha256_list(sha256_list, sort=0) -> "QuerySet[IndexDirs]":
        """
        Return the dirs in the current directory
        :param sort: The sort order of the dirs (0-2)
        :return: The sorted query of dirs
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import SORT_MATRIX

        dirs = (
            IndexDirs.objects.filter(dir_fqpn_sha256__in=sha256_list)
            .filter(delete_pending=False)
            .order_by(*SORT_MATRIX[sort])
        )
        return dirs

    def files_in_dir(self, sort=0, additional_filters=None) -> "QuerySet[IndexData]":
        """
        Return the files in the current directory
        :param sort: The sort order of the files (0-2)
        :return: The sorted query of files
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import SORT_MATRIX

        if additional_filters is None:
            additional_filters = {}

        # files = (
        #     IndexData.objects.prefetch_related("new_ftnail", "filetype")
        #     .filter(home_directory=self.pk, delete_pending=False, **additional_filters)
        #     .order_by(*SORT_MATRIX[sort])
        # )
        files = (
            self.IndexData_entries.prefetch_related("new_ftnail")
            .select_related("filetype")
            .filter(delete_pending=False, **additional_filters)
            .order_by(*SORT_MATRIX[sort])
        )

        return files

    def dirs_in_dir(self, sort=0) -> "QuerySet[IndexDirs]":
        """
        Return the directories in the current directory
        :param sort: The sort order of the directories (0-2)
        :return: The sorted query of directories
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import SORT_MATRIX

        return IndexDirs.objects.filter(
            dir_parent_sha256=self.dir_fqpn_sha256, delete_pending=False
        ).order_by(*SORT_MATRIX[sort])

    def get_view_url(self) -> str:
        """
        Generate the URL for the viewing of the current database item

        Returns
        -------
            Django URL object

        """
        from frontend.utilities import convert_to_webpath

        webpath = convert_to_webpath(
            self.fqpndirectory.replace(settings.ALBUMS_PATH.lower() + r"/albums/", r"")
        )
        return reverse("directories") + webpath

    def get_bg_color(self) -> str:
        """
        Get the html / Cell background color of the file.

        Returns
        -------
        * The background hex color code of the current database entry
        """
        return self.filetype.color

    def return_identifier(self) -> str:
        return self.dir_fqpn_sha256

    # pylint: disable-next=unused-argument
    def get_thumbnail_url(self, size=None) -> str:
        """
        Generate the URL for the thumbnail of the current item
        The argument is unused, included for API compt. between IndexData & IndexDirs

        Returns
        -------
            Django URL object

        """
        return reverse(r"thumbnail2_dir", args=(self.dir_fqpn_sha256,))

    # def send_thumbnail(self) -> FileResponse:
    #     """
    #      Output a http response header, for an image attachment.

    #     Args:
    #          filename (str): The filename to be sent with the thumbnail

    #      Returns:
    #          object::
    #              The Django response object that contains the attachment and header

    #      Raises:
    #          None

    #      Examples
    #      --------
    #      return_img_attach("test.png", img_data)

    #      # https://stackoverflow.com/questions/36392510/django-download-a-file
    #      # https://stackoverflow.com/questions/27712778/
    #      #               video-plays-in-other-browsers-but-not-safari
    #      # https://stackoverflow.com/questions/720419/
    #      #               how-can-i-find-out-whether-a-server-supports-the-range-header

    #     """
    #     mtype = "application/octet-stream"
    #     response = FileResponse(
    #         io.BytesIO(self.small_thumb),
    #         content_type=mtype,
    #         as_attachment=False,
    #         filename=os.path.basename(self.fqpndirectory) + ".jpg",
    #     )
    #     response["Content-Type"] = mtype
    #     response["Content-Length"] = len(self.small_thumb)
    #     return response


class IndexData(models.Model):
    """
    The Master Index for All files in the Gallery.  (See IndexDirs for the counterpart
    for Directories)

    The file_sha256 is the Sha256 of the file itself, and can be used to help eliminate multiple
    thumbnails being created for the same file.

    The unique_sha256 is the sha256 of the file + the fully qualified pathname of the file.
    The unique sha256 is the eventual replacement for the UUID.  The idea is that a regeneration of the
    database does not destroy the valid identifiers for the files.  The UUID works as an unique identifier,
    but is randomly generated, which means that it can't be regenerated after a database regeneration, or
    if the database record is deleted, and then recreated.  Where the unique_sha256 can be, as long as the
    file & file path is the same and unchanged.
    """

    id = models.AutoField(primary_key=True)

    file_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=False,
        null=True,
        default=None,
        max_length=64,
    )  # This is the sha256 of the file itself
    unique_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )  # This is the sha256 of the (file + fqfn)

    lastscan = models.FloatField(db_index=True)
    # Stored as Unix TimeStamp (ms)
    lastmod = models.FloatField(db_index=True)  # Stored as Unix TimeStamp (ms)
    # Stored as Unix TimeStamp (ms)
    name = models.CharField(db_index=True, max_length=384, default=None)
    # FQFN of the file itself
    name_sort = NaturalSortField(for_field="name", max_length=384, default="")
    duration = models.BigIntegerField(null=True)
    size = models.BigIntegerField(default=0)  # File size

    home_directory = models.ForeignKey(
        "IndexDirs",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        related_name="IndexData_entries",
    )
    is_animated = models.BooleanField(default=False, db_index=True)
    ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
    delete_pending = models.BooleanField(
        default=False, db_index=True
    )  # File is to be deleted,
    cover_image = models.BooleanField(
        default=False, db_index=True
    )  # This image is the directory placard
    filetype = models.ForeignKey(
        filetypes,
        to_field="fileext",
        on_delete=models.CASCADE,
        db_index=True,
        default=".none",
        related_name="file_filetype_data",
    )
    is_generic_icon = models.BooleanField(
        default=False, db_index=False
    )  # icon is a generic icon

    dir_sha256 = models.CharField(
        db_index=True,
        blank=True,
        unique=True,
        null=True,
        default=None,
        max_length=64,
    )

    new_ftnail = models.ForeignKey(
        ThumbnailFiles,
        on_delete=models.SET_NULL,
        blank=True,
        default=None,
        null=True,
        related_name="IndexData",
    )

    # https://stackoverflow.com/questions/38388423

    ownership = models.OneToOneField(
        Owners,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

    @property
    def fqpndirectory(self) -> str:
        return self.home_directory.fqpndirectory

    def update_or_create_file(self, fs_record, unique_file_sha256, dir_sha256):
        """
        Add a file to the database, or update an existing file.
        :param file_info: Dictionary with file information, including:
            - name: The name of the file
            - fqpndirectory: The fully qualified pathname of the directory
            - size: The size of the file
            - lastmod: The last modified time of the file
            - file_sha256: The SHA256 hash of the file
            - unique_sha256: The unique SHA256 hash of the file + fqfn
            - is_animated: Whether the file is animated (e.g., GIF)
            - ignore: Whether to ignore this file
            - delete_pending: Whether this file is pending deletion
            - index_image: Whether this image is an index image
            - filetype: The type of the file (e.g., .jpg, .mp4)
        :param dir_sha256: The SHA256 hash of the directory containing the file
        :return: Tuple (found, new_rec) where found is a boolean indicating if the record was found,
                 and new_rec is the IndexData object.
        """
        print("Debug: ", fs_record["filetype"])
        defaults = {
            "name": fs_record["name"],
            "fqpndirectory": normalize_fqpn(fs_record["fqpndirectory"]),
            "size": int(fs_record["size"]),
            "lastmod": float(fs_record["lastmod"]),
            "file_sha256": fs_record.get("file_sha256", None),
            "unique_sha256": fs_record.get("unique_sha256", None),
            "is_animated": bool(fs_record.get("is_animated", False)),
            "ignore": bool(fs_record.get("ignore", False)),
            "delete_pending": bool(fs_record.get("delete_pending", False)),
            "index_image": bool(fs_record.get("index_image", False)),
            "filetype": fs_record["filetype"],
            #            "filetype": filetypes.objects.get(fileext=fs_record["filetype"]),
            "dir_sha256": dir_sha256,
        }

        # Create or update the IndexData record
        new_rec, created = IndexData.objects.update_or_create(
            unique_sha256=defaults["unique_sha256"],
            defaults=defaults,
            create_defaults=defaults,
        )
        found = not created
        return found, new_rec

    def return_unique_identifier(self) -> str:
        return self.unique_sha256

    @staticmethod
    def return_identical_files_count(sha) -> int:
        """
        Return the number of identical files in the database
        :return: Integer - Number of identical files
        """
        return IndexData.objects.filter(file_sha256=sha).count()

    @staticmethod
    def return_list_all_identical_files_by_sha(sha) -> "QuerySet[IndexData]":
        dupes = (
            IndexData.objects.filter(file_sha256=sha)
            .values("file_sha256")
            .annotate(dupe_count=Count("file_sha256"))
            .exclude(dupe_count__lt=2)
            .order_by("-dupe_count")
        )
        return dupes

    @staticmethod
    def get_identical_file_entries_by_sha(sha):
        return IndexData.objects.values("name", "fqpndirectory").filter(file_sha256=sha)

    @lru_cache(maxsize=1000)
    @staticmethod
    def get_by_filters(additional_filters=None) -> "QuerySet[IndexData]":
        """
        Return the files in the current directory, filtered by additional filters
        :param additional_filters: Additional filters to apply to the query
        :return: The filtered query of files
        """
        if additional_filters is None:
            additional_filters = {}
        return IndexData.objects.filter(delete_pending=False, **additional_filters)

    @staticmethod
    def return_by_sha256_list(sha256_list, sort=0) -> "QuerySet[IndexData]":
        """
        Return the files in the current directory
        :param sort: The sort order of the files (0-2)
        :return: The sorted query of files
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.utilities import SORT_MATRIX

        files = (
            IndexData.objects.prefetch_related("new_ftnail")
            .select_related("filetype")
            .filter(file_sha256__in=sha256_list, delete_pending=False)
            .order_by(*SORT_MATRIX[sort])
        )
        return files

    @lru_cache(maxsize=1000)
    @staticmethod
    def get_by_sha256(sha_value, unique=False) -> "IndexData":
        """
        Return the IndexData object by SHA256
        :param sha_value: The SHA256 of the IndexData object
        :param unique: If True, search by unique_sha256, otherwise by file_sha256
        :return: IndexData object or None if not found
        """
        try:
            if unique:
                return (
                    IndexData.objects.prefetch_related("new_ftnail")
                    .select_related("filetype")
                    .get(unique_sha256=sha_value, delete_pending=False)
                )
            return (
                IndexData.objects.prefetch_related("new_ftnail")
                .select_related("filetype")
                .get(file_sha256=sha_value, delete_pending=False)
            )
        except IndexData.DoesNotExist:
            return None

    def get_file_sha(self, fqfn) -> tuple[str, str]:
        """
        Return the SHA256 hash of the file as a hexdigest string

        Args:
            fqfn (str) : The fully qualified filename of the file to be hashed

        :return: The SHA256 hash of the file + fqfn as a hexdigest string
        """
        sha = None
        unique = None
        try:
            with open(fqfn, "rb") as filehandle:
                digest = hashlib.file_digest(filehandle, "sha256")
                sha = digest.hexdigest()
                digest.update(str(fqfn).title().encode("utf-8"))
                unique = digest.hexdigest()
        except FileNotFoundError:
            sha = None
            unique = None
            print(f"FNF (SHA256): {fqfn}")
        return sha, unique

    def get_webpath(self):
        """
        Convert the fqpndirectory to an web path
        :return:
        """
        return self.fqpndirectory.replace(
            settings.ALBUMS_PATH.lower() + r"/albums/", r""
        )

    def get_file_counts(self):
        """
        Stub method to allow the same behavior between a Index_Dir objects and IndexData object.

        :return: None
        """
        return None

    def get_dir_counts(self):
        """
        Stub method to allow the same behavior between a Index_Dir objects and IndexData object.

        :return: None
        """
        return None

    def get_bg_color(self):
        """
        Get the html / Cell background color of the file.

        Returns
        -------
        * The background hex color code of the current database entry
        """
        return self.filetype.color

    def get_view_url(self):
        """
        Generate the URL for the viewing of the current database item

        Returns
        -------
            Django URL object

        """
        # options = {}
        # parameters = []
        return reverse("view_item", args=(self.unique_sha256,))

    def get_thumbnail_url(self, size=None):
        """
        Generate the URL for the thumbnail of the current item

        Returns
        -------
            Django URL object

        """
        if size not in settings.IMAGE_SIZE and size is not None:
            size = None
        if size is None:
            size = "small"
        size = size.lower()

        url = reverse(r"thumbnail2_file", args=(self.file_sha256,)) + f"?size={size}"
        return url

    def get_download_url(self):
        """
        Generate the URL for the downloading of the current database item

        Returns
        -------
            Django URL object

        """
        return reverse("download_file") + self.name + f"?usha={self.unique_sha256}"

    def inline_sendfile(self, request, ranged=False):
        """
         Send an file either using an RangedFileResponse, or HTTP Respsonse

        Args:
             request : Dango Request Object
             ranged (boolean): is an media file (eg Mp3, Mp4, etc) that allows ranged sending

         Returns:
             object::
                 The Django response object that contains the attachment and header

         Raises:
             FileNotFoundError

         Examples
         --------
         send_thumbnail("test.png")

        """
        # from frontend.web import stream_video

        mtype = self.filetype.mimetype
        if mtype is None:
            mtype = "application/octet-stream"
        fqpn_filename = os.path.join(self.fqpndirectory, self.name)
        if not ranged:
            try:
                with open(fqpn_filename, "rb") as fh:
                    response = HttpResponse(fh.read(), content_type=mtype)
                    response["Content-Disposition"] = f"inline; filename={self.name}"
            except FileNotFoundError:
                raise Http404
        else:
            # open must be in the RangedFielRequest, to allow seeking
            try:
                response = RangedFileResponse(
                    request,
                    file=open(fqpn_filename, "rb"),  # , buffering=1024*8),
                    as_attachment=False,
                    filename=self.name,
                )
            except FileNotFoundError:
                raise Http404
        response["Content-Type"] = mtype
        return response

    class Meta:
        verbose_name = "Master Files Index"
        verbose_name_plural = "Master Files Index"
