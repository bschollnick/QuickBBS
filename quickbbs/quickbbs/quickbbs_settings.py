# from filetypes.constants import *
SITE_NAME = "QuickBBS Site"
IMAGE_SIZE = {"small": 200, "medium": 740, "large": 1024, "unknown": 200}

QUICKBBS_REQUIRE_LOGIN = 0
SITE_NAME = "The Gallery"
GALLERY_ITEMS_PER_PAGE = 30
ARCHIVE_ITEMS_PER_PAGE = 21

SERVER_IP = "0.0.0.0"
SERVER_PORT = 8888

# import socket
# Used for Bonjour / ZeroConf, temporarily removed
# HOSTNAME = socket.gethostname()
# EXTERNAL_IP = "192.168.1.19"
# print(HOSTNAME, EXTERNAL_IP)

PRELOAD = ["/albums", "/albums/hentai_idea"]

SERVER_PATH = "/Volumes/c-8tb/gallery/quickbbs"
SERVERLOG = f"{SERVER_PATH}/logs/server.log"
ALBUMS_PATH = f"{SERVER_PATH}"
THUMBNAILS_PATH = f"{SERVER_PATH}/thumbnails"
STATIC_PATH = f"{SERVER_PATH}/quickbbs/static"

RESOURCES_PATH = f"{SERVER_PATH}/resources"
TEMPLATES_PATH = f"{RESOURCES_PATH}/templates"
IMAGES_PATH = f"{RESOURCES_PATH}/images"
JAVASCRIPT_PATH = f"{RESOURCES_PATH}/javascript"
CSS_PATH = f"{RESOURCES_PATH}/css"
FONTS_PATH = f"{RESOURCES_PATH}/fonts"

# Used in ftypes / Filetypes
FTYPES = {
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
    "markdown": 11,
    "link": 12,
}
# TBD: Need to confirm ftypes is still in use.
FILES_TO_IGNORE = [
    ".",
    "..",
    "thumbs.db",
    "downloaded_site.webloc",
    "update_capture.command",
    ".ds_store",
    "icon?",
]

EXTENSIONS_TO_IGNORE = [
    ".pdf_png_preview",
    ".log",
    ".webloc",
    ".command",
    ".sh",
    ".swf",
]

IGNORE_DOT_FILES = True

REGISTRATION_OPEN = True

#
#   **NOTE** if you make any changes to the entries below, re-run manage.py refresh-filetypes
#           to ensure that the filetype database table is updated with your changes
#
GRAPHIC_FILE_TYPES = [".bmp", ".gif", ".jpg", ".jpeg", ".png", ".webp"]
PDF_FILE_TYPES = [
    ".pdf",
]
RAR_FILE_TYPES = [".cbr", ".rar"]
ZIP_FILE_TYPES = [".cbz", ".zip"]
HTML_FILE_TYPES = [".html", ".htm"]
TEXT_FILE_TYPES = [".txt", ".markdown", ".text"]
MOVIE_FILE_TYPES = [
    ".mp4",
    ".mpg",
    ".mpg4",
    ".mpeg",
    ".mpeg4",
    ".wmv",
    ".flv",
    ".avi",
    ".m4v",
]
AUDIO_FILE_TYPES = [
    ".MP3",
]
BOOK_FILE_TYPES = [
    ".epub",
]
MARKDOWN_FILE_TYPES = [
    ".markdown",
]

LINK_FILE_TYPES = [".link"]

ARCHIVE_FILE_TYPES = RAR_FILE_TYPES + ZIP_FILE_TYPES

# IMAGE_SAFE_FILES = GRAPHIC_FILE_TYPES + PDF_FILE_TYPES + ARCHIVE_FILE_TYPES

# FILES_TO_CACHE = GRAPHIC_FILE_TYPES + PDF_FILE_TYPES + ARCHIVE_FILE_TYPES

