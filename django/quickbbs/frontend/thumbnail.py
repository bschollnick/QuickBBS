"""
Core Plugin for Gallery
"""

##############################################################################
import cStringIO
import exceptions
import os
import os.path
import time
from PIL import Image
import config
from functools import partial
from multiprocessing.dummy import Pool
from subprocess import call

pool = Pool(5) # two concurrent commands at a time

THUMBNAIL_DB = {}
THUMBNAIL_DB.update({'BMP':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'DIB':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'EPS':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'GIF':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'MSP':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'TIF':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'TIFF':{'IMG_TAG':True, 'FRAME_TAG':False,
                             'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                             'ICON':""}})
THUMBNAIL_DB.update({'JPG':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'JPEG':{'IMG_TAG':True, 'FRAME_TAG':False,
                             'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                             'ICON':""}})
THUMBNAIL_DB.update({'JPE':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'JIF':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'JFIF':{'IMG_TAG':True, 'FRAME_TAG':False,
                             'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                             'ICON':""}})
THUMBNAIL_DB.update({'JFI':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'PNG':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'PCX':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FAEBF4',
                            'ICON':""}})
THUMBNAIL_DB.update({'PDF':{'IMG_TAG':True, 'FRAME_TAG':False,
                            'CONTAINER':False, 'BACKGROUND': '#FDEDB1',
                            'ICON':""}})

THUMBNAIL_REBUILD_TIME = (24 * 60 * 60) * 14  # 2 weeks

def check_for_ghostscript():
    """
    Check and return path to ghostscript, returns None
    if is not installed.
    """
    from twisted.python.procutils import which
    if which("gs") == []:
        print "Ghostscript is not installed."
        return None
    return which("gs")[0]

GHOSTSCRIPT_INSTALLED = check_for_ghostscript()
THUMBNAIL_REBUILD_TIME = (24 * 60 * 60) * 14  # 2 weeks

class Thumbnails(object):
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

    def display_text_content(self, src_filename):
        """
        Initialization for Core Plugin.

        """
        raise NotImplementedError("Subclass must implement abstract method")

    def make_tnail_name(self, filename=None):
        tnail_name = {}
        tnail_name["small"] = filename + "_thumb%s.png" %\
                              config.configdata["configuration"]["sm_thumb"]
                              # gallery view ~300
        tnail_name["medium"] = filename + "_thumb%s.png" %\
                              config.configdata["configuration"]["med_thumb"]
                               # mobile view ~740
        tnail_name["large"] = filename + "_thumb%s.png" %\
                              config.configdata["configuration"]["lg_thumb"]
                              # large view ~1024
        return tnail_name

    def make_tnail_fsname(self, src_filename=None):
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
        if src_filename is None:
            raise RuntimeError("No Source file given.")

        tnail_target = src_filename.replace("%salbums%s" % (os.sep, os.sep), "%sthumbnails%s" % (os.sep, os.sep))
        tnail_name = self.make_tnail_name(tnail_target)
        tnail_name["small"] = os.path.join(tnail_target, tnail_name["small"])
        tnail_name["medium"] = os.path.join(tnail_target, tnail_name["medium"])
        tnail_name["large"] = os.path.join(tnail_target, tnail_name["large"])
        return tnail_name

    def does_thumbnail_already_exist(self, thumbfilename):
        try:
            return os.path.exists(thumbfilename)
        except exceptions.IOError:
            return False

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
            if time.time() - THUMBNAIL_REBUILD_TIME > t_modified:
                # if the current timestamp minus 2 weeks, is greater then the
                # file's
                os.remove(thumbfilename)


    def create_pdf_thumbnail(self, src_filename,
                             t_filename,
                             t_size=None):
        gs_command = '''gs -q -dQUIET -dPARANOIDSAFER \
        -dBATCH -dNOPAUSE \
        -dNOPROMPT -dMaxBitmap=500000000 -dLastPage=1 -dAlignToPixels=0 \
        -dGridFitTT=0 -sDEVICE=jpeg -dTextAlphaBits=4 -dGraphicsAlphaBits=4\
        -g%ix%i -dPDFFitPage -dORIENT1=false -sOutputFile=$'%s' -f$'%s' '''
        if  src_filename == None:
            raise RuntimeError("No Source Filename was not specified")

        if  t_filename == None:
            raise RuntimeError("The Target is not specified")

        if src_filename == t_filename:
            raise RuntimeError("The source is the same as the target.")

        if os.path.exists(t_filename):
            return None

        if t_size == None:
            raise RuntimeError("No Target size is defined")

        if not GHOSTSCRIPT_INSTALLED:
            return ''

        pool.imap(partial(call, shell=True), [gs_command % (t_size, t_size, t_filename, src_filename)])

    def create_thumbnail_from_file(self, src_filename,
                                   t_filename=None,
                                   t_size=None):
        if os.path.exists(t_filename):
            return False
        elif src_filename == t_filename:
            raise RuntimeError("The source is the same as the target.")
        elif t_filename is None:
            raise RuntimeError("The Target is not specified")
        elif t_size is None:
            raise RuntimeError("No Target size is defined")

        if src_filename.lower().endswith(".pdf"):
            print "trying to pdf convert"
            self.create_pdf_thumbnail(src_filename,
                                      t_filename,
                                      t_size)

        try:
            image_file = Image.open(src_filename)
        except IOError:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] (ioerror) is damaged." % (src_filename)
            return False
        except IndexError as detail:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] (IndexError) is damaged." % (src_filename)
            print detail
            return False
        except TypeError:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The File [%s] (TypeError) is damaged." % (src_filename)
            return False

        try:
            if image_file.mode != "RGB":
                new_image = image_file.convert('RGB')
            image_file.thumbnail([int(t_size), int(t_size)], Image.ANTIALIAS)
        except IOError:
            print "File thumbnail ", src_filename
            print "save thumbnail ", t_filename
            print "The thumbnail for %s could not be created (IO Error)." % (src_filename)
            return False

        image_file.save(t_filename, "PNG", optimize=True)
        pool.imap(image_file.save, [t_filename, "PNG", True])

        return True

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
        if memory_image is None:
            raise RuntimeError("No Memory Image is provided.")
        elif t_filename is None:
            raise RuntimeError("The Target is not specified")
        elif os.path.exists(t_filename):
            return False
        elif t_size is None:
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
        return False

    def extract_from_container(self, container_file=None,
                               fn_to_extract=None,
                               t_size=None):
        """
        Initialization for Core Plugin.

        """
        pass
