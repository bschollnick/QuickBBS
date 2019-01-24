# coding: utf-8
"""
Constants for QuickBBS, the python edition.
"""
import re


# used in Utilities
replacements={'?':'','/':"", ":":"", "#":"_"}
regex = re.compile("(%s)" % "|".join(map(re.escape, replacements.keys())))


# Used in ftypes / Filetypes
ftypes = {'unknown':0,
          'dir':1,
          'pdf':2,
          'archive':3,
          'image':4,
          'movie':5,
          'text':6,
          'html':7,
          'epub':8,
          'flash':9}


_archives = [".zip", ".rar", ".cbz", ".cbr"]
_html = [".htm", ".html"]
_graphics = [".bmp", ".gif", ".jpg", ".jpeg", ".png"]
_text = [".txt", ".md", ".markdown"]
_movie = [".mp4", ".m4v", ".mpg", ".mpg4", ".mpeg",
           ".mpeg4", ".wmv", ".flv", ".avi"]

