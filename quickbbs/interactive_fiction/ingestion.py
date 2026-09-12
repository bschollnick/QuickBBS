"""Scanner ingestion for game folders under Albums/interactive_fiction/
(Step 9; re-scoped per the game-folder separation design work).

Two entry points the scan command calls as an additive post-pass after its
own normal work — the only touch to existing scan code is two call sites in
quickbbs/management/commands/scan.py, not a change to update_database_from_disk
itself:

- ingest_stories(): after --add_files, create a Story for every real game
  folder under Albums/interactive_fiction/ with no matching
  Story.source_fqfn yet.
- verify_stories(): after --verify_files, tombstone Story rows whose source
  file is gone, and re-validate/refresh rows whose source file changed
  (sha256 drift) or reappeared after being tombstoned.

**Game-folder model**: a game is a
directory directly under `Albums/interactive_fiction/` containing exactly
one mandatory `__init__.py` manifest (GAME_TITLE, GAME_AUTHOR,
REQUIRED_PLUGINS, MAIN_STORY_FILE). One folder maps onto exactly one
Story row, built from the `.inkj` file MAIN_STORY_FILE names — a .inkj is
already a complete, self-contained game, never a chapter of something
larger, so any OTHER .inkj present in the same folder is simply ignored
by ingestion. A folder missing `__init__.py`, or whose MAIN_STORY_FILE
doesn't match a real file present, is a real, explicit ingestion failure
for that one folder (Story.game_ingestion_error set, surfaced in Django
admin per the plan's own decided hard-failure + admin-visible-flag
behavior) — never a silent skip or a guessed fallback.
REQUIRED_PLUGINS is copied onto the Story row verbatim from the manifest
(plain strings, read via `ink_engine.game_folder.read_module_literals()`
like every other manifest field) — ingestion never resolves these names against
`discover_api_descriptors()`, since that would require the game's own
`.py` files to already be loaded (real code execution), which is exactly
what `Story.is_engine_trusted` gates on. Resolving/loading those plugins
for real is a separate, later, explicit admin action (marking the Story
trusted), not a precondition for the Story existing at all.

Every real .inkj candidate still goes through Step 4's full validation
(validate_story_upload, imported from interactive_fiction.story_views) —
a mislabeled .inkj that isn't compiled Ink is rejected and logged, never
stored as a story.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from ink_engine.game_folder import read_module_literals

from interactive_fiction.image_linking import reconcile_story_images
from interactive_fiction.images import find_file_by_path, link_story_image
from interactive_fiction.models import Story
from interactive_fiction.story_views import (
    create_story_from_compiled_json,
    unique_story_slug,
    validate_story_upload,
)
from quickbbs.common import normalize_fqpn
from quickbbs.models import DirectoryIndex, FileIndex

logger = logging.getLogger(__name__)


class _GameManifestError(Exception):
    """A real, explicit game-folder ingestion failure — the message is
    stored verbatim in Story.game_ingestion_error and logged, never
    silently swallowed."""


# The only manifest fields ever read (see _resolve_main_story_path,
# _apply_game_manifest_fields).
_MANIFEST_FIELDS = ("GAME_TITLE", "GAME_AUTHOR", "REQUIRED_PLUGINS", "MAIN_STORY_FILE", "NEW_GAME_FIELDS", "SOURCE_GAME_VERSION", "PLAY_LAYOUT")


def _load_game_manifest(game_dir: Path) -> Any:
    """Read one game folder's `__init__.py` manifest, filtered to `_MANIFEST_FIELDS`.

    A thin QuickBBS-specific layer over `ink_engine.game_folder.read_module_literals()`
    (the shared AST-as-data primitive — never imports/execs the file, since
    a game folder lives in the untrusted Albums tree and its manifest must
    be readable before any Story exists to grant it is_engine_trusted):
    this function's own job is filtering the result down to the fields
    ingestion cares about, warning (not hard-failing) on one assigned a
    non-literal expression, and raising only when the file itself is
    missing — all real QuickBBS ingestion policy, not something the
    shared primitive should have an opinion on.

    Args:
        game_dir: The game folder's real filesystem path.

    Returns:
        A SimpleNamespace exposing whichever of `_MANIFEST_FIELDS` were
        found as plain literal assignments (missing fields, including one
        assigned a non-literal expression, are simply absent attributes,
        matching the old module's own `getattr(..., default)` call sites).

    Raises:
        _GameManifestError: `__init__.py` is missing.
    """
    init_path = game_dir / "__init__.py"
    if not init_path.exists():
        raise _GameManifestError(f"Game folder '{game_dir.name}' has no __init__.py manifest")
    result = read_module_literals(init_path)
    non_literal_fields = result.skipped & set(_MANIFEST_FIELDS)
    if non_literal_fields:
        logger.warning(
            "Game folder '%s': __init__.py assigns %s to a non-literal expression, ignoring",
            game_dir.name,
            sorted(non_literal_fields),
        )
    fields = {name: value for name, value in result.literals.items() if name in _MANIFEST_FIELDS}
    return SimpleNamespace(**fields)


def read_manifest_value(game_dir: Path, field: str, default: Any = None) -> Any:
    """Read one literal value from a game folder's `__init__.py` manifest.

    The manifest is the single source of truth for everything about a
    game, so anything a game declares about itself — which play layout it
    wants, what it is called — is read from here rather than copied onto a
    Story column where the two could drift apart.

    Parsed with `ast`, never imported: a game folder lives in the
    untrusted Albums tree (see `_load_game_manifest`).

    Args:
        game_dir: The game folder's real filesystem path.
        field: The manifest name to read. Must be one of
            `_MANIFEST_FIELDS`; anything else is not extracted by the
            parser and so always yields `default`.
        default: What to return when the folder has no readable manifest,
            or the manifest does not assign this field.

    Returns:
        The literal value, or `default`.
    """
    try:
        manifest = _load_game_manifest(game_dir)
    except _GameManifestError:
        return default
    return getattr(manifest, field, default)


def _resolve_main_story_path(game_dir: Path, manifest: Any) -> str:
    """Resolve which real `.inkj` file in `game_dir` is this game's Story source.

    Args:
        game_dir: The game folder's real filesystem path.
        manifest: The already-loaded manifest module (see _load_game_manifest).

    Returns:
        The main story file's full path, as a string.

    Raises:
        _GameManifestError: The manifest has no MAIN_STORY_FILE, or names
            a file that doesn't exist in `game_dir` — any other .inkj
            files present are not a valid fallback, per the plan's own
            "ignore, don't guess" rule.
    """
    main_story_file = getattr(manifest, "MAIN_STORY_FILE", None)
    if not main_story_file:
        raise _GameManifestError(f"Game folder '{game_dir.name}': __init__.py has no MAIN_STORY_FILE")
    main_story_path = game_dir / main_story_file
    if not main_story_path.is_file():
        raise _GameManifestError(f"Game folder '{game_dir.name}': MAIN_STORY_FILE '{main_story_file}' does not exist in this folder")
    return str(main_story_path)


def game_folders() -> list[Path]:
    """Return every real game folder directly under Albums/interactive_fiction/.

    A "game folder" here means any directory at all under that path — a
    missing `__init__.py` is a real ingestion failure for that folder
    (see `_ingest_one_game_folder`), not grounds to exclude it from this
    listing; distinguishing "not a game" from "a broken game" is exactly
    the point of surfacing errors in admin rather than silently skipping.

    Args:
        None.

    Returns:
        Every direct subdirectory of Albums/interactive_fiction/, sorted
        by name. Empty if that path doesn't exist at all yet.
    """
    games_root = Path(DirectoryIndex.get_albums_root()) / "interactive_fiction"
    if not games_root.is_dir():
        return []
    return sorted((p for p in games_root.iterdir() if p.is_dir()), key=lambda p: p.name)


def _get_scan_owner():
    """Look up the dedicated scanner-ingestion owner account.

    Args:
        None.

    Returns:
        The User instance named by settings.IF_SCAN_DEFAULT_OWNER, or None
        if that account doesn't exist — callers must fail loudly (log,
        skip) rather than guessing an owner.
    """
    try:
        return get_user_model().objects.get(username=settings.IF_SCAN_DEFAULT_OWNER)
    except get_user_model().DoesNotExist:
        logger.error(
            "IF_SCAN_DEFAULT_OWNER account '%s' does not exist — no .inkj files will be ingested this run.",
            settings.IF_SCAN_DEFAULT_OWNER,
        )
        return None


def find_inkj_file_by_path(full_filepathname: str) -> FileIndex | None:
    """Resolve one .inkj file's full path directly to its live FileIndex row.

    Used by interactive_fiction.views._source_gallery_item_sha256 to resolve
    a scanner-ingested story back to its originating gallery item (the
    mirror image of ingest_stories()'s file -> story direction) — a single
    indexed directory lookup plus a filtered in-directory query, rather than
    live_inkj_files()'s full-table scan, since that function needs to check
    only one path, not enumerate every candidate. A thin, .inkj-filtered
    wrapper over interactive_fiction.images.find_file_by_path's shared
    two-step DirectoryIndex-then-files_in_dir resolution.

    Args:
        full_filepathname: The full path to look up (e.g. Story.source_fqfn).

    Returns:
        The matching live FileIndex row (filetype .inkj, not ignored, not
        delete_pending), or None if no such row exists (including when the
        containing directory itself has no DirectoryIndex row).
    """
    return find_file_by_path(full_filepathname, additional_filters={"filetype__fileext__iexact": ".inkj"})


def _resolve_game_folder(owner, game_dir: Path) -> tuple[Any, str, FileIndex] | None:
    """Resolve one game folder's manifest, main-story path, and tracked
    gallery file — the shared validation prefix for both the create and
    refresh paths in _ingest_one_game_folder.

    Args:
        owner: The scanner-ingestion owner account.
        game_dir: The candidate game folder's real filesystem path.

    Returns:
        (manifest module, main story's full path, its FileIndex row), or
        None if any real validation step failed — in which case a
        matching Story row already has `game_ingestion_error` set (see
        _record_game_ingestion_error) and the error is already logged.
    """
    try:
        manifest = _load_game_manifest(game_dir)
        main_story_fqfn = _resolve_main_story_path(game_dir, manifest)
    except _GameManifestError as exc:
        logger.error("Game folder ingestion failed: %s", exc)
        _record_game_ingestion_error(owner, game_dir, str(exc))
        return None

    file_entry = find_inkj_file_by_path(main_story_fqfn)
    if file_entry is None:
        error = f"Game folder '{game_dir.name}': MAIN_STORY_FILE is not a tracked gallery file (run the gallery scanner first)"
        logger.error("Game folder ingestion failed: %s", error)
        _record_game_ingestion_error(owner, game_dir, error)
        return None

    return manifest, main_story_fqfn, file_entry


def _ingest_one_game_folder(owner, game_dir: Path) -> bool:
    """Create or refresh the one Story for one real game folder.

    Shared by ingest_stories() (full batch pass over every game folder)
    and ingest_stories_in_directory() (single-folder, called live from
    the web view path when that exact folder's files changed) — both need
    the same manifest-read/validate/create-or-refresh sequence per
    candidate folder, just scoped to a different set of candidates.

    A folder already backed by a Story row (matched by game_dir's own
    resolved main-story path as `source_fqfn`) is refreshed via
    _refresh_from_disk() instead of re-created — this keeps the same
    Story.pk across a manifest/content update, so every player's
    SaveState/CurrentGame reconnects without FK churn, matching
    verify_stories()'s own existing "restored"/"refreshed" behavior.

    Args:
        owner: The scanner-ingestion owner account (see _get_scan_owner()).
        game_dir: The candidate game folder's real filesystem path.

    Returns:
        True if a Story row was created or successfully refreshed; False
        on any real ingestion failure (manifest error, unreadable/invalid
        `.inkj`) — in every False case, a matching Story row (created if
        none existed) has `game_ingestion_error` set and is left
        unavailable, per the plan's own decided hard-failure + admin-
        visible-flag behavior; nothing is ever silently dropped.
    """
    resolved = _resolve_game_folder(owner, game_dir)
    if resolved is None:
        return False
    manifest, main_story_fqfn, file_entry = resolved

    existing = Story.objects.filter(source_fqfn=main_story_fqfn).first()
    if existing is not None:
        # A refresh failure here (invalid replacement content) is
        # _refresh_from_disk's own existing, correct "keep the working
        # story as-is" behavior — NOT a real ingestion failure to record
        # via game_ingestion_error/is_available=False, which would wrongly
        # take down an otherwise-fine, already-ingested game over a bad
        # in-progress file write. _refresh_from_disk already logs the
        # real reason.
        if _refresh_from_disk(existing, file_entry):
            _apply_game_manifest_fields(existing, manifest, game_dir)
            return True
        return False

    data = _read_and_validate_main_story(owner, game_dir, main_story_fqfn)
    if data is None:
        return False

    _create_or_repurpose_game_story(owner, game_dir, resolved=(manifest, main_story_fqfn, file_entry), data=data)
    return True


def _read_and_validate_main_story(owner, game_dir: Path, main_story_fqfn: str) -> dict[str, Any] | None:
    """Read and validate a game folder's real main-story file's bytes.

    Args:
        owner: The scanner-ingestion owner account (for error recording).
        game_dir: The candidate game folder's real filesystem path.
        main_story_fqfn: The main story file's real, resolved full path.

    Returns:
        The validated compiled-Ink JSON dict, or None on any real failure
        (unreadable file, invalid content) — in which case a matching
        Story row already has `game_ingestion_error` set and the error is
        already logged.
    """
    try:
        with open(main_story_fqfn, "rb") as story_file:
            raw_bytes = story_file.read()
    except OSError as exc:
        error = f"Game folder '{game_dir.name}': could not read MAIN_STORY_FILE: {exc}"
        logger.error("Game folder ingestion failed: %s", error)
        _record_game_ingestion_error(owner, game_dir, error)
        return None

    data, errors = validate_story_upload(raw_bytes)
    if data is None:
        error = f"Game folder '{game_dir.name}': MAIN_STORY_FILE is not valid compiled Ink JSON: {'; '.join(errors)}"
        logger.error("Game folder ingestion failed: %s", error)
        _record_game_ingestion_error(owner, game_dir, error)
        return None

    return data


def _create_or_repurpose_game_story(owner, game_dir: Path, *, resolved: tuple[Any, str, FileIndex], data: dict[str, Any]) -> None:
    """Create this game folder's first-ever Story row, or repurpose its
    existing placeholder row (from a previously-failed ingestion) rather
    than leaving that row behind as an orphaned duplicate.

    Args:
        owner: The scanner-ingestion owner account.
        game_dir: The candidate game folder's real filesystem path.
        resolved: (manifest module, main story's real full path, its
            current FileIndex row) — the same tuple _resolve_game_folder
            returns.
        data: The already-validated compiled-Ink JSON dict.

    Returns:
        None.
    """
    manifest, main_story_fqfn, file_entry = resolved
    title = str(getattr(manifest, "GAME_TITLE", "") or game_dir.name)
    placeholder = Story.objects.filter(source_fqfn=_placeholder_fqfn(game_dir)).first()
    if placeholder is not None:
        placeholder.title = title
        placeholder.compiled_json = data
        placeholder.ink_version = str(data.get("inkVersion", ""))
        placeholder.source_fqfn = main_story_fqfn
        placeholder.source_sha256 = file_entry.file_sha256 or ""
        placeholder.is_available = True
        placeholder.save(update_fields=["title", "compiled_json", "ink_version", "source_fqfn", "source_sha256", "is_available", "updated_at"])
        _apply_game_manifest_fields(placeholder, manifest, game_dir)
        return

    story = create_story_from_compiled_json(owner, title, data, source_fqfn=main_story_fqfn, source_sha256=file_entry.file_sha256 or "")
    _apply_game_manifest_fields(story, manifest, game_dir)


def _apply_game_manifest_fields(story: Story, manifest: Any, game_dir: Path) -> None:
    """Copy a game folder's manifest fields onto its Story row and clear
    any prior ingestion error — this folder just ingested successfully.

    Args:
        story: The Story row to update (mutated and saved in place).
        manifest: The already-loaded, already-validated manifest module.
        game_dir: The game folder's real filesystem path — used to
            resolve any `NEW_GAME_FIELDS` `radio_image` option's own
            `image` filename to a real, already-scanned gallery
            FileIndex row (see `_link_new_game_field_images`).

    Returns:
        None.
    """
    story.title = str(getattr(manifest, "GAME_TITLE", "") or story.title)
    story.game_author = str(getattr(manifest, "GAME_AUTHOR", "") or "")
    story.game_required_plugins = list(getattr(manifest, "REQUIRED_PLUGINS", []) or [])
    story.game_new_game_fields = list(getattr(manifest, "NEW_GAME_FIELDS", []) or [])
    story.game_ingestion_error = ""
    story.save(update_fields=["title", "game_author", "game_required_plugins", "game_new_game_fields", "game_ingestion_error", "updated_at"])
    _link_new_game_field_images(story, game_dir)


def _new_game_field_image_tag(filename: str) -> str:
    """Return the synthetic StoryImage tag name for one character-creation
    image, deterministic from its own filename alone.

    Args:
        filename: A `NEW_GAME_FIELDS` `radio_image` option's own `image`
            value (e.g. `"male.png"`) — a plain filename inside the game
            folder, never a path.

    Returns:
        The tag name `character_creation()`/its template look up this
        image under (e.g. `"newgame:male.png"`) — namespaced so it can
        never collide with a real `# image: <tag_name>` Ink tag the
        story's own content declares.
    """
    return f"newgame:{filename}"


def _link_new_game_field_images(story: Story, game_dir: Path) -> None:
    """Link every `NEW_GAME_FIELDS` `radio_image` option's own image to a
    real gallery file, so `character_creation.jinja` can serve it via the
    existing `story_image()` view — these are the game folder's own real
    UI assets (e.g. a gender-picker icon), not story CONTENT with a
    `# image:` Ink tag, but they're scanned into the gallery exactly like
    any other file under Albums/interactive_fiction/<game>/, so the
    existing StoryImage/FileIndex machinery already knows how to serve
    them once linked — no separate serving path needed.

    Args:
        story: The Story row whose `game_new_game_fields` may reference
            real image filenames.
        game_dir: The game folder's real filesystem path, used to
            resolve each filename to its own real FileIndex row.

    Returns:
        None. A filename that hasn't been scanned yet (game folder just
        unzipped, scanner hasn't run) is silently left unlinked — the
        next `verify_stories()` pass re-runs this and links it then;
        `character_creation.jinja`'s own image tag simply renders broken
        until that happens, same tolerance `_current_image_urls()`
        already has for a work-in-progress story's placeholder tags.
    """
    for field in story.game_new_game_fields:
        if field.get("type") != "radio_image":
            continue
        for option in field.get("options", []):
            filename = option.get("image")
            if not filename:
                continue
            file_entry = find_file_by_path(str(game_dir / filename))
            if file_entry is not None:
                link_story_image(story, _new_game_field_image_tag(filename), file_entry)


def _placeholder_fqfn(game_dir: Path) -> str:
    """Return the stable, non-real `source_fqfn` used for a game folder's
    Story row while its real main-story path can't be resolved (manifest
    missing/invalid, MAIN_STORY_FILE not found).

    Args:
        game_dir: The game folder's real filesystem path.

    Returns:
        A per-folder-stable placeholder path — never a real file — so
        repeated ingestion attempts against the same broken folder update
        the same Story row instead of creating a new one each time, and
        so a later successful ingestion can find and repurpose that same
        row (see `_ingest_one_game_folder`'s own placeholder-repurposing
        step) rather than leaving it behind as an orphaned duplicate.
    """
    return str(game_dir / "__game_folder__")


def _record_game_ingestion_error(owner, game_dir: Path, error: str) -> None:
    """Create (if needed) or update the Story row representing a game
    folder that failed to ingest, so the failure is visible in Django
    admin rather than log-only.

    Args:
        owner: The scanner-ingestion owner account.
        game_dir: The failed game folder's real filesystem path.
        error: The human-readable failure reason (stored verbatim).

    Returns:
        None.
    """
    story = Story.objects.filter(source_fqfn=_placeholder_fqfn(game_dir)).first()
    if story is None:
        story = Story.objects.create(
            owner=owner,
            title=game_dir.name,
            slug=unique_story_slug(game_dir.name),
            compiled_json={},
            source_fqfn=_placeholder_fqfn(game_dir),
            is_available=False,
        )
    _set_game_ingestion_error(story, error)


def _set_game_ingestion_error(story: Story, error: str) -> None:
    """Record a real ingestion failure on an existing Story row.

    Args:
        story: The Story row to update (mutated and saved in place).
        error: The human-readable failure reason (stored verbatim).

    Returns:
        None.
    """
    story.game_ingestion_error = error
    story.is_available = False
    story.save(update_fields=["game_ingestion_error", "is_available", "updated_at"])


def ingest_stories() -> int:
    """Create or refresh a Story for every real game folder under
    Albums/interactive_fiction/.

    Args:
        None.

    Returns:
        The number of game folders successfully ingested (created or
        refreshed) this pass. A folder that failed (see
        _ingest_one_game_folder) is not counted here, but is still
        recorded — via a Story row with game_ingestion_error set — so it
        remains visible in admin.
    """
    owner = _get_scan_owner()
    if owner is None:
        return 0

    ingested = 0
    for game_dir in game_folders():
        if _ingest_one_game_folder(owner, game_dir):
            ingested += 1

    return ingested


def relink_story_images() -> dict[str, int]:
    """Reconcile every ingested game's content-image links against its tags.

    The graphics half of ingestion, run alongside the story-content half
    rather than as a separate manual step. For each game folder with a
    live Story row, every `# image:`/`# video:` tag in its .ink corpus is
    re-expanded and re-resolved against the gallery, and the story's
    content-image rows are made to match exactly — links added, links
    repointed, and rows whose tag or file is gone deleted (see
    `image_linking.reconcile_story_images`).

    Deleting is the reason this runs unconditionally rather than only when
    the compiled story changed: an image can leave the gallery without the
    `.inkj` being touched at all, and an append-only link would keep
    serving a row pointing at content that is no longer there.

    Args:
        None.

    Returns:
        {"linked", "unlinked", "broken", "tags"} totalled across games.
    """
    totals = {"linked": 0, "unlinked": 0, "broken": 0, "tags": 0}
    for game_dir in game_folders():
        try:
            manifest = _load_game_manifest(game_dir)
            main_story_fqfn = _resolve_main_story_path(game_dir, manifest)
        except _GameManifestError as exc:
            logger.warning("Skipping image reconcile for '%s': %s", game_dir, exc)
            continue

        story = Story.objects.filter(source_fqfn=main_story_fqfn).defer("compiled_json").first()
        if story is None:
            continue

        try:
            counts = reconcile_story_images(story, game_dir, getattr(manifest, "SOURCE_GAME_VERSION", None))
        except OSError as exc:
            logger.warning("Image reconcile failed for '%s': %s", game_dir, exc)
            continue

        for key, value in counts.items():
            totals[key] += value
    return totals


def ingest_stories_in_directory(directory: DirectoryIndex) -> int:
    """Ingest one game folder, if `directory` is itself a real, direct
    game folder under Albums/interactive_fiction/.

    The live-web counterpart to ingest_stories(): called from
    update_database_from_disk() right after sync_files() so a game
    folder's content becomes playable the moment its directory is next
    viewed, matching how any other file type is picked up live — instead
    of requiring a separate `manage.py scan --add_files` batch run.
    Directories that are NOT themselves a direct child of
    Albums/interactive_fiction/ (an ordinary gallery directory, or a
    sub-directory nested inside a game folder) are correctly a no-op here
    — a live single-directory sync has no way to know a nested change
    should re-trigger its ENCLOSING game folder's own manifest read, and
    guessing at that relationship risks re-ingesting the wrong folder;
    `manage.py scan --verify_files`'s own batch verify_stories() pass
    remains the correct, complete way to pick up such a change.

    Args:
        directory: The DirectoryIndex just synced by update_database_from_disk().

    Returns:
        1 if this directory is a real game folder and was successfully
        ingested; 0 otherwise (not a game folder, ingestion failed, or no
        scan owner configured).
    """
    games_root = normalize_fqpn(str(Path(DirectoryIndex.get_albums_root()) / "interactive_fiction"))
    directory_path = normalize_fqpn(directory.fqpndirectory)
    parent_path = normalize_fqpn(os.path.dirname(directory_path.rstrip(os.sep)))
    if parent_path != games_root:
        return 0

    owner = _get_scan_owner()
    if owner is None:
        return 0

    return 1 if _ingest_one_game_folder(owner, Path(directory_path)) else 0


def _tombstone(story: Story) -> None:
    """Mark a story unavailable and clear its compiled_json (Step 9's tombstone).

    Args:
        story: The scanner-ingested story whose source file is gone.

    Returns:
        None.
    """
    story.is_available = False
    story.compiled_json = {}
    story.save(update_fields=["is_available", "compiled_json", "updated_at"])


def _refresh_from_disk(story: Story, file_entry: FileIndex) -> bool:
    """Re-validate and reload a story's compiled_json from its current source file.

    Args:
        story: The scanner-ingested story to refresh (mutated in place on
            success).
        file_entry: The current FileIndex row for story.source_fqfn.

    Returns:
        True if the refresh applied (and was saved); False if the file
        couldn't be read or failed validation, in which case story is left
        untouched — a half-written file mid-copy must not take down a
        working story, and a real validation failure is logged rather than
        silently discarding the existing content.
    """
    try:
        with open(story.source_fqfn, "rb") as story_file:
            raw_bytes = story_file.read()
    except OSError as exc:
        logger.warning("Could not re-read story file '%s': %s", story.source_fqfn, exc)
        return False

    data, errors = validate_story_upload(raw_bytes)
    if data is None:
        logger.warning("Re-validation failed for '%s', keeping existing content: %s", story.source_fqfn, "; ".join(errors))
        return False

    story.compiled_json = data
    story.ink_version = str(data.get("inkVersion", ""))
    story.source_sha256 = file_entry.file_sha256 or ""
    story.is_available = True
    story.save(update_fields=["compiled_json", "ink_version", "source_sha256", "is_available", "updated_at"])
    return True


def verify_stories() -> tuple[int, int, int]:
    """Tombstone stories whose source file is gone; refresh ones that changed or reappeared.

    Args:
        None.

    Returns:
        (tombstoned_count, restored_count, refreshed_count) — restored_count
        is stories whose source file reappeared at the same path (matched
        by source_fqfn) and had compiled_json refilled on the same row, so
        every player's SaveState/CurrentGame reconnects without FK churn
        (both FKs point at the same, unchanged, Story.pk).
    """
    tombstoned = restored = refreshed = 0

    for story in Story.objects.exclude(source_fqfn="").defer("compiled_json"):
        file_entry = find_inkj_file_by_path(story.source_fqfn)
        if file_entry is None:
            if story.is_available:
                _tombstone(story)
                tombstoned += 1
            continue

        was_tombstoned = not story.is_available
        sha_changed = bool(file_entry.file_sha256) and file_entry.file_sha256 != story.source_sha256
        if not (was_tombstoned or sha_changed):
            continue

        if _refresh_from_disk(story, file_entry):
            if was_tombstoned:
                restored += 1
            else:
                refreshed += 1

    # Re-run manifest-driven ingestion for every real game folder — this
    # retries a previously-broken folder (whose placeholder Story row has
    # a non-real source_fqfn the loop above can never match) and refreshes
    # game_required_plugins/game_new_game_fields from the manifest if
    # either changed, even when the main .inkj's own content didn't.
    owner = _get_scan_owner()
    if owner is not None:
        for game_dir in game_folders():
            _ingest_one_game_folder(owner, game_dir)

    return tombstoned, restored, refreshed
