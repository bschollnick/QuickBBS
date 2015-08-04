"""
Thumbnail services for the gallery.

This is the universal code for creating and manipulating the thumbnails
used by the gallery.
"""
import core_plugin
import codecs

class PluginOne(core_plugin.CorePlugin):
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
    """

    ACCEPTABLE_FILE_EXTENSIONS = ['.HTM', '.HTML']

    IMG_TAG = False

    FRAME_TAG = True

    DEFAULT_ICON = r"/images/1431973779.png"

    DEFAULT_BACKGROUND = "FEF7DF"

    def web_view(self, src_filename):
        """
        Create a web acceptable view of the file.

        In this case, read & process the src_filename,
        and then return this as a string.
        """
        if src_filename == None or src_filename == "":
             raise RuntimeError("No Source Filename was provided.")

        raw_text = codecs.open(src_filename, encoding='utf-8').readlines()
        return ''.join(raw_text)#.encode('utf-8')

