"""
Thumbnail services for the gallery.

This is the universal code for creating and manipulating the thumbnails
used by the gallery.
"""
import core_plugin
import os
import os.path
from PIL import Image
import cStringIO


class PluginOne(core_plugin.CorePlugin):

    ACCEPTABLE_FILE_EXTENSIONS = ['.PNG']

    IMG_TAG = True

    FRAME_TAG = False

    #DEFAULT_ICON = r"/images/1431973815_text.png"

    DEFAULT_BACKGROUND = "FAEBF4"

    def create_thumbnail_from_file(self, src_filename,
                                   t_filename,
                                   t_size=None):
        if src_filename == t_filename or t_filename == None:
            return None

        if os.path.exists(t_filename):
            return None

        if t_size == None:
            return

        try:
            image_file = Image.open(src_filename)
            image_file.thumbnail((t_size, t_size), Image.ANTIALIAS)
            image_file.save(t_filename, "PNG", optimize=True)
            return True
        except IOError:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] (ioerror) is damaged." % (src_filename)
        except IndexError as detail:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] (IndexError) is damaged." % (src_filename)
            print detail
        except TypeError:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] (TypeError) is damaged." % (src_filename)

    def create_thumbnail_from_memory(self, memory_image=None,
                                     t_filename=None,
                                     t_size=None):
        if memory_image == None or t_filename == None:
            return None

        if os.path.exists(t_filename):
            return None

        if t_size == None:
            return

        try:
            #
            #   Convert this to bytes io?
            #
            image_file = Image.open(cStringIO.StringIO(memory_image))
            image_file.thumbnail((t_size, t_size), Image.ANTIALIAS)
            image_file.save(t_filename, "PNG", optimize=True)
            return True
        except IOError:
            print "save thumbnail ", t_filename
        except IndexError as detail:
            print "save thumbnail ", t_filename
            print detail
        except TypeError:
            print "save thumbnail ", t_filename

