"""
Thumbnail services for the gallery.

This is the universal code for creating and manipulating the thumbnails
used by the gallery.
"""
import core_plugin
import os
import os.path

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

class PluginOne(core_plugin.CorePlugin):

    ACCEPTABLE_FILE_EXTENSIONS = ['.PDF']
    IMG_TAG = True
    FRAME_TAG = False

#    DEFAULT_ICON = r"/images/1431973815_text.png"

    DEFAULT_BACKGROUND = "FDEDB1"

    def create_thumbnail_from_file(self, src_filename,
                                   t_filename,
                                   t_size=None):
        gs_command = '''gs -q -dQUIET -dPARANOIDSAFER \
        -dBATCH -dNOPAUSE \
        -dNOPROMPT -dMaxBitmap=500000000 -dLastPage=1 -dAlignToPixels=0 \
        -dGridFitTT=0 -sDEVICE=jpeg -dTextAlphaBits=4 -dGraphicsAlphaBits=4\
        -g%ix%i -dPDFFitPage -sOutputFile="%s" -f"%s"'''
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

        os.system(gs_command %
                  (t_size, t_size, t_filename, src_filename))

