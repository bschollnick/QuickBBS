"""
Thumbnail services for the gallery.

This is the universal code for creating and manipulating the thumbnails
used by the gallery.
"""
import common
import config
import os
import os.path
from PIL import Image
import StringIO
import time
from twisted.web.server import NOT_DONE_YET

#
#   Thumbnails are created in a canvas size of thumbnail_size x thumbnail_size
#
THUMBNAIL_REBUILD_TIME = (24 * 60 * 60) * 14  # 2 weeks
#
#   Thumbnails are forced to be refreshed within this time period
#

thumbnails = {}
thumbnails["small"] = ("_thumb300.png", 300)
thumbnails["mobile"] = ("_thumb750.png", 750)
thumbnails["large"] = ("_thumb1024.png", 1024)

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


def _create_thumbnail(fq_filename,
                      fq_thumbnail,
                      tsize=None,
                      memory_source=None):
    """
    fq_filename is the fully qualified filename of the image file
        to create the thumbnail from.

    fq_thumbnail is the name of the generated thumbnail file.

    This is a connivence wrapper around the image save code.

    Memory_source is the binary data for the image (e.g. zip file extraction)
    """
    if fq_filename == fq_thumbnail:
        return None

    if os.path.exists(fq_thumbnail):
        return None

    if tsize == None:
        return

    try:
        if memory_source == None:
            image_file = Image.open(fq_filename)
        else:
            image_file = Image.open(StringIO.StringIO(memory_source))
        image_file.thumbnail((tsize, tsize), Image.ANTIALIAS)
        image_file.save(fq_thumbnail, "PNG", optimize=False)
        return True
    except IOError:
        print "File thumbnail ", fq_filename
        print "save thumbnail ", fq_thumbnail
        print "The File [%s] (ioerror) is damaged." % (fq_filename)
        return ''
    except IndexError as detail:
        print "File thumbnail ", fq_filename
        print "save thumbnail ", fq_thumbnail
        print "The File [%s] (IndexError) is damaged." % (fq_filename)
        print detail
        return ''
    except TypeError:
        print "File thumbnail ", fq_filename
        print "save thumbnail ", fq_thumbnail
        print "The File [%s] (TypeError) is damaged." % (fq_filename)
        return ''


def return_thumbnail_name(fq_thumbnail, small=True, mobile=True):
    """
        Return the thumbnail name with the thumbnail size postpended
    """
    if small:
        return  "%s%s" % (fq_thumbnail, thumbnails["small"][0])

    if mobile:
        return  "%s%s" % (fq_thumbnail, thumbnails["mobile"][0])
    else:
        return  "%s%s" % (fq_thumbnail, thumbnails["large"][0])


def create_small_thumbnail(fq_filename, fq_thumbnail, msource=None):
    """
    Connivence wrapper around the code for the small_thumbnail creation
    """
    small_thumbnail = return_thumbnail_name(fq_thumbnail, small=True)
    timecheck_thumbnail_file(small_thumbnail)
    if msource == None:
        _create_thumbnail(fq_filename,
                          small_thumbnail,
                          tsize=thumbnails["small"][1])
    else:
        _create_thumbnail(fq_filename,
                          small_thumbnail,
                          tsize=thumbnails["small"][1],
                          memory_source=msource)
    return NOT_DONE_YET

def create_medium_thumbnail(fq_filename, fq_thumbnail, msource=None):
    """
    Connivence wrapper around the code for the medium_thumbnail creation
    """
    medium_thumbnail = return_thumbnail_name(fq_thumbnail,
                                             small=False,
                                             mobile=True)
    timecheck_thumbnail_file(medium_thumbnail)
    if msource == None:
        _create_thumbnail(fq_filename,
                          medium_thumbnail,
                          tsize=thumbnails["mobile"][1])
    else:
        _create_thumbnail(fq_filename,
                          medium_thumbnail,
                          tsize=thumbnails["mobile"][1],
                          memory_source=msource)
    return NOT_DONE_YET

def create_large_thumbnail(fq_filename, fq_thumbnail, msource=None):
    """
    Connivence wrapper around the code for the large_thumbnail creation
    """
    medium_thumbnail = return_thumbnail_name(fq_thumbnail,
                                             small=False,
                                             mobile=False)
    timecheck_thumbnail_file(medium_thumbnail)
    if msource == None:
        _create_thumbnail(fq_filename,
                          medium_thumbnail,
                          tsize=thumbnails["large"][1])
    else:
        _create_thumbnail(fq_filename,
                          medium_thumbnail,
                          tsize=thumbnails["large"][1],
                          memory_source=msource)
    return NOT_DONE_YET

def create_thumbnail(fq_filename,
                     fq_thumbnail,
                     msource=None,
                     gallery=False,
                     mobile=False):
    """
        Wrapper to create both the small and large thumbnails.

        msource = memory source
    """
    if gallery:
        create_small_thumbnail(fq_filename, fq_thumbnail, msource=msource)
        return  True
    if mobile:
        create_medium_thumbnail(fq_filename, fq_thumbnail, msource=msource)
        return  True
    else:
        create_large_thumbnail(fq_filename, fq_thumbnail, msource=msource)
        return  True


def create_thumbnail_for_pdf(fullpathname, filetype):
    """
    Create a thumbnail from a PDF file.

    ghost_script_command = '''gs -q -dQUIET -dPARANOIDSAFER -dBATCH -dNOPAUSE \
    -dNOPROMPT -dMaxBitmap=500000000 -dLastPage=1 -dAlignToPixels=0 \
    -dGridFitTT=0 -sDEVICE=jpeg -dTextAlphaBits=4 -dGraphicsAlphaBits=4\
    -g300x300 -dPDFFitPage -sOutputFile="%s" -f"%s"'''

    fullpathname is the Fully qualified filename
    """
    ghost_script_small_command = '''gs -q -dQUIET -dPARANOIDSAFER \
    -dBATCH -dNOPAUSE \
    -dNOPROMPT -dMaxBitmap=500000000 -dLastPage=1 -dAlignToPixels=0 \
    -dGridFitTT=0 -sDEVICE=jpeg -dTextAlphaBits=4 -dGraphicsAlphaBits=4\
    -g300x300 -dPDFFitPage -sOutputFile="%s" -f"%s"'''

    ghost_script_large_command = '''gs -q -dQUIET -dPARANOIDSAFER \
    -dBATCH -dNOPAUSE \
    -dNOPROMPT -dMaxBitmap=500000000 -dLastPage=1 -dAlignToPixels=0 \
    -dGridFitTT=0 -sDEVICE=jpeg -dTextAlphaBits=4 -dGraphicsAlphaBits=4\
    -g1024x1024 -dPDFFitPage -sOutputFile="%s" -f"%s"'''

    if not GHOSTSCRIPT_INSTALLED:
        return ''

    if filetype not in config.FILETYPES["pdf_file_types"]:
        return ''

    thumbnail_save_filename = fullpathname.replace(
        "albums/", "thumbnails/")# + ".png"

    thumbnail_save_filename = common.clean_filename2(thumbnail_save_filename)

    small_thumbnail = return_thumbnail_name(thumbnail_save_filename, True)
    medium_thumbnail = return_thumbnail_name(thumbnail_save_filename,
                                             False, True)
    large_thumbnail = return_thumbnail_name(thumbnail_save_filename,
                                            False, False)

    timecheck_thumbnail_file(small_thumbnail)
    timecheck_thumbnail_file(medium_thumbnail)
    timecheck_thumbnail_file(large_thumbnail)

    common.assure_path_exists(thumbnail_save_filename)
#    if not os.path.exists(os.path.dirname(thumbnail_save_filename)):
#        os.makedirs(os.path.dirname(thumbnail_save_filename))

    if not os.path.exists(small_thumbnail):
        #
        #   Cache File doesn't exist
        #
        os.system(ghost_script_small_command %
                  (small_thumbnail, fullpathname))
    if not os.path.exists(medium_thumbnail):
        #
        #   Cache File doesn't exist
        #
        os.system(ghost_script_large_command %
                  (medium_thumbnail, fullpathname))
    if not os.path.exists(large_thumbnail):
        #
        #   Cache File doesn't exist
        #
        os.system(ghost_script_large_command %
                  (large_thumbnail, fullpathname))
    return NOT_DONE_YET

def timecheck_thumbnail_file(thumbnail_save_filename):
    """
        Check the thumbnail file, and see if it is older than
        the rebuild time.

        If it is, it will be deleted, so that it can be regenerated.
    """
    if os.path.exists(thumbnail_save_filename):
        # File exists
        t_modified = os.path.getmtime(thumbnail_save_filename)
        # Get modified time stamps in seconds
        if time.time() - THUMBNAIL_REBUILD_TIME > t_modified:
            # if the current timestamp minus 2 weeks, is greater then the
            # file's
            os.remove(thumbnail_save_filename)



def create_thumbnail_for_file(server_root,
                              fullpathname,
                              filetype,
                              cover=False,
                              gallery=False,
                              mobile=False,
                              filename=None):
    """
        switchboard function that will dispatch to the proper
        thumbnail creator function.

        * pdfs are routed to create_thumbnail_for_pdf
        * image files are routed to create_thumbnail
        * archives are routed to create_thumbnail_for_archives
            - page of 0 means all pages, otherwise just that file #
    """

    if filetype in config.FILETYPES["pdf_file_types"]:
        create_thumbnail_for_pdf(fullpathname, filetype)
#     elif filetype in config.FILETYPES["archive_file_types"]:
#         create_thumbnail_for_archives(server_root,
#                                       fullpathname,
#                                       filetype,
#                                       cover=cover,
#                                       gallery=gallery,
#                                       mobile=mobile,
#                                       filename=filename)
    elif filetype not in config.FILETYPES["graphic_file_types"]:
        return False

    thumbnail_save_filename = fullpathname.replace("albums/", "thumbnails/")
    if not os.path.exists(os.path.dirname(thumbnail_save_filename)):
        os.makedirs(os.path.dirname(thumbnail_save_filename))

    create_thumbnail(fullpathname,
                     thumbnail_save_filename,
                     gallery=gallery, mobile=mobile)
    return  True
##############################################################################
def newcreate_thumbnail_for_archives(archive_name,
                                     filetype,
                                     cover=False,
                                     gallery=False,
                                     mobile=False,
                                     filename=None,
                                     archive_listing=None):
    """
    Create thumbnails for archive files.
    """
    import directory_caching.archives as archives
    if filetype not in config.FILETYPES["archive_file_types"]:
        return ''

    if cover == True:
        thumbnail_save_filename = common.fix_doubleslash(
            archive_name + os.sep + "cover")
    else:
        thumbnail_save_filename = common.fix_doubleslash(
            archive_name + os.sep + os.path.split(filename)[1])

    thumbnail_save_filename = thumbnail_save_filename.replace(
        "albums/", "thumbnails/")

    timecheck_thumbnail_file(thumbnail_save_filename)

    if not os.path.exists(os.path.dirname(thumbnail_save_filename)):
        os.makedirs(os.path.dirname(thumbnail_save_filename))

    data_thumbnail = None
    if not os.path.exists(thumbnail_save_filename):
        #
        #   Cache File doesn't exist
        #
        if cover:
            for afn in archive_listing:
                extension = os.path.splitext(afn)[1][1:].lower().strip()
                if extension in config.FILETYPES["graphic_file_types"]:
                    data_thumbnail = archives.return_archive_contents(\
                        archive_name,
                        afn)
                    break
        else:
            data_thumbnail = archives.return_archive_contents(archive_name,
                                                              filename)


        if not os.path.exists(os.path.dirname(thumbnail_save_filename)):
            #
            #   Directory doesn't exist, make it.
            #
            os.makedirs(os.path.dirname(thumbnail_save_filename))

        if data_thumbnail != None and\
                os.path.isdir(archive_name) != True:
            create_thumbnail(archive_name,
                             thumbnail_save_filename,
                             msource=data_thumbnail,
                             gallery=gallery,
                             mobile=mobile)
    return NOT_DONE_YET
