"""
Django Models for quickbbs
"""

import hashlib
import io
import mimetypes
import os
import pathlib
import time
import uuid

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.http import FileResponse, Http404, HttpResponse
from django.urls import reverse
from ranged_fileresponse import RangedFileResponse

import thumbnails.models
from filetypes.models import FILETYPE_DATA, filetypes
from quickbbs.natsort_model import NaturalSortField


def convert_text_to_md5_hdigest(text):
    """
    convert a text string to a md5 hash.  Text string is title cased, whitespace stripped, and
    encoded as an utf-16 string.  The hash is exported as the hex digest.

    This is used as key for database lookups, and is standardized using this helper.

    :param text:String
    :return: 32 character md5 hexadecimal string
    """
    return hashlib.md5(text.title().strip().encode("utf-16")).hexdigest()


def is_valid_uuid(uuid_to_test, version=4):
    """
    Check if uuid_to_test is a valid UUID.
    https://stackoverflow.com/questions/19989481

    Args:
        uuid_to_test (str) - UUID code to validate
        version (int) - UUID version to validate against (eg  1, 2, 3, 4)

    Returns:
        boolean:
            `True` if uuid_to_test is a valid UUID, otherwise `False`.

    Raises:
        None

    Examples
    --------
    >>> is_valid_uuid('c9bf9e57-1685-4c89-bafb-ff5af830be8a')
    True
    >>> is_valid_uuid('c9bf9e58')
    False
    """
    try:
        uuid_obj = uuid.UUID(uuid_to_test, version=version)
    except:
        return False

    return str(uuid_obj) == uuid_to_test


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

    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    fqpndirectory = models.CharField(
        db_index=False, max_length=384, default="", unique=True, blank=True
    )  # FQFN of the file itself
    # WebPath_md5 = models.CharField(db_index=True, max_length=32, unique=False)
    dir_name_md5 = models.CharField(db_index=True, max_length=32, unique=False)
    # DirName is the just the directory name (eg test1)
    combined_md5 = models.CharField(db_index=True, max_length=32, unique=True)
    # Combined is the FQPN md5  (eg /var/albums/test/test1)
    parent_dir_md5 = models.CharField(db_index=True, max_length=32, unique=False)
    # Is the FQPN of the parent directory (eg /var/albums/test)
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
    ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
    delete_pending = models.BooleanField(
        default=False, db_index=True
    )  # File is to be deleted,
    filetype = models.ForeignKey(
        filetypes,
        to_field="fileext",
        on_delete=models.CASCADE,
        db_index=True,
        default=".dir",
    )
    small_thumb = models.BinaryField(default=b"")

    @staticmethod
    def normalize_fqpn(fqpn_directory):
        """
        Normalize the directory structure fully qualified pathname for conversion to a md5
        hexdigest string.
        :param fqpn_directory: String, the fully qualified pathname for the directory
        :return: normalized string, all lowercase, whitespace stripped, ending with os.sep
        """
        fqpn_directory = fqpn_directory.lower().strip()
        if not fqpn_directory.endswith(os.sep):
            fqpn_directory = fqpn_directory + os.sep
        return fqpn_directory

    @staticmethod
    def add_directory(fqpn_directory, thumbnail=b""):
        """
        Create a new directory entry
        :param fqpn_directory: The fully qualified pathname for the directory
        :param thumbnail: thumbnail image to store for the thumbnail/cover art
        :return: Database record
        """
        Path = pathlib.Path(fqpn_directory)
        fqpn_directory = IndexDirs.normalize_fqpn(str(Path.resolve()))
        parent_dir = IndexDirs.normalize_fqpn(str(Path.parent.resolve()))
        filename_seg = str(Path.name)

        # dir_seg, filename_seg = os.path.split(fqpn_directory)
        new_rec = IndexDirs()
        new_rec.fqpndirectory = fqpn_directory
        new_rec.dir_name_md5 = convert_text_to_md5_hdigest(
            IndexDirs.normalize_fqpn(filename_seg)
        )
        new_rec.combined_md5 = convert_text_to_md5_hdigest(
            IndexDirs.normalize_fqpn(fqpn_directory)
        )
        new_rec.parent_dir_md5 = convert_text_to_md5_hdigest(parent_dir)
        new_rec.uuid = uuid.uuid4()
        #        new_rec.FileCount = FileCount
        #        new_rec.DirCount = DirCount
        new_rec.small_thumb = thumbnail
        new_rec.lastmod = os.path.getmtime(new_rec.fqpndirectory)
        new_rec.lastscan = time.time()
        new_rec.filetype = filetypes(fileext=".dir")
        new_rec.save()
        return new_rec

    @property
    def numdirs(self):
        """
        Place holder for backward compatibility reasons (matching the numdirs attribute
        of IndexData)
        :return: None
        """
        return None

    @property
    def numfiles(self):
        """
        Place holder for backward compatibility reasons (matching the numdirs attribute
        of IndexData)
        :return: None
        """
        return None

    @property
    def name(self):
        """
        Return the directory name of the directory.
        :return: String
        """
        return str(pathlib.Path(self.fqpndirectory).name)

    @staticmethod
    def delete_directory(fqpn_directory):
        """
        Delete the Index_Dirs data for the fqpn_directory, and ensure that all
        IndexData records are wiped as well.
        :param fqpn_directory: text string of fully qualified pathname of the directory
        :return:
        """
        # pylint: disable-next=import-outside-toplevel
        from cache.models import Cache_Storage

        combined_md5 = convert_text_to_md5_hdigest(
            IndexDirs.normalize_fqpn(fqpn_directory)
        )
        Cache_Storage.remove_from_cache_name(fqpn_directory)
        IndexDirs.objects.filter(combined_md5=combined_md5).delete()
        # IndexData.objects.filter(parent_dir_id=combined_md5).delete()
        # This should be redundant, but need to test to verify.

    def get_file_counts(self):
        """
        Return the number of files that are in the database for the current directory
        :return: Integer - Number of files in the database for the directory
        """
        return IndexData.objects.filter(
            parent_dir=self.pk, delete_pending=False
        ).count()

    def get_dir_counts(self):
        """
        Return the number of directories that are in the database for the current directory
        :return: Integer - Number of directories
        """
        return IndexDirs.objects.filter(
            parent_dir_md5=self.combined_md5, delete_pending=False
        ).count()

    def get_count_breakdown(self):
        """
        Return the count of items in the directory, broken down by filetype.
        :return: dictionary, where the key is the filetype (e.g. "dir", "jpg", "mp4"),
        and the value is the number of items of that filetype.
        A special "all_files" key is used to store the # of all items in the directory (except
        for directories).  (all_files is the sum of all file types, except "dir")
        """
        d_files = IndexData.objects.filter(
            parent_dir_md5__combined_md5=self.combined_md5
        )
        totals = {}
        for key in FILETYPE_DATA.keys():
            totals[key[1:]] = d_files.filter(filetype__fileext=key).count()
        totals["dir"] = self.get_dir_counts()
        # totals["dir"] = IndexDirs.objects.filter(
        #    parent_dir_md5=self.combined_md5, delete_pending=False
        # ).count()
        # totals["all_files"] = d_files.filter().count() - totals["dir"]
        totals["all_files"] = self.get_file_counts()
        return totals

    def return_parent_directory(self):
        """
        Return the database object of the parent directory to the current directory
        :return: database record of parent directory
        """
        parent_dir = IndexDirs.objects.filter(combined_md5=self.parent_dir_md5)
        return parent_dir

    @staticmethod
    def search_for_directory(fqpn_directory):
        """
        Return the database object matching the fqpn_directory
        :param fqpn_directory: The fully qualified pathname of the directory
        :return: A boolean representing the success of the search, and the resultant record
        """
        Path = pathlib.Path(fqpn_directory)
        fqpn_directory = IndexDirs.normalize_fqpn(str(Path.resolve()))
        query = IndexDirs.objects.filter(
            combined_md5=convert_text_to_md5_hdigest(fqpn_directory),
            delete_pending=False,
            ignore=False,
        )
        if query.exists():
            record = query[0]
            return (True, record)
        return (False, query)  # return an empty query set

    def files_in_dir(self, sort=0):
        """
        Return the files in the current directory
        :param sort: The sort order of the files (0-2)
        :return: The sorted query of files
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.database import SORT_MATRIX

        files = (
            IndexData.objects.select_related("filetype")
            .filter(parent_dir=self.pk, delete_pending=False)
            .order_by(*SORT_MATRIX[sort])
        )
        return files.count(), files

    def dirs_in_dir(self, sort=0):
        """
        Return the directories in the current directory
        :param sort: The sort order of the directories (0-2)
        :return: The sorted query of directories
        """
        # necessary to prevent circular references on startup
        # pylint: disable-next=import-outside-toplevel
        from frontend.database import SORT_MATRIX

        dir_scan = str((pathlib.Path(self.fqpndirectory)).resolve())
        dir_scan = IndexDirs.normalize_fqpn(dir_scan)
        dir_scan_md5 = convert_text_to_md5_hdigest(dir_scan)
        # dirs = IndexDirs.objects.filter(combined_md5=self.combined_md5, delete_pending=False)
        dirs = IndexDirs.objects.filter(
            parent_dir_md5=dir_scan_md5, delete_pending=False
        ).order_by(*SORT_MATRIX[sort])
        return dirs.count(), dirs

    def get_view_url(self):
        """
        Generate the URL for the viewing of the current database item

        Returns
        -------
            Django URL object

        """
        options = {}
        options["i_uuid"] = str(self.uuid)
        webpath = self.fqpndirectory.replace(
            settings.ALBUMS_PATH.lower() + r"/albums/", r""
        )
        return reverse("directories") + webpath

    def get_bg_color(self):
        """
        Get the html / Cell background color of the file.

        Returns
        -------
        * The background hex color code of the current database entry
        """
        return self.filetype.color

    # pylint: disable-next=unused-argument
    def get_thumbnail_url(self, size=None):
        """
        Generate the URL for the thumbnail of the current item
        The argument is unused, included for API compt. between IndexData & IndexDirs

        Returns
        -------
            Django URL object

        """
        return reverse(r"thumbnail_dir", args=(self.uuid,))

    def send_thumbnail(self):
        """
         Output a http response header, for an image attachment.

        Args:
             filename (str): The filename to be sent with the thumbnail

         Returns:
             object::
                 The Django response object that contains the attachment and header

         Raises:
             None

         Examples
         --------
         return_img_attach("test.png", img_data)

         # https://stackoverflow.com/questions/36392510/django-download-a-file
         # https://stackoverflow.com/questions/27712778/
         #               video-plays-in-other-browsers-but-not-safari
         # https://stackoverflow.com/questions/720419/
         #               how-can-i-find-out-whether-a-server-supports-the-range-header

        """
        mtype = "application/octet-stream"
        response = FileResponse(
            io.BytesIO(self.small_thumb),
            content_type=mtype,
            as_attachment=False,
            filename=os.path.basename(self.fqpndirectory) + ".jpg",
        )
        response["Content-Type"] = mtype
        response["Content-Length"] = len(self.small_thumb)
        return response


class Thumbnails_Files(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    FilePath = models.CharField(
        db_index=True, max_length=384, default=None
    )  # FQFN of the file itself
    FileName = models.CharField(
        db_index=True, max_length=384, default=None
    )  # FQFN of the file itself
    FileSize = models.BigIntegerField(default=-1)

    small_thumb = models.BinaryField(default=b"")
    medium_thumb = models.BinaryField(default=b"")
    large_thumb = models.BinaryField(default=b"")

    class Meta:
        verbose_name = "Image File Thumbnails Cache"
        verbose_name_plural = "Image File Thumbnails Cache"
        constraints = [
            models.UniqueConstraint(
                fields=["FileName", "FilePath"], name="unique_thumb_files"
            )
        ]
        # File Workflow:
        #
        #   When checking for a thumbnail, if Thumbnail_ID == 0, then generate the new thumbnails,
        #   and set the Thumbnail_ID for the file.
        #
        #   If the file has been flagged as changed, then:
        #       Grab the Thumbnail_ID record and set Flag_For_Regeneration to True
        #
        #   If the Thumbnail_ID record is set, check the Thumbnail_ID record for
        #   Flag_For_Regeneration, and if True, then Regenerate the Thumbnails.


class Thumbnails_Archives(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    zipfilepath = models.CharField(
        db_index=True, max_length=384, default="", blank=True
    )  # FQFN of the file itself

    FilePath = models.CharField(
        db_index=True, max_length=384, default=None
    )  # FQFN of the file itself
    FileName = models.CharField(
        db_index=True, max_length=384, default=None
    )  # FQFN of the file itself
    page = models.IntegerField(default=0)  # The
    FileSize = models.BigIntegerField(default=-1)
    small_thumb = models.BinaryField(default=b"")
    medium_thumb = models.BinaryField(default=b"")
    large_thumb = models.BinaryField(default=b"")

    class Meta:
        verbose_name = "Archive Thumbnails Cache"
        verbose_name_plural = "Archive Thumbnails Cache"

        constraints = [
            models.UniqueConstraint(
                fields=["FileName", "FilePath", "zipfilepath"], name="unique_archives"
            )
        ]


class IndexData(models.Model):
    """
    The Master Index for All files in the Gallery.  (See IndexDirs for the counterpart
    for Directories)
    """

    id = models.AutoField(primary_key=True)
    uuid = models.UUIDField(
        default=None, null=True, editable=False, db_index=True, blank=True
    )
    # Stored as Unix TimeStamp (ms)
    lastscan = models.FloatField(db_index=True)
    lastmod = models.FloatField(db_index=True)  # Stored as Unix TimeStamp (ms)
    name = models.CharField(db_index=True, max_length=384, default=None)
    # FQFN of the file itself
    # sortname = models.CharField(editable=False, max_length=384, default='')
    name_sort = NaturalSortField(for_field="name", max_length=384, default="")
    size = models.BigIntegerField(default=0)  # File size
    # The # of files in this directory
    #    numfiles = models.IntegerField(default=0)
    #    numdirs = models.IntegerField(
    #        default=0
    #    )  # The # of Children Directories in this directory
    #    count_subfiles = models.BigIntegerField(default=0)  # the # of subfiles in archive
    fqpndirectory = models.CharField(default=0, db_index=True, max_length=384)
    # Directory of the file, lower().replace("//", "/"), ensure it is path, and not path + filename
    parent_dir = models.ForeignKey(
        IndexDirs, on_delete=models.CASCADE, null=True, default=None
    )
    is_animated = models.BooleanField(default=False, db_index=True)
    ignore = models.BooleanField(default=False, db_index=True)  # File is to be ignored
    delete_pending = models.BooleanField(
        default=False, db_index=True
    )  # File is to be deleted,
    filetype = models.ForeignKey(
        filetypes,
        to_field="fileext",
        on_delete=models.CASCADE,
        db_index=True,
        default=".none",
    )
    is_generic_icon = models.BooleanField(
        default=False, db_index=False
    )  # icon is a generic icon

    file_tnail = models.OneToOneField(
        Thumbnails_Files,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

    # https://stackoverflow.com/questions/38388423
    archives = models.OneToOneField(
        Thumbnails_Archives,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

    ownership = models.OneToOneField(
        Owners,
        on_delete=models.CASCADE,
        db_index=True,
        default=None,
        null=True,
        blank=True,
    )

    def get_webpath(self):
        """
        Convert the fqpndirectory to an web path
        :return:
        """
        return self.fqpndirectory.replace(
            settings.ALBUMS_PATH.lower() + r"/albums/", r""
        )

    # def write_to_db_entry(self, fileentry, fqpn, version=4):
    #     """
    #     The write_to_db_entry function writes the fileentry to the IndexData database.
    #     It takes a scandir entry and a fully qualified pathname as parameters.
    #     The function then determines if it is dealing with a directory or not, and
    #     then creates an appropriate FileType object for that file extension.
    #     If it is not an image, video, audio or archive type of file (as defined in
    #     the FILETYPE_DATA dictionary), then we will just create a generic FileType object
    #     that has no other attributes than being there.
    #
    #     :param self: Reference the class instance
    #     :param fileentry: scandir entry
    #     :param fqpn: Pass the fully qualified pathname of the file to be scanned
    #     :param version=4: Generate a uuid version 4
    #     :return: None
    #     """
    #     """
    #     Start of Unified code.  WIP
    #     Intended to be the glue that writes the database entry.
    #     Parameters
    #     ----------
    #     fileentry : The scandir entry
    #     fqpn : The fully qualified pathname of the file
    #     version : uuid version number
    #
    #     Returns
    #     -------
    #         None:
    #
    #     """
    #     if self.uuid is None:
    #         self.uuid = uuid.uuid(version=version)
    #
    #     fext = os.path.splitext(fileentry.name)[1].lower()
    #     if fext == "":
    #         fext = ".none"
    #     self.filetypes(fileext=fext)
    #
    #     if fileentry.is_dir():
    #         self.filetypes(fileext=".dir")
    #         fext = ".dir"
    #
    #     if fext in [".gif"] and filetype_models.FILETYPE_DATA[fext]["is_image"]:
    #         try:
    #             animated = Image.open(os.path.join(fqpn, filename)).is_animated
    #             force_save = True
    #         except AttributeError:
    #             print(f"{fext} is not an animated GIF")
    #
    #     numfiles = 0
    #     numdirs = 0
    #     lastscan = time.time()

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
        options = {}
        options["i_uuid"] = str(self.uuid)
        parameters = []
        return reverse("new_viewitem", kwargs=options) + "".join(parameters)

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

        # options = {"i_uuid": str(self.uuid)}
        url = reverse(r"thumbnail_file", args=(self.uuid,)) + f"?size={size}"
        return url

    def get_download_url(self):
        """
        Generate the URL for the downloading of the current database item

        Returns
        -------
            Django URL object

        """
        return reverse("download") + f"?UUID={self.uuid}"
        # null = System Owned

    def send_thumbnail(self, filename=None, fext_override=None, size="small"):
        """
         Output a http response header, for an image attachment.

        Args:
             filename (str): The filename to be sent with the thumbnail
             fext_override (str): Filename extension to use instead of the original file's ext
             size (str): The size string of the thumbnail to send (small, medium, large)

         Returns:
             object::
                 The Django response object that contains the attachment and header

         Raises:
             None

         Examples
         --------
         send_thumbnail("test.png")

        References:
            https://stackoverflow.com/questions/36392510/django-download-a-file
            https://stackoverflow.com/questions/27712778/
                   video-plays-in-other-browsers-but-not-safari
            https://stackoverflow.com/questions/720419/
                    how-can-i-find-out-whether-a-server-supports-the-range-header

        """

        def get_sized_tnail(size="small", tnail=None):
            """
            Helper to get and pick the right size for the thumbnail to be sent
            :param size: The size string
            :param tnail: The thumbnail record to be checked
            :return: the blob that contains the image data
            """
            blobdata = b""
            if tnail is None:
                return b""
            match size.lower():
                case "small":
                    blobdata = tnail.small_thumb
                case "medium":
                    blobdata = tnail.medium_thumb
                case "large":
                    blobdata = tnail.large_thumb
                case _:
                    blobdata = b""
            return blobdata

        if fext_override is not None:
            mimetype_filename = os.path.join(self.name, fext_override)
        elif filename:
            mimetype_filename = filename
        else:
            mimetype_filename = None

        if mimetype_filename:
            mtype = mimetypes.guess_type(mimetype_filename)[0]
        else:
            mtype = "application/octet-stream"
        if self.file_tnail is not None:
            blob = get_sized_tnail(size=size, tnail=self.file_tnail)
        response = FileResponse(
            io.BytesIO(blob),
            content_type=mtype,
            as_attachment=False,
            filename=filename or self.name,
        )
        response["Content-Type"] = mtype
        response["Content-Length"] = len(blob)
        return response

    # @method_decorator(cache_control(private=True))
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
        fqpn_filename = os.path.join(self.fqpndirectory, self.name)
        try:
            mtype = self.filetype.mimetype
            if mtype is None:
                mtype = "application/octet-stream"
            with open(fqpn_filename, "rb") as fh:
                if ranged:
                    # open must be in the RangedFielRequest, to allow seeking
                    response = RangedFileResponse(
                        request,
                        file=open(fqpn_filename, "rb"),  # , buffering=1024*8),
                        as_attachment=False,
                        filename=self.name,
                    )
                    response["Content-Type"] = mtype
                else:
                    response = HttpResponse(fh.read(), content_type=mtype)
                    response["Content-Disposition"] = f"inline; filename={self.name}"
            return response
        except FileNotFoundError:
            pass

        raise Http404

    class Meta:
        verbose_name = "Master Index"
        verbose_name_plural = "Master Index"

        constraints = [
            models.UniqueConstraint(
                fields=["name", "fqpndirectory"], name="unique name directory"
            )
        ]
