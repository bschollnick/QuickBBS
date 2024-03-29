# coding: utf-8
"""
Constants for QuickBBS, the python edition.
"""

# Used in ftypes / Filetypes
ftypes = {
    "unknown": 0,
    "dir": 1,
    "pdf": 2,
    "archive": 3,
    "image": 4,
    "movie": 5,
    "text": 6,
    "html": 7,
    "epub": 8,
    "flash": 9,
    "audio": 10,
}


_archives = [".zip", ".rar", ".cbz", ".cbr"]
_html = [".htm", ".html"]
_graphics = [".bmp", ".gif", ".jpg", ".jpeg", ".png", ".webp"]
_text = [".txt", ".md", ".markdown"]
_movie = [".mp4", ".m4v", ".mpg", ".mpg4", ".mpeg", ".mpeg4", ".wmv", ".flv", ".avi"]
_audio = [
    ".mp3",
]
