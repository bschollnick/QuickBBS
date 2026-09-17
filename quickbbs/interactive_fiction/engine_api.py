"""QuickBBS's own plugin-source assembly for `ink_engine.discovery.discover_plugins()`.

The discovery/binding machinery lives in the standalone `ink_engine`
library (`/Volumes/Support-8tb/Gallery/interactive_fiction/ink_engine/`,
distinct from this Django app's own `interactive_fiction` package name).
Trust-gating has NO home in that library at all — `ink_engine` never
imports Django and never sees a `Story` row. **Deciding which sources are
safe to scan is this module's only real job**; the engine then scans
exactly what it is handed.

**What changed from the OLD system**: the OLD `discover_api_descriptors()`
scanned `engine_plugins/` by dotted import AND walked every game folder
under Albums via `importlib.util.spec_from_file_location` into a
synthetic `interactive_fiction._games.<game>.<module>` namespace requiring
hand-built parent packages in `sys.modules`. The NEW `discover_plugins()`
(in `ink_engine.discovery`) never does that — it takes a flat list of
importable dotted names and uses ordinary Python import machinery for
every one of them. Making a trusted game importable — a folder by its
parent, a bundle by the archive itself, which `zipimport` resolves — is
plain packaging, so the engine supplies it as `mount_game()`; this module
decides WHICH games earn that call.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ink_engine.discovery import (
    ENGINE_PLUGIN_PACKAGE,
    discover_plugins,
    mount_game,
)
from ink_engine.plugin import Plugin
from quickbbs.directoryindex import DirectoryIndex
from quickbbs.MonitoredCache import ThreadSafeLRUCache

logger = logging.getLogger(__name__)

# Cache for discover_api_descriptors()'s result — it's called at least once
# per turn (play/play_submit/play_undo/play_restart/panel actions), but the
# underlying scan only changes at two real points: a Story is saved (trust
# flag toggled in admin — see clear_api_descriptor_cache's post_save
# receiver below) or scan_if_stories runs (game folders added/removed on
# disk — see sync_engine_apis()'s own call to clear it). No TTL: this is
# invalidated exactly when the facts change, not approximated by a timer.
_API_DESCRIPTOR_CACHE_KEY = "descriptors"
_api_descriptor_cache: ThreadSafeLRUCache = ThreadSafeLRUCache(maxsize=1)


def clear_api_descriptor_cache() -> None:
    """Drop the cached `discover_api_descriptors()` result.

    Called whenever the underlying facts can have changed: a `Story` is
    saved (its `is_engine_trusted` flag may have flipped) or a scan runs
    (game folders may have been added/removed on disk).
    """
    _api_descriptor_cache.pop(_API_DESCRIPTOR_CACHE_KEY, None)


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
    # module load time (for discover_api_descriptors()) -- a top-level
    # import here would be a real circular import, not just a style
    # preference.
    from interactive_fiction.models import (  # pylint: disable=import-outside-toplevel
        Story,
    )

    games_root = Path(DirectoryIndex.get_albums_root()) / "interactive_fiction"
    if not games_root.is_dir():
        return []

    # A bundle sits either in the games root or one level down in its own
    # game folder, which is how the published bundles are laid out.
    candidates = list(games_root.iterdir())
    candidates.extend(
        entry for game_dir in games_root.iterdir() if game_dir.is_dir() for entry in game_dir.iterdir() if entry.suffix.lower() == ".zip"
    )

    trusted_names: list[str] = []
    for game in sorted(candidates, key=str):
        if game.is_dir() and (game / "__init__.py").exists():
            # A folder game's Story points at a file INSIDE it.
            is_trusted = Story.objects.filter(source_fqfn__startswith=str(game).rstrip("/") + "/", is_engine_trusted=True).exists()
        elif game.is_file() and game.suffix.lower() == ".zip":
            # A bundle's Story points at the bundle itself. Matched
            # exactly: a prefix match would let `<game>.zip.bak` claim
            # `<game>.zip`'s trust.
            is_trusted = Story.objects.filter(source_fqfn=str(game), is_engine_trusted=True).exists()
        else:
            continue

        if not is_trusted:
            logger.info(
                "interactive_fiction.engine_api: skipping '%s' — no trusted Story marks this game safe to execute (Story.is_engine_trusted)",
                game.name,
            )
            continue

        # mount_game() takes a folder or a bundle and releases its
        # sys.path entry; make_game_folder_importable() never released
        # one, so a second game of the same package name resolved to the
        # first. The mount is held, not released, because the modules it
        # makes importable stay imported for the worker's life.
        package = mount_game(game).package
        # One game can be present as both a folder and a bundle inside it
        # while a library is being converted. Mounting both would offer
        # discover_plugins() the same package twice, which it rightly
        # rejects as a duplicate plugin name.
        if package not in trusted_names:
            trusted_names.append(package)
    return trusted_names


def discover_api_descriptors() -> dict[str, Plugin]:
    """Scan the engine's own generic plugin directory plus every trusted
    game folder, and return their combined `Plugin`s.

    Cached until `clear_api_descriptor_cache()` is called — this is called
    at least once per turn, and the underlying directory scan / trust query
    only changes on a game-folder scan or a `Story` save (trust flag
    toggled in admin), both of which explicitly clear the cache.

    Returns:
        A dict of {plugin_name: Plugin}, spanning the generic plugin
        directory and every currently-trusted game folder.

    Raises:
        ValueError: Two sources declare a `Plugin` with the same name — a
            real, unambiguous configuration error, never silently
            resolved by picking one arbitrarily.
    """
    cached = _api_descriptor_cache.get(_API_DESCRIPTOR_CACHE_KEY)
    if cached is not None:
        return cached

    descriptors = discover_plugins([ENGINE_PLUGIN_PACKAGE] + _trusted_game_module_names())
    _api_descriptor_cache[_API_DESCRIPTOR_CACHE_KEY] = descriptors
    return descriptors
