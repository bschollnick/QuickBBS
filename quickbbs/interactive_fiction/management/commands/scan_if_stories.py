"""The single ingestion process for Interactive Fiction — a dedicated
command for the Albums/interactive_fiction/ subtree, parallel to (never
part of) the general-purpose `scan` command that walks the whole gallery.

Everything an IF game needs to go from files on disk to a playable story
happens here, in one pass, in this order:

1. **Clear stored SHA256s** for the subtree (`_clear_shas_under`). The
   gallery scanner only hashes a file whose stored hash is NULL, so a
   `.inkj` recompiled in place at the same path would otherwise keep its
   stale hash forever — and `verify_stories()` uses exactly that hash to
   decide whether to reload the story. Clearing first makes every IF file
   rehash on every scan; the rest of the gallery is untouched.
2. **Walk the subtree** (`add_directories`/`add_files`) — the same
   machinery `scan` uses via `--start`, permanently scoped here, now
   recomputing the hashes cleared in step 1.
3. **Verify and ingest stories** — tombstone stories whose source file is
   gone, refresh those whose content changed, create/refresh one Story per
   game folder from its manifest.
4. **Sync EngineAPI rows** for the generic `engine_plugins/` and each
   game's own API modules (new ones start disabled, per that function's
   safe-by-default posture).
A bundled game's media needs no pass of its own: it resolves its own
tags from its own bundle at request time.

This used to be a standalone script, run by hand.

Usage:
    python manage.py scan_if_stories
    python manage.py scan_if_stories --max_count N
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from interactive_fiction.ingestion import (
    game_folders,
    ingest_stories,
    verify_stories,
)
from interactive_fiction.models import Story, sync_engine_apis
from quickbbs.common import normalize_fqpn
from quickbbs.directoryindex import DirectoryIndex
from quickbbs.management.commands.add_directories import add_directories
from quickbbs.management.commands.add_files import add_files
from quickbbs.models import FileIndex


def _clear_shas_under(start_path: str) -> int:
    """Null the stored SHA256 of every scanned file under `start_path`.

    The gallery scanner only computes a file's SHA256 when the stored one
    is NULL (`FileIndex.find_files_without_sha` -> the add_files rescan
    path); it never rehashes a file whose hash is already set. That is fine
    for gallery content, which is written once, but wrong for a game folder,
    where a `.inkj` is recompiled in place over and over at the same path.
    The stale hash then propagates to `Story.source_sha256` and makes the
    story row claim a hash that is not its content — and, worse,
    `verify_stories()` decides whether to reload `compiled_json` by
    comparing exactly those two hashes, so an unchanged-looking hash means
    a recompiled story is never re-read.

    Nulling first makes the recompute unconditional for this subtree only:
    every IF file is rehashed on every scan, and the rest of the gallery
    keeps its existing skip-if-present behaviour untouched.

    `unique_sha256` is cleared alongside it because it is derived from the
    same digest (content + path); leaving a stale unique hash behind under
    its UNIQUE constraint would block the row being rewritten with the
    correct one. Multiple NULLs do not collide under UNIQUE.

    Args:
        start_path: The already-validated Albums subtree to clear
            (Albums/interactive_fiction).

    Returns:
        The number of FileIndex rows cleared.
    """
    normalized = normalize_fqpn(start_path)
    with transaction.atomic():
        return FileIndex.objects.filter(home_directory__fqpndirectory__startswith=normalized, delete_pending=False).update(
            file_sha256=None, unique_sha256=None
        )


class Command(BaseCommand):
    """Scan Albums/interactive_fiction/ only, ingest Story rows, sync EngineAPI."""

    help = "Scan Albums/interactive_fiction/ (recursively, never the rest of the gallery), ingest/refresh Story rows, and sync EngineAPI."

    def add_arguments(self, parser):
        """Register this command's one shared option.

        Args:
            parser: The argparse parser supplied by Django.
        """
        parser.add_argument(
            "--max_count",
            type=int,
            default=0,
            help="Maximum number of directories/files to process per step (0 = unlimited).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Walk Albums/interactive_fiction/, ingest/verify Story rows, sync EngineAPI.

        Args:
            *args: Unused positional arguments from Django.
            **options: Parsed command-line options (max_count).

        Raises:
            CommandError: If Albums/interactive_fiction/ doesn't exist
                yet under the configured albums root.
        """
        max_count = int(options.get("max_count", 0) or 0)
        start_path = f"{DirectoryIndex.get_albums_root()}/interactive_fiction"
        if not DirectoryIndex.is_in_albums_tree(start_path):
            raise CommandError(f"'{start_path}' is not within the configured albums root ({DirectoryIndex.get_albums_root()}).")

        # A bundle has no per-file rows to hash, walk or relink: it is one
        # file, read in place. These three stages exist for folder games
        # and are skipped outright when there are none, rather than
        # rehashing and re-walking a tree that holds only bundles.
        folder_games = bool(game_folders())
        if folder_games:
            cleared = _clear_shas_under(start_path)
            if cleared:
                self.stdout.write(f"Cleared SHA256 on {cleared} Interactive Fiction file(s) for recomputation.")

            add_directories(max_count=max_count, start_path=start_path)
            add_files(max_count=max_count, start_path=start_path)

        tombstoned, restored, refreshed = verify_stories()
        if tombstoned or restored or refreshed:
            self.stdout.write(f"Interactive Fiction: {tombstoned} tombstoned, {restored} restored, {refreshed} refreshed")

        ingested = ingest_stories()
        if ingested:
            self.stdout.write(self.style.SUCCESS(f"Interactive Fiction: {ingested} game(s) ingested/refreshed"))

        # Every bundle is re-examined on each scan (ingest_stories), so a
        # game disabled for failing its integrity check is reported here
        # rather than only in the log.
        refused = Story.objects.exclude(game_ingestion_error="").filter(is_available=False).count()
        if refused:
            self.stdout.write(self.style.ERROR(f"Interactive Fiction: {refused} game(s) unavailable — see game_ingestion_error in admin"))

        created_count, updated_count = sync_engine_apis()
        self.stdout.write(
            self.style.SUCCESS(f"Engine APIs synced: {created_count} newly discovered (disabled by default), {updated_count} already known.")
        )
