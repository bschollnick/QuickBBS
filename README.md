QuickBBS Gallery
================

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](license.txt)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)
[![Django 6.1+](https://img.shields.io/badge/django-6.1%2B-092e20.svg)](pyproject.toml)

A high-performance, self-hosted Django gallery and file browser, built on a hybrid file system + database design. Point it at a directory tree of images, PDFs, archives, video, and audio, and it indexes, thumbnails, and serves them through a fast, responsive web UI.

This README covers the essentials — installation, running it, and a feature overview. For architecture, deployment options, database schema, and everything else, the **[`Docs/`](Docs/) directory is the complete, authoritative reference**; start at [`Docs/index.md`](Docs/index.md).

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

## Quick Start

Requires Python 3.12–3.14, Django 6.1+, and PostgreSQL. Django 6.1 is a hard minimum — `FileIndex`/`DirectoryIndex` use the `DB_CASCADE`/`DB_SET_NULL` on_delete options (DB-enforced `ON DELETE` constraints), which don't exist before 6.1.

```bash
git clone https://github.com/bschollnick/quickbbs.git
cd quickbbs
poetry install
```

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

For production, QuickBBS is tested against Granian and Hypercorn (both ASGI, native HTTP/2). Other ASGI/WSGI servers such as Uvicorn, Daphne, and Gunicorn should also work but aren't part of our regular test cycle. Large-scale deployments may instead front the app with Apache, nginx, or Caddy as a reverse proxy — see [`Docs/Web Servers.md`](Docs/Web%20Servers.md) for full deployment options, reverse proxy configs, and HTTPS setup.

## Documentation

**The [`Docs/`](Docs/) directory is where the complete documentation lives** — this README is intentionally just a quick-start. Head there for anything beyond the basics, including:

* [Documentation index](Docs/index.md) — start here
* [Web Servers & Deployment](Docs/Web%20Servers.md)
* [Database ERD](Docs/DATABASE_ERD.md)
* [Links & Aliases](Docs/Links%20&%20Aliases.md)
* [Version History](Docs/Version%20History.md)
* [Design documents](Docs/design%20documents/) — architecture and design rationale

## License

MIT — see [license.txt](license.txt).
