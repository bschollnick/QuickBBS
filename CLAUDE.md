# CLAUDE.md

This file provides guidance to Claude Code when working with the QuickBBS codebase.

## 📂 Documentation Organization

**Detailed documentation has been split into focused files in the `.claude/` directory.**

See [.claude/README.md](.claude/README.md) for the complete documentation structure.

### Quick Links

- **[Commands](.claude/commands.md)** - Quick command reference (runserver, migrations, code quality)
- **[Critical Runtime Rules](.claude/critical-runtime.md)** - ⚠️ **READ FIRST** - ASGI/WSGI, threading, Django ORM safety
- **[Architecture](.claude/architecture.md)** - Project structure, apps, design principles
- **[Development Standards](.claude/development.md)** - Code quality, type hints, ORM optimization
- **[Templates & Frontend](.claude/templates-frontend.md)** - Template system, HTMX, CSS management

## 🚨 Critical Rules Summary

### ASGI/WSGI Compatibility
- **NEVER use `thread_sensitive=False`** with Django ORM
- **NEVER use ThreadPoolExecutor** with Django ORM
- Keep functions simple - don't mix async/sync boundaries
- Use `transaction.atomic()` for all DB writes
- Call `close_old_connections()` after expensive operations

See [.claude/critical-runtime.md](.claude/critical-runtime.md) for details.

### Static Files Organization
- **Custom assets** → `resources/` directory (NOT `static/`)
- **Django/packages** → `static/` directory only
- Rule: If you created it, it goes in `resources/`

### Type Hints (Python 3.14)
```python
from __future__ import annotations

# ✓ Use these
def process(data: dict[str, Any]) -> list[str] | None: ...

# ✗ Don't use these
def process(data: Dict[str, Any]) -> Optional[List[str]]: ...
```

### Django ORM Optimization
- **Forward FKs/OneToOne** → `select_related()` (SQL JOINs)
- **Reverse FKs/M2M** → `prefetch_related()` (separate queries)
- **NEVER use both** on the same relationship

See [.claude/development.md](.claude/development.md) for details.

### File System Rules
- **NEVER modify `albums/` directory** - Gallery content, not code
- **NEVER search `/Volumes/C-8TB/gallery/quickbbs/albums/` path** - This is user gallery content, NOT source code
  - When searching for templates → use `templates/` directory
  - When searching for static files → use `resources/` or `static/` directories
  - When searching for Python code → use `quickbbs/` and app directories
  - The `albums/` path contains ONLY user gallery files (images, videos, PDFs, etc.)
- **Always use `normalize_fqpn()`** before path operations
- File handles using `send_file_response` intentionally omit context managers (function closes them)

## ⚡ Quick Start

```bash
# Working directory (source code root)
cd /Volumes/C-8TB/gallery/quickbbs/quickbbs/

# Project structure
# /Volumes/C-8TB/gallery/quickbbs/
# ├── quickbbs/           ← SOURCE CODE (work here)
# │   ├── templates/      ← Django templates
# │   ├── resources/      ← Custom CSS/JS
# │   ├── static/         ← Django/package assets
# │   └── [apps]/         ← Python modules
# └── albums/             ← USER GALLERY CONTENT (NEVER search here)

# Run dev server
python manage.py runserver 0.0.0.0:8888

# Format & lint (use wrapper)
cd .. && ./format_code.sh frontend/utilities.py

# After any code changes (MANDATORY)
python -m pylint <module>  # Compare before/after scores
```

## 🔧 Development Workflow

1. Make code changes
2. Run `./format_code.sh <files>` (black + isort)
3. Run `PYTHONPATH=. mypy quickbbs/` (type checking)
4. **MANDATORY**: Run `python -m pylint <module>` - note score
5. Fix all ERRORS and TYPE HINTS
6. Re-run pylint and compare scores
   - ✅ Improved/same → Complete
   - ❌ Decreased → STOP and report

See [.claude/commands.md](.claude/commands.md) for all commands.

## 📖 For More Details

All detailed documentation is in the `.claude/` directory:

```
.claude/
├── README.md                 # Overview & file guide
├── commands.md               # Command reference
├── critical-runtime.md       # ASGI/WSGI, threading (READ FIRST for runtime changes)
├── architecture.md           # Structure, apps, design
├── development.md            # Code standards, testing
└── templates-frontend.md     # Templates, HTMX, CSS
```

Start with [.claude/README.md](.claude/README.md) for guidance on which file to read based on your task.
