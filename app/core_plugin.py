"""
Core Plugin for Gallery
"""

##############################################################################
from yapsy.IPlugin import IPlugin
import config
import os, os.path
import sys
import traceback
import time

class CorePlugin(IPlugin):
    """
        Subclassed core plugin.


        * ACCEPTABLE_FILE_EXTENSIONS is a list, that contains the (UPPERCASE),
            File Extensions (DOTTED format, e.g. .GIF, not GIF) that this
            plugin will manage.

        * IMG_TAG - BOOLEAN - (e.g. .PNG, .GIF, .JPG)
            * True - This plugin can make an IMAGE based thumbnail, for this
                file type
            * False - This plugin will not make an image thumbnail

        * FRAME_TAG - BOOLEAN - (e.g. .TEXT, .MARKDOWN, etc)
            * True - This plugin will return an TEXT based stream. That should
                be displayed in the browser window.

            * False - This plugin will not make an image thumbnail

        * DEFAULT_ICON - String - The Default thumbnail image to use, if
            IMG_TAG is False

        * DEFAULT_BACKGROUND - String - The background of the table cell, for
            this file format.

        * CONTAINER - BOOLEAN - (e.g. ZIP, RAR) - This plugin returns an
            memory_image of the contents.

    """
    def __init__(self):
        """
        Initialization for Core Plugin.

        """
        IPlugin.__init__(self)

    ACCEPTABLE_FILE_EXTENSIONS = None

    IMG_TAG = False

    FRAME_TAG = False

    CONTAINER = False

    THUMBNAIL_REBUILD_TIME = (24 * 60 * 60) * 14  # 2 weeks


    @classmethod
    def display_text_content(cls, src_filename):
        """
        Initialization for Core Plugin.

        """
        raise NotImplementedError("Subclass must implement abstract method")

    @classmethod
    def generate_tnail_name(cls, src_filename=None, clean_filename=None):
        """
        Generate the thumbnail name for the source file.

        input -
                src_filename - The FQFN of the source file
                clean_filename - Pointer to the filename cleaning function
                                 that should be used.

        output - A dictionary, of the small, medium, and large thumbnails for
                 the thumbnail file.  The thumbnail will have the albums
                 directory replaced with the thumbnails directory name.
        """
        if src_filename == None:
            raise RuntimeError("No Source file given.")

        if clean_filename != None:
            pathname, filename = os.path.split(src_filename)
            src_filename = os.path.join(pathname, clean_filename(filename))

        tnail_name = {}
        tnail_target = src_filename.replace("/albums/", "/thumbnails/")
        tnail_name["small"] = tnail_target + "_thumb%s.png" %\
                              config.SETTINGS["small_thumbnail"]
                              # gallery view ~300
        tnail_name["medium"] = tnail_target + "_thumb%s.png" %\
                               config.SETTINGS["medium_thumbnail"]
                               # mobile view ~740
        tnail_name["large"] = tnail_target + "_thumb%s.png" %\
                              config.SETTINGS["large_thumbnail"]
                              # large view ~1024
        return tnail_name

    @classmethod
    def does_thumbnail_already_exist(self, thumbfilename):
        try:
            return os.path.exists(thumbfilename)
        except exceptions.IOError:
            return False

    @classmethod
    def timecheck_thumbnail_file(self, thumbfilename):
        """
            Check the thumbnail file, and see if it is older than
            the rebuild time.

            If it is, it will be deleted, so that it can be regenerated.
        """
        if self.does_thumbnail_already_exist(thumbfilename):
            # File exists
            t_modified = os.path.getmtime(thumbfilename)
            # Get modified time stamps in seconds
            if time.time() - self.THUMBNAIL_REBUILD_TIME > t_modified:
                # if the current timestamp minus 2 weeks, is greater then the
                # file's
                os.remove(thumbfilename)


    @classmethod
    def create_thumbnail_from_file(cls, src_filename,
                                   t_filename,
                                   t_size=None):
        """
        Initialization for Core Plugin.

        """
        raise NotImplementedError("%s - create_thumbnail_from_file - Subclass must implement abstract method" % cls.ACCEPTABLE_FILE_EXTENSIONS)

    @classmethod
    def create_thumbnail_from_memory(cls, memory_image=None,
                                     t_filename=None,
                                     t_size=None):
        """
        Initialization for Core Plugin.

        """
        raise NotImplementedError("%s - create_thumbnail_from_memory - Subclass must implement abstract method" % cls.ACCEPTABLE_FILE_EXTENSIONS)

    @classmethod
    def extract_from_container(cls, container_file=None,
                               fn_to_extract=None,
                               t_size=None):
        """
        Initialization for Core Plugin.

        """
        raise NotImplementedError("%s - extract from container - Subclass must implement abstract method" % cls.ACCEPTABLE_FILE_EXTENSIONS)
