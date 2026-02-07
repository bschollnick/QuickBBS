"""Application-specific settings and configuration for QuickBBS."""

import re

from django.db.models import Q

SITE_NAME = "QuickBBS Site"

# Directory thumbnail priority filenames (without extensions)
# Files matching these names will be prioritized when selecting thumbnails for directories
DIRECTORY_COVER_NAMES = ["cover", "title"]

# Prebuilt query for cover image matching (built once at startup for performance)
# This Q object matches files where the name (without extension) matches any DIRECTORY_COVER_NAMES

DIRECTORY_COVER_QUERIES = Q()
for cover_name in DIRECTORY_COVER_NAMES:
    # Case-insensitive regex match: filename starts with cover_name followed by dot
    DIRECTORY_COVER_QUERIES |= Q(name__iregex=rf"^{re.escape(cover_name)}\.")

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


REGISTRATION_OPEN = True

"""
Past this point be dragons - these are internal settings that should not be modified without understanding what the change will do.

            ___====-_  _-====___
       _--^^^#####//      \\#####^^^--_
    _-^##########// (    ) \\##########^-_
   -############//  |\^^/|  \\############-
 _/############//   (@::@)   \\############\_
/#############((     \\//     ))#############\
-###############\\    (oo)    //###############-
-#################\\  / VV \  //#################-
-##################\\/      \//##################-
_#/|##########/\######(   )######/\##########|\#_
|/ |#/\#/\#/\/  \#/\##\  /##/\#/  \/\#/\#/\#| \|
`  |/  V  V  `   V  \# \/ #/  V   '  V  V  \|  '
    `   `  `      `   /  \   '      '  '   '
                     (  )
                    /    \
                   /      \
                  /        \
              HERE BE DRAGONS
"""

IMAGE_SIZE = {
    "small": (200, 200),
    "medium": (740, 740),
    "large": (1024, 1024),
    "unknown": (200, 200),
}

# PIL/Pillow Configuration
PIL_MAX_IMAGE_PIXELS = None  # Disable decompression bomb warning
PIL_LOAD_TRUNCATED_IMAGES = True  # Allow loading truncated images

# Thumbnail Quality Settings (1-100, where 100 is highest quality)
PIL_IMAGE_QUALITY = 85  # Quality for PIL/Pillow thumbnail generation
CORE_IMAGE_QUALITY = 55  # Quality for Core Image thumbnail generation (macOS)

ALIAS_MAPPING = {
    r"/volumes/masters/masters/hyp-collective": r"/volumes/c-8tb/gallery/quickbbs/albums/hentai_idea/hyp-collective",
    r"/volumes/masters/masters": r"/volumes/c-8tb/gallery/quickbbs/albums/hentai_idea",
}


# Set to True to enable hit/miss tracking on LRU caches for performance analysis
# Check stats in Django shell: print(directoryindex_cache.stats())
CACHE_MONITORING = True

# LRU cache size constants - adjust based on monitoring stats
DIRECTORYINDEX_CACHE_SIZE = 750
DISTINCT_FILES_CACHE_SIZE = 500
FILEINDEX_CACHE_SIZE = 250
FILEINDEX_DOWNLOAD_CACHE_SIZE = 250

#
#   ┌──────────────────────────────────────────────────────────────────────────────┐
#   │ FILETYPE DEFINITIONS - FOR refresh-filetypes COMMAND ONLY                    │
#   ├──────────────────────────────────────────────────────────────────────────────┤
#   │ These lists are ONLY used by the `manage.py refresh-filetypes` command      │
#   │ to seed/update the `filetypes` database table.                              │
#   │                                                                              │
#   │ ⚠️  IMPORTANT: The Django application does NOT use these lists directly!     │
#   │    All filetype decisions are made by querying the `filetypes` table.       │
#   │                                                                              │
#   │ To add support for a new file type:                                         │
#   │   1. Add the extension to the appropriate list below                        │
#   │   2. Run: python manage.py refresh-filetypes                                │
#   │   3. The extension will be added to the database and recognized by the app  │
#   └──────────────────────────────────────────────────────────────────────────────┘
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

# Combined list of all supported file types (duplicates removed, sorted)
ALL_SUPPORTED_FILETYPES = sorted(
    set(
        GRAPHIC_FILE_TYPES
        + PDF_FILE_TYPES
        + RAR_FILE_TYPES
        + ZIP_FILE_TYPES
        + HTML_FILE_TYPES
        + TEXT_FILE_TYPES
        + MOVIE_FILE_TYPES
        + AUDIO_FILE_TYPES
        + BOOK_FILE_TYPES
        + MARKDOWN_FILE_TYPES
        + LINK_FILE_TYPES
    )
)

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
