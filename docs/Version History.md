
## Pre-Version 1 (2014 and earlier)
**Technology**: Twisted Matrix Framework

The original QuickBBS Gallery was built on the [Twisted Matrix](https://twistedmatrix.com) web framework, written in Python. This version served as the foundational proof-of-concept for the gallery system.

**Key Features:**
- Twisted web server with asynchronous request handling
- File system-based gallery browsing
- Basic template system using early Python web technologies
- Simple file serving and directory listing

**Retirement**: June 21, 2016 - The Twisted codebase was officially retired in favor of Django (commit: 185ae83).

## Version 1 (2014-2016)
**Technology**: Django (Early Implementation)

Version 1 represented the initial migration from Twisted to Django, establishing the foundation for modern QuickBBS Gallery.

**Key Features:**
- First Django-based implementation
- File system-only approach with in-memory directory caching
- Thumbnails stored as separate files on disk
- Plugin system (Core Plugins v1.0 and v1.1)
- INI-based configuration system

**Limitations:**
- **Performance Issues**: Severely impacted by disk I/O bottlenecks
- **Large Directory Problems**: Struggled with directories containing 3,000-4,000+ files
- **Thumbnail Generation**: Created during web page rendering, causing significant delays
- **No Database Integration**: Relied entirely on file system operations

**Architecture:**
- Used scandir library for improved directory scanning performance
- Memory-based directory caching
- No persistent storage of file metadata

## Version 2 (April 25, 2018 - 2022)
**Technology**: Django with Database Integration

Version 2 represented a **major architectural shift** introducing database-backed operations and UUID-based file identification.

### Major Improvements:

**UUID-Based Architecture:**
- Introduced Universal Unique Identifiers for all gallery objects
- Simplified file lookup from filename+pathname to UUID-based queries
- All file references use UUIDs internally and in web requests

**Database Integration:**
- SQLite3 database for storing file metadata
- Persistent caching of directory and file information
- Separated thumbnail generation from page rendering

**Performance Optimizations:**
- Thumbnail generation moved to dedicated endpoints
- Database-cached directory listings
- Improved handling of large directories (3K-4K files)

**Enhanced File Type Support:**
```ini
# V2 File Type Configuration
graphic_file_types = bmp, gif, jpg, jpeg, png
pdf_file_types = pdf
archive_file_types = cbr, rar, cbz, zip
text_file_types = txt, markdown
movie_file_types = mp4, mpg, mpeg, wmv, flv, avi
```

### URL Structure Examples:
```
http://example.com/albums/catpics                                      # Directory listing
http://example.com/thumbnail/7109b28a-80f6-4a8f-8b48-ae86e052cdaa?small  # Small thumbnail
http://example.com/viewitem/7109b28a-80f6-4a8f-8b48-ae86e052cdaa          # Single item view
http://example.com/view_archive/7109b28a-80f6-4a8f-8b48-ae86e052cdaa      # Archive contents
http://example.com/view_arc_item/7109b28a-80f6-4a8f-8b48-ae86e052cdaa?page=4  # Archive item
```

**Key Architectural Changes:**
- Directory caching with change detection
- Archive support for RAR and ZIP files
- Modular plugin architecture
- Enhanced thumbnail management

## Version 3.0 (December 2022 - March 2024)
**Technology**: Django 5+, PostgreSQL, Modern Python

Version 3 introduced **revolutionary performance optimizations** and modern architectural patterns.

### Revolutionary Changes:

**PostgreSQL Thumbnail Storage:**
- Thumbnails stored as binary blobs directly in PostgreSQL database
- Three sizes: Small (200x200), Medium (740x740), Large (1024x1024)
- Eliminated disk I/O bottlenecks for thumbnail delivery
- Database becomes bottleneck instead of disk, providing better scalability

**Watchdog File System Monitoring:**
- Real-time file system monitoring using [Watchdog library](https://github.com/gorakhargosh/watchdog/)
- Automatic cache invalidation on file system changes
- Directories marked for rescanning without immediate database updates
- Eliminated need for periodic directory scanning

**Modern Django Architecture:**
- Upgraded to Django 5+ (testing Django 6.0 alpha)
- Separated applications: `cache_watcher`, `filetypes`, `frontend`, `thumbnails`
- Modern Python 3.12+ type hints and async support
- PostgreSQL-optimized database schema

**SHA256-Based Identification:**
- Migrated from UUIDs to SHA256 hashes for file identification
- More reliable file tracking across moves and renames
- Better deduplication capabilities

### Application Structure:
```
quickbbs/
├── cache_watcher/     # Watchdog monitoring
├── filetypes/         # File type detection
├── frontend/          # Web interface
├── quickbbs/          # Core configuration
└── thumbnails/        # PostgreSQL thumbnail storage
```

## Version 3.5 (2025)
**Technology**: Django 6.0 Alpha, HTMX, Advanced Performance

Version 3.5 represents the **current state-of-the-art** implementation with full HTMX integration and advanced performance optimizations.

### Major Enhancements:

**Full HTMX Integration:**
- Dynamic partial page updates without full page reloads
- Template selection based on request type (partial vs complete)
- Enhanced user experience with faster navigation
- `@vary_on_headers("HX-Request")` decorators throughout

**Layout Manager System (`frontend/managers.py`):**
- **Database-Level Pagination**: PostgreSQL LIMIT/OFFSET instead of memory loading
- **LRU Caching**: 500-item caches for layout and context data
- **Optimized Query Planning**: Fetch only current page data
- **Threaded Thumbnail Processing**: ThreadPoolExecutor with configurable workers

**Advanced Performance Features:**
- **Cached Text Encoding Detection**: File encoding cached by modification time
- **Smart Text Processing**: 1MB size limits with encoding detection
- **ORM Optimization**: Strategic use of `select_related` and `prefetch_related`
- **Context Building Optimization**: Efficient breadcrumb generation

**Modern Development Stack:**
- Poetry dependency management
- Black code formatting
- MyPy type checking
- Pytest testing framework
- Comprehensive development toolchain

### Current Capabilities:
- **Multi-format Support**: Images, PDFs, archives, text, movies, audio, books
- **Responsive Design**: Multiple thumbnail sizes for desktop/mobile
- **Search Integration**: Fast file and directory search
- **Real-time Monitoring**: Instant cache invalidation
- **High Performance**: Database-optimized with intelligent caching

## Version 3.75 (2025)
**Technology**: Django 6.0 Alpha, HTMX, macOS Native Integration

Version 3.75 builds on the v3.5 foundation with enhanced thumbnail generation, better WSGI/ASGI compatibility, and comprehensive UI improvements.

### Major Enhancements:

**Thumbnails:**

In addition to PIL/FFMPEG/PyMuPDF thumbnail support, **macOS Native Thumbnail Generation** has been added for systems running under Mac OS.  This uses the Native Mac OS frameworks  optimal performance if running under Mac OS.
	- **AVFoundation**: Native video thumbnail generation without triggering GUI Python dock icon
	- **PDFKit**: macOS-native PDF thumbnail generation
	- **Core Image Exploration**: Investigation of Core Image as PIL replacement for better performance
- **Virtual Directory Support**: Thumbnails are now supported for alias/link directories

**ASGI/Async Compatibility:**
- **Multi-Server Support**: better compatibility with WSGI (Gunicorn) and ASGI (Uvicorn, Hypercorn, Daphne)
- **Connection Management**: Enhanced database connection handling to prevent leaks
- **Removed ThreadPoolExecutor**: Replaced with `sync_to_async` wrappers to prevent database connection leaks and transaction bleeding

**Template System & UI Improvements:**
- **Bulma Standardization**: Refactored utilize more core Bulma CSS components
- **Template Consolidation**: Reduced duplication between `search_listings` and `gallery_listing` templates
- **Component Architecture**: Better separation of navbar, breadcrumb, and sidebar components
- **CSS Cleanup**: Eliminated majority of inline styles in favor of external CSS
- **Mobile-First Design**: Removed device detection in favor of pure CSS responsive design
- **HTMX Enhancements**:
  - Added `show:window:top` for proper viewport scrolling
  - Improved spinner behavior with browser navigation handling
  - Better partial page update patterns

**Database & Performance Optimizations:**
- **1-to-1 Relationships**: Optimized `fs_Cache_Tracking` ↔ `IndexDirs` linkage
- **Query Optimization**: Multiple rounds of N+1 query elimination
- **Memory Efficiency**: Improved batch processing and pagination strategies

**File System Management:**
- **Enhanced Scan Command**:
	  - New `--add_directories`, `--add_files`, `--add_thumbnails` options
	  - Performance metrics for all operations
	  - `--max_count` parameter for incremental processing
	  - Improved `--verify_files` and `--verify_directories` options
- **Watchdog Improvements**:
	  - Event debouncing (5-second buffer for bulk operations)
	  - Automatic watchdog reset mechanism for long-running stability
	  - Better connection cleanup in event handlers
- **macOS Alias Support**: .link support is still available, but mac OS Native alias resolution is an alternative to the `.link` functionality
- **URI Parsing**: Fixed special character handling in file paths

**File Operations:**
- **file_mover_colors3 Rewrite**: Performance optimized, eliminated complexity
- **Colorama Integration**: Enhanced terminal output with color support
- **Directory Name Consistency**: Fixed edge cases in path handling

**Code Quality & Infrastructure:**
- **Import Cleanup**: Removed unnecessary and wildcard imports
- **Type Hints**: Corrected Union type hints and added comprehensive typing
- **Docstring Updates**: Enhanced documentation across codebase
- **Database Backups**: Added `django-dbbackup` for automated backups

**Bug Fixes:**
- Fixed text file encoding detection regression
- Resolved thumbnail foreign key updates with duplicate SHA256 hashes
- Fixed directory count display issues in templates
- Corrected resource path loading issues
- Multiple edge case fixes in scanning, caching, and thumbnail generation

---

## Performance Evolution Summary:

| Version | Storage                    | Thumbnails     | Monitoring             |
| ------- | -------------------------- | -------------- | ---------------------- |
| Pre-v1  | File System                | None           | Manual                 |
| v1      | File System + Memory Cache | Disk Files     | Manual                 |
| v2      | SQLite Database            | Disk Files     | Manual                 |
| v3.0    | PostgreSQL                 | Database BLOBs | Watchdog               |
| v3.5    | PostgreSQL                 | Database BLOBs | Watchdog + HTMX        |
| v3.75   | PostgreSQL                 | Database BLOBs | Watchdog + HTMX + ASGI |

