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
    ACCEPTABLE_FILE_EXTENSIONS = ['.JPG', '.JPEG', '.JPE',
                                  '.JIF', '.JFIF', '.JFI']

    IMG_TAG = True

    FRAME_TAG = False

    CONTAINER = False

    #DEFAULT_ICON = r"/images/1431973815_text.png"

    DEFAULT_BACKGROUND = "FAEBF4"

    def create_thumbnail_from_file(self, src_filename,
                                   t_filename,
                                   t_size=None):
        """
        Create a thumbnail from a source file.

        inputs -

            * src_filename - String - This is the fully qualified filepathname
                of the file to be thumbnailed.

            * t_filename - String - This is the fully qualified filepathname
                of the thumbnail file to be created.

            * t_size - integer - This is the maximum size of the thumbnail.
                The thumbnail will be t_size x t_size (e.g. 300 x 300)

        output -

            * The thumbnail file that is created at the t_filename location.
        """
        if src_filename == t_filename:
            raise RuntimeError("The source is the same as the target.")

        if  t_filename == None:
            raise RuntimeError("The Target is not specified")

        if os.path.exists(t_filename):
            return None

        if t_size == None:
            raise RuntimeError("No Target size is defined")


        try:
            image_file = Image.open(src_filename)
        except IOError:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "IOError opening the file[%s] ." % (src_filename)
        except IndexError as detail:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] generated an IndexError." % (src_filename)
            print detail
        except TypeError:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] is not the proper type (TypeError)." % (src_filename)

        image_file.thumbnail((t_size, t_size), Image.ANTIALIAS)

        try:
            if image_file.mode != "RGB":
                new_image = image_file.convert('RGB')
                new_image.save(t_filename, "PNG", optimize=True)
            else:
                image_file.save(t_filename, "PNG", optimize=True)
            return True
        except IOError:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "IOError writing the file[%s] ." % (src_filename)
        except IndexError as detail:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] (IndexError) is damaged." % (src_filename)
            print detail
        except TypeError:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] (TypeError) is damaged." % (src_filename)

##########################################################################
    def create_thumbnail_from_memory(self, memory_image=None,
                                     t_filename=None,
                                     t_size=None):
        """
        Create a thumbnail from a memory image of the file.

        inputs -

            * memory_image - blob - This is the blob of image data, typically
                a blob that has been read from a file, or a zip, etc.

            * t_filename - String - This is the fully qualified filepathname
                of the thumbnail file to be created.

            * t_size - integer - This is the maximum size of the thumbnail.
                The thumbnail will be t_size x t_size (e.g. 300 x 300)

        output -

            * The thumbnail file that is created at the t_filename location.
        """
        if memory_image == None:
            raise RuntimeError("No Memory Image is provided.")

        if  t_filename == None:
            raise RuntimeError("The Target is not specified")

        if os.path.exists(t_filename):
            return None

        if t_size == None:
            raise RuntimeError("No Target size is defined")

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
