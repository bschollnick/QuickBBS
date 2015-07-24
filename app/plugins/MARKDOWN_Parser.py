"""
Thumbnail services for the gallery.

This is the universal code for creating and manipulating the thumbnails
used by the gallery.
"""
import core_plugin
import codecs
import markdown


class PluginOne(core_plugin.CorePlugin):

    ACCEPTABLE_FILE_EXTENSIONS = ['.MARKDOWN', '.MARK', '.MD']

    IMG_TAG = False

    FRAME_TAG = True

    DEFAULT_ICON = r"/images/markdown-mark.png"

    DEFAULT_BACKGROUND = "fef7df"



    def display_text_content(self, src_filename):
        if src_filename == "" or src_filename == None:
            return None

        raw_text = codecs.open(src_filename, encoding='utf-8').readlines()
        return markdown.markdown(''.join(raw_text))#.encode('utf-8')

