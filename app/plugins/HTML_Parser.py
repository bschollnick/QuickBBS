"""
Thumbnail services for the gallery.

This is the universal code for creating and manipulating the thumbnails
used by the gallery.
"""
import core_plugin
import codecs

class PluginOne(core_plugin.CorePlugin):

    ACCEPTABLE_FILE_EXTENSIONS = ['.HTM', '.HTML']

    IMG_TAG = False

    FRAME_TAG = True

    DEFAULT_ICON = r"/images/1431973779.png"

    DEFAULT_BACKGROUND = "FEF7DF"

    def display_text_content(self, src_filename):
        if src_filename == "" or src_filename == None:
            return None

        raw_text = codecs.open(src_filename, encoding='utf-8').readlines()
        return ''.join(raw_text)#.encode('utf-8')

