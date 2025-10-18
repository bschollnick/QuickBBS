SITE_NAME = "QuickBBS Site"
IMAGE_SIZE = {
    "small": (200, 200),
    "medium": (740, 740),
    "large": (1024, 1024),
    "unknown": (200, 200),
}

# PIL/Pillow Configuration
PIL_MAX_IMAGE_PIXELS = None  # Disable decompression bomb warning
PIL_LOAD_TRUNCATED_IMAGES = True  # Allow loading truncated images

# Directory thumbnail priority filenames (without extensions)
# Files matching these names will be prioritized when selecting thumbnails for directories
DIRECTORY_COVER_NAMES = ["cover", "title"]

QUICKBBS_REQUIRE_LOGIN = 0
SITE_NAME = "The Gallery"
GALLERY_ITEMS_PER_PAGE = 30
ARCHIVE_ITEMS_PER_PAGE = 21

SERVER_IP = "0.0.0.0"
SERVER_PORT = 8888

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
ICONS_PATH = f"{RESOURCES_PATH}/images"

ALIAS_MAPPING = {
    r"/volumes/masters/masters/hyp-collective": r"/volumes/c-8tb/gallery/quickbbs/albums/hentai_idea/hyp-collective",
    r"/volumes/masters/masters": r"/volumes/c-8tb/gallery/quickbbs/albums/hentai_idea",
}

# Used in ftypes / Filetypes, used in the refresh-filetypes command
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

# used as list of files to ignore when scanning directories
FILES_TO_IGNORE = [
    ".",
    "..",
    "thumbs.db",
    "downloaded_site.webloc",
    "update_capture.command",
    ".ds_store",
    "icon?",
]

# list of file extensions to ignore when scanning directories
EXTENSIONS_TO_IGNORE = [
    ".pdf_png_preview",
    ".log",
    ".webloc",
    ".command",
    ".sh",
    ".swf",
]

# Do not display files that start with a DOT (.)
IGNORE_DOT_FILES = True


REGISTRATION_OPEN = True

#
#   **NOTE** if you make any changes to the entries below, re-run manage.py refresh-filetypes
#           to ensure that the filetype database table is updated with your changes
#
# TBD: Verify, Haven't these already been moved to FileTypes?
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
    ".mp3",
]
BOOK_FILE_TYPES = [
    ".epub",
]
MARKDOWN_FILE_TYPES = [
    ".markdown",
]

LINK_FILE_TYPES = [".link", ".alias"]

ARCHIVE_FILE_TYPES = RAR_FILE_TYPES + ZIP_FILE_TYPES
