"""Application-specific settings and configuration for QuickBBS."""

import re

from django.db.models import Q

SITE_NAME = "QuickBBS Site"

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


REGISTRATION_OPEN = True

# Past this point be dragons - these are internal settings that should not be modified without understanding what the change will do.

#             ___====-_  _-====___
#        _--^^^#####//      \\#####^^^--_
#     _-^##########// (    ) \\##########^-_
#    -############//  |\^^/|  \\############-
#  _/############//   (@::@)   \\############\_
# /#############((     \\//     ))#############\
# -###############\\    (oo)    //###############-
# -#################\\  / VV \  //#################-
# -##################\\/      \//##################-
# _#/|##########/\######(   )######/\##########|\#_
# |/ |#/\#/\#/\/  \#/\##\  /##/\#/  \/\#/\#/\#| \|
# `  |/  V  V  `   V  \# \/ #/  V   '  V  V  \|  '
#     `   `  `      `   /  \   '      '  '   '
#                      (  )
#                     /    \
#                    /      \
#                   /        \
#               HERE BE DRAGONS

# Thumbnail size presets (width, height) used by the thumbnail generation system
# "small" is used for gallery grid thumbnails, "medium" for lightbox previews,
# "large" for full-screen viewing, "unknown" is the fallback
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

# All-white corruption detection threshold (bytes)
# Thumbnails with small_thumb blob size below this value are suspected GPU corruption
# and will be validated with PIL. All-white JPEGs at 200x200 q=55 are ~1303 bytes;
# real photo thumbnails are typically 3-15KB+.
SMALL_THUMBNAIL_SAFEGUARD_SIZE = 2500

# Path alias mapping for resolving alternative volume mount points
# Keys are lowercase source paths, values are the canonical paths they map to
# Used by normalize_fqpn() to redirect legacy or alternate mount locations
ALIAS_MAPPING = {
    r"/volumes/masters/masters/hyp-collective": r"/volumes/c-8tb/gallery/quickbbs/albums/hentai_idea/hyp-collective",
    r"/volumes/masters/masters": r"/volumes/c-8tb/gallery/quickbbs/albums/hentai_idea",
}


# Set to True to enable hit/miss tracking on LRU caches for performance analysis
# When enabled, caches use MonitoredLRUCache which tracks hits/misses/hit_rate
# Check stats in Django shell: print(directoryindex_cache.stats())
CACHE_MONITORING = True

# LRU cache size constants - maximum number of entries each cache will hold
# When a cache is full, the least recently used entry is evicted
# Increase sizes if monitoring shows hit rates below 80%
DIRECTORYINDEX_CACHE_SIZE = 750  # DirectoryIndex lookups by SHA256 (directoryindex.py)
DISTINCT_FILES_CACHE_SIZE = 500  # Distinct file SHA lists per directory+sort (directoryindex.py)
FILEINDEX_CACHE_SIZE = 250  # FileIndex lookups by SHA256 (fileindex.py)
FILEINDEX_DOWNLOAD_CACHE_SIZE = 250  # FileIndex download lookups by SHA256 (fileindex.py)
LAYOUT_MANAGER_CACHE_SIZE = 500  # Gallery page layout results (managers.py)
BUILD_CONTEXT_INFO_CACHE_SIZE = 500  # Item view context data (managers.py)
WEBPATHS_CACHE_SIZE = 500  # Full path to web path conversions (utilities.py)
BREADCRUMBS_CACHE_SIZE = 400  # Breadcrumb navigation lists (utilities.py)
NORMALIZED_STRINGS_CACHE_SIZE = 500  # Normalized string lookups (common.py)
DIRECTORY_SHA_CACHE_SIZE = 1000  # Directory SHA256 hash computations (common.py)
NORMALIZED_PATHS_CACHE_SIZE = 1000  # Normalized path lookups (common.py)
FILETYPES_CACHE_SIZE = 500  # Filetype lookups by extension (filetypes/models.py)
THUMBNAILFILES_CACHE_SIZE = 1000  # ThumbnailFiles lookups by SHA256 (thumbnails/models.py)
ENCODING_CACHE_SIZE = 1000  # Text file encoding detection results (fileindex.py)
ALIAS_CACHE_SIZE = 250  # macOS alias resolution results (fileindex.py)

# HTTP Cache-Control header settings
HTTP_CACHE_MAX_AGE = 300  # seconds (5 minutes) for file response Cache-Control headers

# Search and view limits
DEFAULT_SORT_ORDER = 0  # Default sort order index (maps to SORT_MATRIX keys)
MAX_SEARCH_RESULTS = 10000  # Maximum combined search results returned
THUMBNAIL_BATCH_LIMIT = 100  # Maximum thumbnails to enqueue per gallery page load
ITEM_VIEW_THUMBNAIL_BATCH_LIMIT = 50  # Maximum thumbnails to enqueue per item view

# Text file display limits
ENCODING_DETECT_READ_SIZE = 4096  # Bytes to read for charset detection
MAX_TEXT_FILE_DISPLAY_SIZE = 1024 * 1024  # Maximum text file size to display (1MB)

# Watchdog / cache watcher timers
EVENT_PROCESSING_DELAY = 5  # seconds - debounce delay for batching filesystem events
WATCHDOG_RESTART_INTERVAL = 14400  # seconds (4 hours) between watchdog restarts

# Directory traversal and bulk operation limits
MAX_DIRECTORY_DEPTH = 15  # Maximum parent directory traversal depth
DIRECTORY_SYNC_CHUNK_SIZE = 100  # Iterator chunk size for directory sync queries
DIRECTORY_SYNC_BATCH_SIZE = 100  # Batch size for bulk_update during directory sync

# SHA256 parallel processing configuration
SHA256_MAX_WORKERS = 8  # Maximum worker processes for parallel SHA256 computation
SHA256_PARALLEL_THRESHOLD = 5  # Minimum file count to use parallel processing

# Batch sizes for database and I/O operations
# These values are optimized for typical directory/file counts in gallery operations
BATCH_SIZES = {
    "db_read": 500,  # Reading file/directory records from database
    "db_write": 250,  # Writing/updating records to database
    "file_io": 100,  # File system operations (stat, hash calculation)
}

# Take the directory cover names and build a Q object that can be used to query for
# files matching those names (case-insensitive).  This is used to efficiently find potential
# cover images for directories.
# Prebuilt query for cover image matching (built once at startup for performance)
# This Q object matches files where the name (without extension) matches any DIRECTORY_COVER_NAMES
DIRECTORY_COVER_QUERIES = Q()
for cover_name in DIRECTORY_COVER_NAMES:
    # Case-insensitive regex match: filename starts with cover_name followed by dot
    DIRECTORY_COVER_QUERIES |= Q(name__iregex=rf"^{re.escape(cover_name)}\.")

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
# Used for validation and display purposes
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

# Filetype category mapping - maps human-readable category names to numeric IDs
# Used by the refresh-filetypes management command to seed the filetypes database table
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

# Filenames to skip during directory scanning (case-insensitive comparison)
# These are OS metadata files or other non-gallery content
FILES_TO_IGNORE = [
    ".",
    "..",
    "thumbs.db",
    "downloaded_site.webloc",
    "update_capture.command",
    ".ds_store",
    "icon?",
]

# File extensions to skip during directory scanning (case-insensitive comparison)
# These are auxiliary files that should not appear in the gallery
EXTENSIONS_TO_IGNORE = [
    ".pdf_png_preview",
    ".log",
    ".webloc",
    ".command",
    ".sh",
    ".swf",
]

# When True, files and directories starting with "." are hidden from gallery views
IGNORE_DOT_FILES = True
