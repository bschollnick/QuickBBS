"""
Thumbnail services for the gallery.

This is the universal code for creating and manipulating the thumbnails
used by the gallery.
"""
import core_plugin
import codecs
import markdown


class PluginOne(core_plugin.CorePlugin):

    ACCEPTABLE_FILE_EXTENSIONS = ['.TXT', '.TEXT']

    IMG_TAG = False

    FRAME_TAG = True

    DEFAULT_ICON = r"/images/1431973815_text.png"

    DEFAULT_BACKGROUND = "FDEDB1"

    def display_text_content(self, src_filename):
        if src_filename == "" or src_filename == None:
            return None

        raw_text = codecs.open(src_filename, encoding='utf-8').readlines()
        return ''.join(raw_text)#.encode('utf-8')

    def create_thumbnail_from_file(self, src_filename,
                                   t_filename,
                                   t_size=None):
        return None

    def create_thumbnail_from_memory(self, memory_image=None,
                                     t_filename=None,
                                     t_size=None):
        return None
