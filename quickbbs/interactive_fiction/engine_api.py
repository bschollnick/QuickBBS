"""QuickBBS's own plugin-source assembly for `ink_engine.discovery.discover_plugins()`.

Redesigned 2026-09-08 as part of `claude_docs/plans/ink_engine_standalone_extraction.md`
Step 5: the engine's own discovery/binding machinery (the OLD
`EngineAPIDescriptor`/synthetic-namespace/`also_reads`/`bind_stateful`
system) moved to the standalone `ink_engine` library
(`/Volumes/Support-8tb/Gallery/interactive_fiction/ink_engine/`,
distinct from this Django app's own `interactive_fiction` package name).
Trust-gating and game-folder-importability have NO home in that library
at all — `ink_engine` never imports Django, never sees a `Story` row,
never constructs a package spec from a raw directory. Both concerns live
here instead, entirely as QuickBBS's own code.

**What changed from the OLD system**: the OLD `discover_api_descriptors()`
scanned `engine_plugins/` by dotted import AND walked every game folder
under Albums via `importlib.util.spec_from_file_location` into a
synthetic `interactive_fiction._games.<game>.<module>` namespace requiring
hand-built parent packages in `sys.modules`. The NEW `discover_plugins()`
(in `ink_engine.discovery`) never does that — it takes a flat list of
sources, where a "directory" source must already be a real, imported
Python package, and a "module name" source must already be importable by
ordinary `importlib.import_module()`. Making a trusted game folder
importable at all is this module's job now (`_ensure_importable`, a
one-time `sys.path` insertion — real Python package semantics, not a
synthetic namespace).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import ink_engine.engine_plugins
from ink_engine.discovery import discover_plugins
from ink_engine.plugin import Plugin
from quickbbs.directoryindex import DirectoryIndex

logger = logging.getLogger(__name__)


def _generic_plugin_sources() -> list[Path]:
    """Return the engine's own shipped plugin directory, always scanned.

    Returns:
        A one-item list holding `ink_engine.engine_plugins`'s own
        directory — the generic, story-agnostic mechanics that ship with
        the engine regardless of which game is loaded.
    """
    return [Path(ink_engine.engine_plugins.__file__).parent]


def _ensure_importable(game_dir: Path) -> str:
    """Make one trusted game folder's real Python package importable, and
    return its dotted module name.

    A game folder under the Albums tree (e.g. `Albums/interactive_fiction/
    <game>/`, containing a real `__init__.py`) is already a genuine Python
    package on disk — it only needs its PARENT directory on `sys.path` for
    ordinary `importlib.import_module(game_dir.name)` to find it, exactly
    like any other installed package. This is a one-time, idempotent
    `sys.path` insertion per distinct parent directory (every game folder
    under the same Albums `interactive_fiction/` root shares one parent),
    not a per-request cost.

    Args:
        game_dir: The trusted game folder's real filesystem path (must
            contain `__init__.py`).

    Returns:
        The game's own dotted module name (its bare folder name), ready
        to pass to `discover_plugins()` as a module-mode source.
    """
    parent = str(game_dir.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return game_dir.name


def _trusted_game_module_names() -> list[str]:
    """Return every trusted game folder's dotted module name.

    QuickBBS's own trust decision, entirely outside `ink_engine`: every
    game folder under Albums whose `Story` row is `is_engine_trusted`,
    made importable and resolved to its dotted module name. This is where
    the OLD system's `Story.objects.filter(...).exists()` check lived
    before (`_game_folder_is_trusted`) — same query, same trust flag, new
    location, no synthetic namespace involved.

    Returns:
        Dotted module names ready to pass to `discover_plugins()`, one per
        trusted game folder. A folder with no matching trusted `Story` row
        is skipped (not an error — it is still browsable/listable,
        just never executed), logged for visibility.
    """
    # Deferred import: interactive_fiction.models imports THIS module at
    # module load time (StorySystemConfig.clean() calls
    # discover_api_descriptors()) -- a top-level import here would be a
    # real circular import, not just a style preference.
    from interactive_fiction.models import (  # pylint: disable=import-outside-toplevel
        Story,
    )

    games_root = Path(DirectoryIndex.get_albums_root()) / "interactive_fiction"
    if not games_root.is_dir():
        return []

    trusted_names: list[str] = []
    for game_dir in sorted(p for p in games_root.iterdir() if p.is_dir() and (p / "__init__.py").exists()):
        folder_prefix = str(game_dir).rstrip("/") + "/"
        if Story.objects.filter(source_fqfn__startswith=folder_prefix, is_engine_trusted=True).exists():
            trusted_names.append(_ensure_importable(game_dir))
        else:
            logger.info(
                "interactive_fiction.engine_api: skipping '%s' — no trusted Story marks this game safe to execute (Story.is_engine_trusted)",
                game_dir.name,
            )
    return trusted_names


def discover_api_descriptors() -> dict[str, Plugin]:
    """Scan the engine's own generic plugin directory plus every trusted
    game folder, and return their combined `Plugin`s.

    Returns:
        A dict of {plugin_name: Plugin}, spanning the generic plugin
        directory and every currently-trusted game folder.

    Raises:
        ValueError: Two sources declare a `Plugin` with the same name — a
            real, unambiguous configuration error, never silently
            resolved by picking one arbitrarily.
    """
    return discover_plugins(_generic_plugin_sources() + _trusted_game_module_names())
