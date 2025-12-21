QuickBBS Gallery
================

A high-performance Django-based gallery and file browser application with hybrid file system + database design.   

## Features

* **File Areas / Image Galleries** - Comprehensive gallery system with database-stored thumbnails
* **Multi-format Support** - Images, PDFs, archives, text files, movies, audio, and more
* **High Performance** - Thumbnail caching in PostgreSQL for optimal I/O performance
* **Real-time Monitoring** - Watchdog-based file system monitoring for automatic cache invalidation
* **Responsive Design** - Multiple thumbnail sizes for desktop and mobile
* **Search & Browse** - File and directory search with metadata indexing

## Quick Start

### Prerequisites
- Python 3.12-3.14
- Django 4.1 or higher (currently using 6.0a1)
- PostgreSQL (currently used - testing would be needed for other database engines) 
### Installation

I am currently using poetry for dependency management, this instructions reflect that.
```bash
# Install dependencies
poetry install

# Set up database
cd quickbbs
python manage.py migrate
python manage.py createcachetable
python manage.py refresh-filetypes
# Run development server
python manage.py runserver 0.0.0.0:8888
```

### Management Commands

#### File System Management

##### Filetypes

```bash
# Refresh file type definitions in database
python manage.py refresh-filetypes
```
* **refresh-filetypes**  - updates the Filetypes table in the database, this controls various aspects of the importation, and display of the files (e.g. Background color, creation of thumbnails, etc.)

##### Scan & Verify commands
```bash
# Scan command - File system integrity and maintenance
python manage.py scan --verify_directories    # Verify existing directories in database
python manage.py scan --verify_files          # Verify existing files in database
```
* **verify_directories** - Verifies that the directories in the database still exist in the file system, if they do not, remove them from the table.
* **verify_files** - Verifies that the files in the database still exist in the file system.  Each file is validated to exist in all of the directories that it was last seen in (based off of SHA-256)

#### Scan & Add

**Reminder:**  QuickBBS will detect any files, folders, or thumbnails that need to be created.  These commands are optional to pre-load the content, since there is a performance penalty to creating large numbers of files / directories / thumbnails at runtime.  

* **add_directories** - Scan the Albums directory and identify any directories that do not exist in the database.  If they do not exist, they will be added.
* **add_files** - Scan the albums directory for any files that are not in the database, if they do not exist, they will be added.
* **add_thumbnails** - Scan the files database, and add thumbnails to any records that do not currently have thumbnails.

```bash
# Scan command - File system integrity and maintenance
python manage.py scan --add_directories       # Add missing directories to database
python manage.py scan --add_files             # Add missing files to database
python manage.py scan --add_thumbnails        # Generate missing thumbnails

# Scan command with limits
python manage.py scan --add_files --max_count 100       # Add up to 100 missing files
python manage.py scan --add_thumbnails --max_count 50   # Generate up to 50 thumbnails

# Scan options can be combined
python manage.py scan --add_directories --add_files  # Add directories and files in one pass
```

All of the **add_XXXXX**  commands have an option of "**--max_count**".  This allows you to limit the maximum number of files, directories, or thumbnails to be created in one pass.  For example, you could set a `cron` task to run batches of 1000 every hour or so by using **--max_count**.


---
## Running & Configuring Web Servers

See [[Web Servers]]

---
## Architecture

### Core Design Philosophy

QuickBBS implements a high-performance, hybrid design combining file system storage with database indexing and caching. 

What sets this apart is several changes from standard "gallery" designs.

* Virtually all gallery systems that I have examined require an extensive pre-scan before any content (or changed content) will be available.  QuickBBS instead will immediately detect any changes in it's monitored directory tree and update accordingly.
* Now the "conventional" scan style commands are available, but are **optional**.
	* The key reason for them is to deal with massive amounts of files being add, moved, or needing thumbnails to be created.  It's significantly faster to use the management commands to perform this than have the database be updated during a web request.
* Second, minimal disk usage.  Once the data is in the database, the only time the disk is used is if there is a need to create an thumbnail, download a file, or access a HTML/Markdown/Text file.  (HTML/Markdown/Text files are not stored in the database, just their metadata.)  All thumbnails are stored in the database.
* **WSGI/ASGI Compatibility**: The application supports both traditional (WSGI) and modern async (ASGI) web servers, enabling deployment flexibility with Gunicorn, Uvicorn, or Hypercorn for optimized performance.

### Why Database-Stored Thumbnails?

Traditional approaches create separate thumbnail files on disk, which under heavy load could be vulnerable to Disk (I/O) bottlenecks. 

In addition, most galleries end up creating thumbnail cache directories which eat up significant disk space.

QuickBBS stores three thumbnail sizes (by default, Small: 200x200, Medium: 740x740, Large: 1024x1024) as binary blobs in PostgreSQL, making the database the bottleneck rather than disk I/O for better performance.

### Request Processing

Web requests are handled as:
- **File Downloads** - Direct file serving with range request support
- **Thumbnails** - File, directory, and archive thumbnail generation
- **Gallery Views** - Directory listing with cached metadata
- **File Display** - Individual file viewing with metadata

### Cache Management

[Watchdog File System Monitor](https://github.com/gorakhargosh/watchdog/) continuously monitors the ALBUMS_PATH. When file system changes are detected, directories are marked for rescanning on the next access.  This prevents disk trashing when multiple files are being updated within a particular directory, but ensures efficient cache invalidation.  

When that directory is next accessed (via the web) the cached data will be detected as being invalidated, and an immediate rescan of the directory will be performed.  The newly updated data is marked as being validated, and the normal workflow is resumed.

**Event Batching**: File system changes are buffered for 5 seconds before processing, preventing database thrashing during bulk file operations (copies, moves, deletions). This batching strategy efficiently handles large-scale file system changes while maintaining responsiveness.

### Performance Optimizations

**Layout Manager (`frontend/managers.py`)**
- **Database-Level Pagination**: Uses PostgreSQL LIMIT/OFFSET queries instead of loading entire datasets into memory
- **Optimized Query Planning**: Calculates page boundaries and fetches only the data needed for the current page
- **Async-Safe Database Operations**: Uses `sync_to_async` wrappers for database operations in async contexts

**Context Building**
- **Cached Encoding Detection**: File text encoding detection cached based on filename and modification time
- **Smart Text Processing**: Handles text files, markdown, and HTML with size limits (1MB) and encoding detection
- **Optimized Breadcrumb Generation**: Efficient breadcrumb building with list comprehensions

[![](https://mermaid.ink/img/pako:eNqFVF1v6jAM_StWnzqJ_QEergRNJyENhvjQfbi9qkJraESbcJNUGhr779dJW8pgDB5QsH2O7WPjjyBTOQbDYKf5oYAVSyTQ50WUmE5kju_w_PwLOA9XRV1tJBcleHOSyEhJy4U0sKx4WQ5girmoqwF5XrneIdgzYlOqjXlqmJtvJjRmVuljk-TP-fcddjL0BYyJ7i9c0v3GzQL_1WisL_fU0yntezEnGIdRgdketiaNeFZgutI82wu5awsbX0OlsiAkUOpbzGkaLjMu-z6-kryoWuYO7FF3KKDVeuoxs3CuVYbGQFRwuUPj4Nf0Mx_6FkYauUXX3PqQu5frERaYKZ2brmjGLd9wg42kKcXxlubN08w7ml7ZhqEjONtN6jV0-S5sVFw31LknZOESqe2MJofSglWQlYJeTz-NqidsBzUatYNqynZdwJYyu4rW6wkDtb1YLetWrcswGjWcM5qcHwFNfRwyYQ4lP0KstdJfI6MobFv24a0ziq5KA6aoe7cP8bsw9sTYjXR3oR5hTnHciNM7ruVhzEPjOJEPler2QpBebLJIR-GrUvv60C8MxNKe18aH3EjjrHfk6QHu9a1I3vFIJ4q5K9W3BK1azvdYMMd-LpJkCwZBhbriIqd79uGCksAWWGESDOmZ45bXpU2CRH5SKK-tWh5lFgytrnEQ1P6fxASnS1gFwy0vDVnpppGc0-ZG-lP5-R8qXrTM?type=png)](https://mermaid.live/edit#pako:eNp1U9Fq4zAQ_JVFTyq0P5CHg8RyoXBJQ5NwcBjCWt7EoraUk2RoqPvvJ8lO2qSNn9a7M6PdHemdSVMRm7C9xUMNa1FoCN-TruhtK9AjPDz8AkS-rru21KiaoXY34HColyVftdg0CQRrLBu6BEjJ51Sprr2JqCr-G-0-Zof8Hypf6F9Hzqd6L5Ql6Y09grHwqBpyPcx4VpN8hZ3bZihr2q4tylel96P27JqqjQeloQjlb5x-zlcSNZzRlyKPptNVJCfWDQkY9zdPnAVfWiPJOchq1HtykX4tv0jQZ55ZQk9xuM2hilGcEV5IGlu5U9PRkRIdjQYFHI4yz0lmeZL5tGtQOAmc826bdhjP-5ILzblRcJkEBV9RGFsa7Ul78AZko0J097NJn1L9dDqa8-Uu7cJpsYvN5kmA2YE_d-mj9yfV6XRQWwS30tqD0zMulDs0eITcWmMvkVnGxzETfCxm2VVTIEyYON6B_E053wvxbV03qYnh-jwfFvJZuF6JEIma5-yetWRbVFV4Xu-xWDBfU0sFm4Swoh12jS9YoT8CFDtvVkct2cTbju5Zly6BUBgeZssmO2xcyB5Q_zXm9P_xH0P-Nos?bgColor=!white)

### Supported File Types

**Graphics** (Full thumbnail support)
- `.bmp`, `.gif`, `.jpg`, `.jpeg`, `.png`, `.webp`

**Documents**
- **PDFs**: `.pdf` (thumbnail from first page)
- **Text**: `.txt`, `.text` (generic icon)
- **Markdown**: `.markdown` (generic icon)
- **Web**: `.html`, `.htm` (generic icon)

**Archives**
- **RAR**: `.cbr`, `.rar`
- **ZIP**: `.cbz`, `.zip`

**Media**
- **Movies**: `.mp4`, `.mpg`, `.mpg4`, `.mpeg`, `.mpeg4`, `.wmv`, `.flv`, `.avi`, `.m4v` (frame extraction)
- **Audio**: `.mp3` (generic icon)
- **Books**: `.epub` (embedded thumbnail support)

**Links**
- **Shortcuts**: `.link`, `.alias`


## Database Schema

The database is broken into individual applications to aid in the upgrade and modularity of the system.

- QuickBBS - The core database tables
	- **DirectoryIndex**: Contains the Index for the Directories, virtual/alias directories.
	- **FileIndex**: Contains the Index for the individual files 
	- **Thumbnails**: 
		- **ThumbnailFiles**: The Database table that contains the Thumbnail data for the File Index, and Directory Index records.  
		- The thumbnail engine uses a modular system for generating thumbnails:
			- **PDF** - Uses PyMuPDF to render the first page of the PDF into a PIL image and is converted into a thumbnail.
			- **PIL / PILLOW** - Uses PILLOW to convert image formats into a thumbnail
			- **video** - converts a variety of video formats into thumbnails (takes a frame from ½ through the video, converts it to a PIL image, and then into a thumbnail)
		- ~~**v3.75 -** In addition native mac OS support for Core Image, PDFKit, and AVFoundation means that when run under mac OS the thumbnail engine will use those native libraries to optimize the performance of the thumbnail engine.~~
			- There appears to be a memory leak in the Mac OS optimized code.  So while the plugins do still exist, they have been temporarily disabled.  This memory leak seems to be in the GPU side not releasing the memory, and not in the python based code.  
	- Cache_Watcher: 
		- **fs_Cache_Tracking**: The Database table used to store the cache status for the directories in the file system
		- It also contains the Caching engine for the File System that monitors for file system changes (using WatchDog) 
	- **filetypes**: Stores the filetype information for the files that QuickBBS display / process.

### Core Applications

#### 1. **cache_watcher** - File System Monitoring & Cache Invalidation
**Purpose**: Real-time file system monitoring using the Watchdog library to maintain cache consistency.

**Key Components**:
- **`WatchdogManager`**: Manages watchdog process lifecycle with automatic 4-hour restarts for stability
- **`CacheFileMonitorEventHandler`**: Batches filesystem events for efficient bulk processing (5-second buffer)
- **`LockFreeEventBuffer`**: Thread-safe event buffering with automatic deduplication and memory management
- **`fs_Cache_Tracking`**: Database model tracking cache invalidation state for each directory

**Features**:
- **Event Batching**: Buffers changes for 5 seconds to handle bulk operations efficiently
- **Automatic Restarts**: Watchdog can be restarted on a regular basis to prevent memory leaks
- **Thread Safety**: Lock-free buffer design reduces contention during high file activity
- **Smart Invalidation**: Only invalidates affected directories, preserving unrelated cached data

#### 2. **filetypes** - File Type Detection & Management
**Purpose**: Centralized file type classification with performance-optimized database queries.

**Key Components**:
- **`filetypes` Model**: Core file type definitions with boolean flags for quick categorization
- **Extension Normalization**: Consistent lowercase formatting with dot prefixes
- **Generic Icon System**: Fallback icons for unknown file types stored as binary thumbnails
- **MIME Type Management**: Proper content-type headers for file serving

**Features**:
- **Boolean Categorization**: Fast queries using `is_image`, `is_archive`, `is_pdf`, etc. flags
- **LRU Caching**: Heavily cached queries for frequently accessed types
- **Icon Integration**: Generic thumbnails stored as binary data in the database
- **Extension Mapping**: Comprehensive mapping from file extensions to categories and MIME types

#### 3. **frontend** - Main Application Logic & Web Interface
**Purpose**: Core web interface with optimized HTMX-powered gallery rendering and search functionality.

**Key Components**:
- **`views.py`**: HTMX-enabled view handlers for galleries, search, and file operations
- **`managers.py`**: Layout management with database-level pagination and LRU caching
- **`utilities.py`**: Helper functions for breadcrumbs, path conversion, and sorting
- **`web.py`**: Authentication, mobile detection, and file serving utilities

**Performance Features**:
- **Database-Level Pagination**: Uses PostgreSQL LIMIT/OFFSET instead of loading full datasets
- **Layout Manager Cache**: LRU cache for frequently accessed gallery layouts
- **Context Building Cache**: Optimized single-pass dictionary creation for item views
- **Async-Compatible Operations**: Database operations wrapped with `sync_to_async` for ASGI/WSGI compatibility

**Template System (v3.95+)**:
- **Jinja2 Macro System**: Reusable template components reduce code duplication by 70-80%
- **Component Architecture**: Modular UI fragments (navbar, breadcrumbs, pagination, cards)
- **External CSS**: All styles extracted from templates for better browser caching
- **DRY Principles**: Single source of truth for HTMX patterns, metadata display, and navigation

**HTMX Integration**:
- HTMX is used to make this gallery into a progressive web application, reducing latency and simplifying the web front-end
- Smart partial page updates without full reloads
- Optimized scroll behavior and loading states

#### 4. **quickbbs** - Core Configuration & Shared Models
**Purpose**: Django project configuration and shared database models.

**Key Components**:
- **`settings.py`**: Main Django configuration with database caching and security settings
- **`quickbbs_settings.py`**: Application-specific configuration (paths, image sizes, file mappings)
- **`models.py`**: Shared database models for FileIndex and DirectoryIndex
- **URL Configuration**: Centralized routing for all application endpoints

#### 5. **thumbnails** - Thumbnail Generation & Binary Storage
**Purpose**: High-performance thumbnail generation and PostgreSQL binary blob storage.

**Key Components**:
- **`ThumbnailFiles` Model**: Core storage with SHA256-indexed binary fields for 3 thumbnail sizes
- **`thumbnail_engine.py`**: Multi-format thumbnail generation (images, PDFs, videos, archives)
- **`core_image_thumbnails.py`**: PIL-based image processing with optimized resizing algorithms
- **Binary Storage**: Small (200x200), Medium (740x740), Large (1024x1024) thumbnails as PostgreSQL blobs

**Performance Features**:
- **Database Storage**: Thumbnails stored as binary data in PostgreSQL for better I/O performance than file system
- **Optimized Indexes**: Partial indexes on SHA256 lookups and thumbnail existence checks
- **Prefetch Lists**: Predefined `ThumbnailFiles_Prefetch_List` constants to avoid N+1 queries
- **Multi-Format Support**: Unified pipeline for images, PDFs, videos, and archive thumbnails
- **macOS Native Support**: When running on macOS, uses native frameworks (AVFoundation, PDFKit, Core Image) for optimized thumbnail generation performance

**Storage Philosophy**:
Store thumbnails as PostgreSQL binary blobs rather than separate files, making the database the I/O bottleneck instead of disk operations for significantly better performance at scale.

## API Documentation

QuickBBS uses HTMX-enabled endpoints for dynamic gallery interactions. All endpoints support both full page loads and HTMX partial updates.

### Core Endpoints

#### Gallery & Navigation
- **`GET /albums/`** - Root gallery listing
- **`GET /albums/{path}`** - Directory gallery view with pagination
- **`GET /view_item/{sha256}/`** - Individual file viewer with metadata

#### Search & Discovery
- **`GET /search/?searchtext={query}&page={n}`** - File and directory search
- **`GET /search/`** - Search interface (no query parameters)

#### Media & Downloads
- **`GET /thumbnail2_file/{sha256}`** - File thumbnail (small/medium/large)
- **`GET /thumbnail2_directory/{dir_sha256}`** - Directory thumbnail
- **`GET /download_file/?{params}`** - Direct file download with range support

#### Static Resources
- **`GET /static/{path}`** - Static assets (CSS, JS, images)
- **`GET /resources/{path}`** - Resource files (fonts, icons)

### HTMX Integration

QuickBBS extensively uses HTMX for seamless navigation:

- **Page Navigation**: Gallery pages use `hx-boost="true"` for enhanced links
- **Content Updates**: `hx-target="body"` and `hx-swap="outerHTML"` for full page updates
- **Dynamic Loading**: Thumbnail generation happens asynchronously in background
- **Search Results**: Real-time search with pagination via HTMX requests

### Template Selection

The application automatically selects templates based on request type:
- **Full Page**: `{view}_complete.jinja` for standard HTTP requests
- **HTMX Partial**: `{view}_partial.jinja` for HTMX-boosted requests
- **Components**: `{view}_menu.jinja` and `{view}_sidebar.jinja` for fragments

### Authentication

- **Optional Login**: Controlled via `QUICKBBS_REQUIRE_LOGIN` setting
- **Django Allauth**: Integrated authentication system at `/accounts/`
- **Admin Interface**: Django admin at `/Admin/` (Grappelli-enhanced)

## Technology Stack

- **Backend**: Django 4.1+ (currently using 6.0a1), Python 3.12-3.14
- **Database**: PostgreSQL with binary blob storage (currently used - testing needed for other engines). Optimized for Django & PostgreSQL features (binary blobs, partial indexes), but compatible with any Django ORM-compliant database.
- **Frontend**: HTMX for dynamic interactions, Jinja2 templates
- **File Monitoring**: Watchdog library
- **Development**: Poetry, pytest, mypy, black, isort, pylint

## Roadmap

- ✅ **v3.0 Core Features** - Gallery system, thumbnail caching, Watchdog monitoring
- ✅ **v3.5 Release** - Full HTMX support, performance optimizations, code cleanup
- ✅ **v3.75 Release** - Enhance Bulma Framework utilization, enhance HTMX support, performance optimizations, code cleanup
- ✅ **v3.80 Release** - Major code cleanup, reducing redundant string operations, utilizing more functionality from the move to SHA256 based identifiers, adding the ability to hide duplicate images in a gallery via user-preferences
- ✅ **v3.85 Release** - Database performance optimizations, composite indexes, virtual directory bug fixes
- ✅ **v3.90 Release** - Model renaming and code organization (FileIndex, DirectoryIndex)
- ✅ **v3.95 Release** - Template system optimization with Jinja2 macros, CSS extraction, component architecture
- 🔄 **Active Development** - Enhanced search capabilities, UI improvements, continued performance optimization

[Detailed Version History](Version%20History.md)


## Contributing

1. Fork the repository
2. Create a feature branch
3. Make changes following the code style (black, isort, mypy)
4. Run tests: `pytest`
5. Submit a pull request

## License

MIT License - See license.txt for details

## Version History

[See Detailed Version History](Version%20History.md)

