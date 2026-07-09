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
* **Modern Template System** - Jinja2 macros with component architecture for maintainable, efficient templates
* **Progressive Web App** - HTMX-powered dynamic updates without full page reloads
* **Background Task Worker** - Thumbnail generation and maintenance run outside the web request cycle via django-dbtasks
* **Passkey Login** - Optional passwordless (WebAuthn) authentication

## Current Version

**Version 4.00** (July 2026) - Passkey authentication, django-dbtasks background task infrastructure, re-engineered alias/link resolution, and major query performance optimizations

For more information, please see the complete documentation in the DOCS directory.