"""
Core Plugin for Gallery
"""

##############################################################################
from yapsy.IPlugin import IPlugin


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

    @classmethod
    def display_text_content(cls, src_filename):
        """
        Initialization for Core Plugin.

        """
        raise NotImplementedError("Subclass must implement abstract method")

    @classmethod
    def create_thumbnail_from_file(cls, src_filename,
                                   t_filename,
                                   t_size=None):
        """
        Initialization for Core Plugin.

        """
        raise NotImplementedError("Subclass must implement abstract method")

    @classmethod
    def create_thumbnail_from_memory(cls, memory_image=None,
                                     t_filename=None,
                                     t_size=None):
        """
        Initialization for Core Plugin.

        """
        raise NotImplementedError("Subclass must implement abstract method")

    @classmethod
    def extract_from_container(cls, container_file=None,
                                    fn_to_extract=None,
                                    t_size=None):
        """
        Initialization for Core Plugin.

        """
        raise NotImplementedError("Subclass must implement abstract method")
