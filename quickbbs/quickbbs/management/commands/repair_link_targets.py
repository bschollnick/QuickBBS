"""
Django management command to re-resolve link file targets.

First force-syncs every directory containing link files from disk so the
report reflects the filesystem at the time it runs — never stale FileIndex
rows (e.g. a link renamed on disk but not yet rescanned). Then re-runs
alias/link resolution for every link file in the index and repoints any
whose stored virtual_directory no longer matches the current resolution
(e.g. rows created before a masters volume's translation existed). Also
reports link files whose targets cannot be resolved and DirectoryIndex rows
outside the albums tree.

The directory sync runs even with --dry-run: it is the same sync browsing a
directory triggers, and without it the report would describe the database's
last scan rather than the disk. --dry-run only skips repointing.

Usage:
    python manage.py repair_link_targets --dry-run
    python manage.py repair_link_targets
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.db.models import Count, Q

from quickbbs.directoryindex import DirectoryIndex, update_database_from_disk
from quickbbs.fileindex import FileIndex

BULK_UPDATE_BATCH_SIZE = 250


class Command(BaseCommand):
    """Re-resolve every link file's virtual_directory against current rules."""

    help = "Re-resolve alias/link virtual_directory targets and report broken links"

    def add_arguments(self, parser) -> None:
        """Register the --dry-run option.

        Args:
            parser: The argparse parser supplied by Django.
        """
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without saving anything.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Re-resolve all link targets, report results, and list out-of-tree directories.

        Clears the alias resolution cache first so stale resolutions from
        before a mapping change are recomputed, then force-syncs every
        directory containing link files so the report reflects the disk at
        run time. With --dry-run, repoints are reported but not saved (the
        directory sync still runs — see module docstring).

        Args:
            *args: Unused positional arguments from Django.
            **options: Parsed command-line options.
        """
        dry_run: bool = options["dry_run"]
        prefix = "[dry-run] " if dry_run else ""

        # Stale resolutions may be cached from before a mapping/algorithm change
        FileIndex._alias_cache.clear()  # pylint: disable=protected-access

        synced = self._sync_link_directories()
        self.stdout.write(f"Synced {synced} link-holding directories from disk")

        repointed, unchanged, unresolvable, missing_files = self._repair_links(dry_run)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{prefix}Repointed: {repointed}   Unchanged: {unchanged}"))

        if missing_files:
            self.stdout.write(self.style.WARNING(f"\nLink files in DB but missing on disk: {len(missing_files)}"))
            for path in missing_files:
                self.stdout.write(f"    {path}")

        if unresolvable:
            self.stdout.write(self.style.WARNING(f"\nUnresolvable link targets (see log for reasons): {len(unresolvable)}"))
            for entry in unresolvable:
                self.stdout.write(f"    {entry}")

        self._report_out_of_tree_directories()

    def _sync_link_directories(self) -> int:
        """
        Force-sync every directory containing link files from disk.

        Invalidates the scan cache for each distinct home directory of a
        live link row (via the batch invalidation path, which also clears
        the layout and DirectoryIndex LRU caches), then rescans each with
        update_database_from_disk(). This removes FileIndex rows for links
        deleted or renamed on disk and indexes new ones, so the link checks
        that follow operate on the filesystem's current state rather than
        the last scan.

        Returns:
            Number of directories synced.
        """
        dir_ids = list(
            FileIndex.objects.filter(filetype__is_link=True, delete_pending=False)
            .exclude(home_directory=None)
            .values_list("home_directory_id", flat=True)
            .distinct()
        )
        if not dir_ids:
            return 0

        directories = list(DirectoryIndex.objects.filter(pk__in=dir_ids, delete_pending=False))
        # A valid cache flag makes update_database_from_disk() skip the
        # rescan, so invalidate first — the report must reflect the disk
        # now, not whenever each directory was last scanned.
        DirectoryIndex.invalidate_caches(directories)

        synced = 0
        # Re-fetch: invalidate_caches() flipped cache_invalidated via a bulk
        # UPDATE, and update_database_from_disk() consults the in-memory
        # flag before doing any work. Materialized (not .iterator()) because
        # update_database_from_disk() calls close_old_connections(), which
        # would kill a streaming cursor mid-loop.
        for directory in list(DirectoryIndex.objects.filter(pk__in=dir_ids, delete_pending=False)):
            update_database_from_disk(directory)
            synced += 1
        return synced

    def _repair_links(self, dry_run: bool) -> tuple[int, int, list[str], list[str]]:
        """
        Re-resolve every link file and repoint stale virtual_directory values.

        Args:
            dry_run: When True, report repoints without saving them.

        Returns:
            Tuple of (repointed count, unchanged count, unresolvable link
            descriptions, missing-on-disk link paths). Both lists are sorted
            alphabetically; repoint messages print in path order via the
            queryset ordering.
        """
        prefix = "[dry-run] " if dry_run else ""
        links = (
            FileIndex.objects.filter(filetype__is_link=True, delete_pending=False)
            .select_related("filetype", "virtual_directory", "home_directory")
            .order_by("home_directory__fqpndirectory", "name")
        )

        repointed = 0
        unchanged = 0
        unresolvable: list[str] = []
        missing_files: list[str] = []
        to_update: list[FileIndex] = []

        for link in links.iterator():
            if link.home_directory is None:
                missing_files.append(f"{link.name}  (no home_directory)")
                continue
            link_path = os.path.join(link.home_directory.fqpndirectory, link.name)
            if not os.path.exists(link_path):
                missing_files.append(link_path)
                continue

            virtual_dir = FileIndex.process_link_file(Path(link_path), link.filetype, link.name)
            old = link.virtual_directory.fqpndirectory if link.virtual_directory else None

            if virtual_dir is None:
                # The reason (dangling bookmark, missing gallery copy, ambiguous
                # target) is logged by process_link_file/find_by_physical_path.
                unresolvable.append(f"{link_path}  (currently: {old})")
                continue

            if virtual_dir.pk == link.virtual_directory_id:
                unchanged += 1
                continue

            repointed += 1
            self.stdout.write(f"{prefix}repoint {link_path}\n    {old}\n    → {virtual_dir.fqpndirectory}")
            if not dry_run:
                link.virtual_directory = virtual_dir
                to_update.append(link)

        if to_update:
            FileIndex.objects.bulk_update(to_update, ["virtual_directory"], batch_size=BULK_UPDATE_BATCH_SIZE)

        return repointed, unchanged, sorted(unresolvable), sorted(missing_files)

    def _report_out_of_tree_directories(self) -> None:
        """Report DirectoryIndex rows outside the albums tree (never deletes)."""
        albums_root = DirectoryIndex.get_albums_root()
        out_of_tree = (
            DirectoryIndex.objects.exclude(fqpndirectory__startswith=albums_root)
            .filter(delete_pending=False)
            .annotate(
                link_refs=Count(
                    "Virtual_FileIndex",
                    filter=Q(Virtual_FileIndex__delete_pending=False),
                    distinct=True,
                ),
                file_refs=Count(
                    "FileIndex_entries",
                    filter=Q(FileIndex_entries__delete_pending=False),
                    distinct=True,
                ),
            )
            .order_by("fqpndirectory")
        )
        rows = list(out_of_tree.values_list("id", "fqpndirectory", "link_refs", "file_refs"))
        if not rows:
            return
        self.stdout.write(self.style.WARNING(f"\nDirectoryIndex rows outside the albums tree: {len(rows)}"))
        self.stdout.write("Stale rows from pre-fix alias resolution — review and remove manually (0 refs = safe):")
        for pk, fqpn, link_refs, file_refs in rows:
            self.stdout.write(f"    id={pk}  links→{link_refs}  files-in-dir→{file_refs}  {fqpn}")
