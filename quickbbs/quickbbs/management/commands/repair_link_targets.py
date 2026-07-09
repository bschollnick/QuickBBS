"""
Django management command to re-resolve link file targets.

Re-runs alias/link resolution for every link file in the index and repoints
any whose stored virtual_directory no longer matches the current resolution
(e.g. rows created before a masters volume's translation existed). Also
reports link files whose targets cannot be resolved and DirectoryIndex rows
outside the albums tree.

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

from quickbbs.directoryindex import DirectoryIndex
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
        before a mapping change are recomputed. With --dry-run, repoints are
        reported but not saved.

        Args:
            *args: Unused positional arguments from Django.
            **options: Parsed command-line options.
        """
        dry_run: bool = options["dry_run"]
        prefix = "[dry-run] " if dry_run else ""

        # Stale resolutions may be cached from before a mapping/algorithm change
        FileIndex._alias_cache.clear()  # pylint: disable=protected-access

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

    def _repair_links(self, dry_run: bool) -> tuple[int, int, list[str], list[str]]:
        """
        Re-resolve every link file and repoint stale virtual_directory values.

        Args:
            dry_run: When True, report repoints without saving them.

        Returns:
            Tuple of (repointed count, unchanged count, unresolvable link
            descriptions, missing-on-disk link paths).
        """
        prefix = "[dry-run] " if dry_run else ""
        links = FileIndex.objects.filter(filetype__is_link=True, delete_pending=False).select_related(
            "filetype", "virtual_directory", "home_directory"
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

        return repointed, unchanged, unresolvable, missing_files

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
