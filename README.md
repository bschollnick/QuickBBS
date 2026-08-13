QuickBBS Gallery
================

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](license.txt)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![Django 6.1+](https://img.shields.io/badge/django-6.1%2B-092e20.svg)](pyproject.toml)

A high-performance, self-hosted Django gallery and file browser, built on a hybrid file system + database design. Point it at a directory tree of images, PDFs, archives, video, and audio, and it indexes, thumbnails, and serves them through a fast, responsive web UI.

This README covers the essentials — installation, running it, and a feature overview. For architecture, deployment options, database schema, and everything else, the **[`docs/`](docs/) directory is the complete, authoritative reference**; start at [`docs/QuickBBS.md`](docs/QuickBBS.md).

## Features

* **File Areas / Image Galleries** — comprehensive gallery system with database-stored thumbnails
* **Multi-format support** — images, PDFs, archives, text files, movies, audio, and more
* **High performance** — thumbnail caching in PostgreSQL for optimal I/O, plus ASGI support (HTTP/1.1 and HTTP/2)
* **Real-time monitoring** — watchdog-based file system monitoring for automatic cache invalidation
* **Responsive design** — multiple thumbnail sizes for desktop and mobile
* **Search & browse** — file and directory search with metadata indexing
* **Modern template system** — Jinja2 macros with a component architecture
* **Progressive Web App** — HTMX-powered dynamic updates without full page reloads
* **Background task worker** — thumbnail generation and maintenance run outside the request cycle via `django-dbtasks`
* **Passkey login** — optional passwordless (WebAuthn) authentication

## Screenshots

Gallery cells are color-coded by filetype — blue for directories, pink for
images, yellow for PDFs/links, gray for movies/audio — so you can tell what
you're looking at before a thumbnail even loads. These colors are just
defaults seeded by `refresh_filetypes` and can be freely redefined per
extension (via the Django admin or the seed command) to match your taste.

<table>
<tr>
<td><img src="docs/images/Viewing mixed directory of content.png" alt="Mixed directory of content" width="400"></td>
<td><img src="docs/images/Viewing directory of PDFs.png" alt="Directory of PDFs" width="400"></td>
</tr>
<tr>
<td><img src="docs/images/Viewing directory of graphics.png" alt="Directory of graphics" width="400"></td>
<td><img src="docs/images/Viewing a larger movie (while playing).png" alt="Playing a movie" width="400"></td>
</tr>
</table>

More screenshots — PDF viewing, thumbnails, and video playback — are in [`docs/Screenshots.md`](docs/Screenshots.md), including the full filetype color legend.

## Quick Start

Requires Python 3.12–3.14, Django 6.1+, and PostgreSQL. Django 6.1 is a hard minimum — `FileIndex`/`DirectoryIndex` use the `DB_CASCADE`/`DB_SET_NULL` on_delete options (DB-enforced `ON DELETE` constraints), which don't exist before 6.1.

```bash
git clone https://github.com/bschollnick/quickbbs.git
cd quickbbs
poetry install
```

`gunicorn`, `uvicorn`, `hypercorn`, and `granian` are optional Poetry extras — `poetry install` alone installs none of them. Add the one you plan to deploy with, e.g. `poetry install --extras granian` (or `--extras all-servers` for all four). See [`docs/Web Servers.md`](docs/Web%20Servers.md#installing-a-web-server) for details.

Configure your database and gallery root, then run migrations:

```bash
cd quickbbs
python manage.py migrate
```

QuickBBS needs **two processes** running side by side — the web server and the background task worker (thumbnail generation won't happen without it):

```bash
# Web server (development)
python manage.py runserver 0.0.0.0:8888

# Background task worker (separate terminal)
python manage.py taskrunner -w 4
```

For production, QuickBBS is tested against Granian and Hypercorn (both ASGI, native HTTP/2). Other ASGI/WSGI servers such as Uvicorn, Daphne, and Gunicorn should also work but aren't part of our regular test cycle. Large-scale deployments may instead front the app with Apache, nginx, or Caddy as a reverse proxy — see [`docs/Web Servers.md`](docs/Web%20Servers.md) for full deployment options, reverse proxy configs, HTTPS setup, and installing the server you choose as a Poetry extra.

## Documentation

**The [`docs/`](docs/) directory is where the complete documentation lives** — this README is intentionally just a quick-start. Head there for anything beyond the basics, including:

* [Full documentation](docs/QuickBBS.md) — start here
* [Screenshots](docs/Screenshots.md) — UI tour and filetype color legend
* [Web Servers & Deployment](docs/Web%20Servers.md)
* [Database ERD](docs/DATABASE_ERD.md)
* [Links & Aliases](docs/Links%20&%20Aliases.md)
* [Version History](docs/Version%20History.md)
* [Design documents](docs/design%20documents/) — architecture and design rationale

## License

MIT — see [license.txt](license.txt).
