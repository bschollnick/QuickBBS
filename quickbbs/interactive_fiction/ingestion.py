"""Scanner ingestion for `.inkj` files in the Albums tree (Step 9).

Two entry points the scan command calls as an additive post-pass after its
own normal work — the only touch to existing scan code is two call sites in
quickbbs/management/commands/scan.py, not a change to update_database_from_disk
itself:

- ingest_stories(): after --add_files, create a Story for every .inkj
  FileIndex row with no matching Story.source_fqfn yet.
- verify_stories(): after --verify_files, tombstone Story rows whose source
  file is gone, and re-validate/refresh rows whose source file changed
  (sha256 drift) or reappeared after being tombstoned.

Every candidate still goes through Step 4's full validation
(validate_story_upload, imported from interactive_fiction.story_views) —
a mislabeled .inkj that isn't compiled Ink is rejected and logged, never
stored as a story.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model

from interactive_fiction.models import Story
from interactive_fiction.story_views import (
    create_story_from_compiled_json,
    validate_story_upload,
)
from quickbbs.models import FileIndex

logger = logging.getLogger(__name__)


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


def live_inkj_files() -> dict[str, FileIndex]:
    """Return every current .inkj FileIndex row, keyed by full file path.

    Public: also used by interactive_fiction.views._source_gallery_item_sha256
    to resolve a scanner-ingested story back to its originating gallery item
    (the mirror image of ingest_stories()'s file -> story direction).

    Args:
        None.

    Returns:
        Mapping of FileIndex.full_filepathname to its FileIndex row.
        Orphaned rows (home_directory=None) are skipped, matching
        full_filepathname's own precondition — an orphan can't be a live
        source for any story.
    """
    candidates = FileIndex.objects.filter(filetype__fileext__iexact=".inkj", ignore=False, delete_pending=False).select_related("home_directory")
    return {entry.full_filepathname: entry for entry in candidates if entry.home_directory is not None}


def ingest_stories() -> int:
    """Create a Story for every unlinked .inkj FileIndex row.

    Matches the plan's file-recognition rule: an .inkj file is only
    reachable here at all once it has a registered filetypes row (added via
    filetypes/management/commands/refresh_filetypes.py) — an unregistered
    extension never becomes a FileIndex row in the first place, so this
    function does not need its own extension whitelist check beyond
    live_inkj_files()'s own filter.

    Args:
        None.

    Returns:
        The number of Story rows created.
    """
    owner = _get_scan_owner()
    if owner is None:
        return 0

    existing_fqfns = set(Story.objects.values_list("source_fqfn", flat=True))

    created = 0
    for fqfn, file_entry in live_inkj_files().items():
        if fqfn in existing_fqfns:
            continue

        try:
            with open(fqfn, "rb") as story_file:
                raw_bytes = story_file.read()
        except OSError as exc:
            logger.warning("Could not read candidate story file '%s': %s", fqfn, exc)
            continue

        data, errors = validate_story_upload(raw_bytes)
        if data is None:
            logger.warning("Skipping invalid story file '%s': %s", fqfn, "; ".join(errors))
            continue

        title = file_entry.name.rsplit(".", 1)[0]
        create_story_from_compiled_json(owner, title, data, source_fqfn=fqfn, source_sha256=file_entry.file_sha256 or "")
        created += 1

    return created


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
    live_files = live_inkj_files()
    tombstoned = restored = refreshed = 0

    for story in Story.objects.exclude(source_fqfn=""):
        file_entry = live_files.get(story.source_fqfn)
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

    return tombstoned, restored, refreshed
