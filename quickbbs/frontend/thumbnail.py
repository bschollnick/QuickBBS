# -*- coding: utf-8 -*-
"""
Core Plugin for Gallery
"""

##############################################################################
from __future__ import absolute_import
from __future__ import print_function
import cStringIO
import exceptions
import os
import os.path
import stat
import time
import subprocess
#from subprocess import call
from functools import partial
from PIL import Image
from ctypes import c_void_p, c_size_t

import warnings
from . import config


#pool = workerpool.WorkerPool(size=15)

THUMBNAIL_DB = {}
THUMBNAIL_DB.update({'bmp': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'dib': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'eps': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'gif': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'msp': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'tif': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'tiff': {'IMG_TAG': True, 'FRAME_TAG': False,
                              'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                              'ICON': ""}})
THUMBNAIL_DB.update({'jpg': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'jpeg': {'IMG_TAG': True, 'FRAME_TAG': False,
                              'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                              'ICON': ""}})
THUMBNAIL_DB.update({'jpe': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'jif': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'jfif': {'IMG_TAG': True, 'FRAME_TAG': False,
                              'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                              'ICON': ""}})
THUMBNAIL_DB.update({'jfi': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'png': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'pcx': {'IMG_TAG': True, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FAEBF4',
                             'ICON': ""}})
THUMBNAIL_DB.update({'pdf': {'IMG_TAG': False, 'FRAME_TAG': False,
                             'ARCHIVE': False, 'BACKGROUND': '#FDEDB1',
                             'ICON': ""}})
THUMBNAIL_DB.update({'zip': {'IMG_TAG': False, 'FRAME_TAG': False,
                             'ARCHIVE': True, 'BACKGROUND': '#FDEDB1',
                             'ICON': ""}})
THUMBNAIL_DB.update({'cbz': {'IMG_TAG': False, 'FRAME_TAG': False,
                             'ARCHIVE': True, 'BACKGROUND': '#FDEDB1',
                             'ICON': ""}})
THUMBNAIL_DB.update({'cbr': {'IMG_TAG': False, 'FRAME_TAG': False,
                             'ARCHIVE': True, 'BACKGROUND': '#FDEDB1',
                             'ICON': ""}})
THUMBNAIL_DB.update({'rar': {'IMG_TAG': False, 'FRAME_TAG': False,
                             'ARCHIVE': True, 'BACKGROUND': '#FDEDB1',
                             'ICON': ""}})

THUMBNAIL_REBUILD_TIME = (24 * 60 * 60) * 14  # 2 weeks

warnings.simplefilter('ignore', Image.DecompressionBombWarning)

def check_for_ghostscript():
    """
    Check and return path to ghostscript, returns None
    if is not installed.
    """
    from twisted.python.procutils import which
    if which("gs") == []:
        print("Ghostscript is not installed.")
        return None
    return which("gs")[0]

GHOSTSCRIPT_INSTALLED = check_for_ghostscript()
THUMBNAIL_REBUILD_TIME = (24 * 60 * 60) * 14  # 2 weeks

#
# class Thumbnails(object):
#     """
#         Subclassed core plugin.
#
#
#         * ACCEPTABLE_FILE_EXTENSIONS is a list, that contains the (lowerCASE),
#             File Extensions (DOTTED format, e.g. .gif, not gif) that this
#             plugin will manage.
#
#         * IMG_TAG - BOOLEAN - (e.g. .PNG, .GIF, .JPG)
#             * True - This plugin can make an IMAGE based thumbnail, for this
#                 file type
#             * False - This plugin will not make an image thumbnail
#
#         * FRAME_TAG - BOOLEAN - (e.g. .TEXT, .MARKDOWN, etc)
#             * True - This plugin will return an TEXT based stream. That should
#                 be displayed in the browser window.
#
#             * False - This plugin will not make an image thumbnail
#
#         * DEFAULT_ICON - String - The Default thumbnail image to use, if
#             IMG_TAG is False
#
#         * DEFAULT_BACKGROUND - String - The background of the table cell, for
#             this file format.
#
#         * CONTAINER - BOOLEAN - (e.g. ZIP, RAR) - This plugin returns an
#             memory_image of the contents.
#
#     """
#     def __init__(self):
#         """
#         Initialization for Core Plugin.
#
#         """
#
#     def display_text_content(self, src_filename):
#         """
#         Initialization for Core Plugin.
#
#         """
#         raise NotImplementedError("Subclass must implement abstract method")
#
#     def make_tnail_name(self, filename=None):
#         tnail_name = {}
#         tnail_name["small"] = filename + "_thumb%s.png" %\
#             config.configdata["configuration"]["sm_thumb"]
# # gallery view ~300
#         tnail_name["medium"] = filename + "_thumb%s.png" %\
#             config.configdata["configuration"]["med_thumb"]
# # mobile view ~740
#         tnail_name["large"] = filename + "_thumb%s.png" %\
#             config.configdata["configuration"]["lg_thumb"]
# # large view ~1024
#         return tnail_name
#
#     def make_tnail_fsname(self, src_filename=None):
#         """
#         Generate the thumbnail name for the source file.
#
#         input -
#                 src_filename - The FQFN of the source file
#                 clean_filename - Pointer to the filename cleaning function
#                                  that should be used.
#
#         output - A dictionary, of the small, medium, and large thumbnails for
#                  the thumbnail file.  The thumbnail will have the albums
#                  directory replaced with the thumbnails directory name.
#         """
#         if src_filename is None:
#             raise RuntimeError("No Source file given.")
#
#         tnail_target = src_filename.replace("%salbums%s" % (os.sep, os.sep),
#                                             "%sthumbnails%s" % (os.sep,
#                                                                 os.sep))
#         tnail_name = self.make_tnail_name(tnail_target)
#         tnail_name["small"] = os.path.join(tnail_target, tnail_name["small"])
#         tnail_name["medium"] = os.path.join(tnail_target, tnail_name["medium"])
#         tnail_name["large"] = os.path.join(tnail_target, tnail_name["large"])
#         return tnail_name

#     def does_thumbnail_already_exist(self, thumbfilename):
# #        if thumbfilename == None:
# #            return False
#         try:
#             return os.path.exists(thumbfilename)
#         except exceptions.IOError:
#             return False
#
#     def validate_thumbnail_file(self, thumbfilename, src_file):
#         """
#         validate thumbnail file existence.
#         """
#         if thumbfilename == None:
#             return False
#         elif self.does_thumbnail_already_exist(thumbfilename):
#             return True
#         return False


#     def create_pdf_thumbnail(self, src_filename,
#                              t_filename,
#                              t_size=None):
#         """
#         http://stackoverflow.com/questions/12759778/python-magickwand-pdf-to-image-converting-and-resize-the-image
#
#
#         ImageMagick just uses Ghostscript under the hood, with less customizablity.
#         (I can't seem to get compression to work properly with IM.)
#         """
#         if src_filename is None:
#             raise RuntimeError("No Source Filename was not specified")
#         elif src_filename == t_filename:
#             raise RuntimeError("The source is the same as the target.")
#
#         if t_filename is None:
#             raise RuntimeError("The Target is not specified")
#
#         if os.path.exists(t_filename):
#             return None
#
#         if t_size is None:
#             raise RuntimeError("No Target size is defined")
# #        pool.map(process, [src_filename], [t_filename], [t_size])
#
#         gs_command = '''gs -q -dQUIET -dPARANOIDSAFER \
#          -dBATCH -dNOPAUSE \
#          -dNOPROMPT -dMaxBitmap=500000000 -dLastPage=1 -dAlignToPixels=0 \
#          -dGridFitTT=0 -sDEVICE=jpeg -dTextAlphaBits=4 -dGraphicsAlphaBits=4\
#          -g%ix%i -dPDFFitPage -dFitPage \
#          -dPrinted=false -sOutputFile=$'%s' -f$'%s' '''
#
#         p = subprocess.call(gs_command % (t_size, t_size,
#                                           t_filename,
#                                           src_filename), shell=True)

#
#     def create_thumbnail_from_file(self, src_filename,
#                                    t_filename=None,
#                                    t_size=None):
#         #if os.path.exists(t_filename):
#             #print(t_filename, "already exists")
#         #    return False
#         #elif src_filename == t_filename:
#         if src_filename == t_filename:
#             raise RuntimeError("The source is the same as the target.")
#         elif t_filename is None:
#             raise RuntimeError("The Target is not specified")
#         elif t_size is None:
#             raise RuntimeError("No Target size is defined")
#         #print ("\n\n",src_filename)
#         extension = os.path.splitext(src_filename)[1].lower()[1:]
#         if extension == 'pdf':
#             return self.create_pdf_thumbnail(src_filename,
#                                              t_filename,
#                                              t_size)
#         try:
#             print ("Error, trying to convert to RGB")
#             image_file = Image.open(src_filename)
#             if image_file.mode != "RGB":
#                 image_file = image_file.convert('RGB')
#
#             image_file.thumbnail((t_size, t_size), Image.ANTIALIAS)
#             image_file.save(t_filename, "PNG", optimize=True)
#
#         except IOError:
#             print("File thumbnail ", src_filename)
#             print("save thumbnail ", t_filename)
#             print("The File [%s] (ioerror) is damaged." % (src_filename))
#             return False
#         except IndexError as detail:
#             print("File thumbnail ", src_filename)
#             print("save thumbnail ", t_filename)
#             print("The File [%s] (IndexError) is damaged." % (src_filename))
#             print(detail)
#             return False
#         except TypeError:
#             print("File thumbnail ", src_filename)
#             print("save thumbnail ", t_filename)
#             print("The File [%s] (TypeError) is damaged." % (src_filename))
#             return False
#         except:
#             print("Generic error on open")
#             return False
#
#         return True

##########################################################################
#     def create_thumbnail_from_memory(self, memory_image=None,
#                                      t_filename=None,
#                                      t_size=None):
#         """
#         Create a thumbnail from a memory image of the file.
#
#         inputs -
#
#             * memory_image - blob - This is the blob of image data, typically
#                 a blob that has been read from a file, or a zip, etc.
#
#             * t_filename - String - This is the fully qualified filepathname
#                 of the thumbnail file to be created.
#
#             * t_size - integer - This is the maximum size of the thumbnail.
#                 The thumbnail will be t_size x t_size (e.g. 300 x 300)
#
#         output -
#
#             * The thumbnail file that is created at the t_filename location.
#         """
#         if memory_image is None:
#             raise RuntimeError("No Memory Image is provided.")
#         elif t_filename is None:
#             raise RuntimeError("The Target is not specified")
#         elif os.path.exists(t_filename):
#             return False
#         elif t_size is None:
#             raise RuntimeError("No Target size is defined")
#
#         try:
#             #
#             #   Convert this to bytes io?
#             #
#             image_file = Image.open(cStringIO.StringIO(memory_image))
#             image_file.thumbnail((t_size, t_size), Image.ANTIALIAS)
#             if image_file.mode != "RGB":
#                 image_file = image_file.convert('RGB')
#             image_file.save(t_filename, "PNG", optimize=True)
#             return True
#         except IOError:
#             print("save thumbnail ", t_filename)
#         except IndexError as detail:
#             print("save thumbnail ", t_filename)
#             print(detail)
#         except TypeError:
#             print("save thumbnail ", t_filename)
#         return False
#
#     def extract_from_container(self, container_file=None,
#                                fn_to_extract=None,
#                                t_size=None):
#         """
#         Initialization for Core Plugin.
#
#         """
#         pass
