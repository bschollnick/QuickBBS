"""
Report on and delete DirectoryIndex rows lying outside the albums root.

Out-of-tree rows (masters volumes, traversal escapes) were created by the
pre-2026-07 alias system; add_directory() now rejects such paths, so these
rows are legacy data that can only mislead (see
claude_docs/plans/albums_root_enforcement.md).

Usage:
    python manage.py purge_out_of_tree            # read-only report (default)
    python manage.py purge_out_of_tree --delete   # delete after reporting
"""

from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from quickbbs.cache_registry import clear_layout_cache_for_directories
from quickbbs.directoryindex import directoryindex_cache
from quickbbs.models import DirectoryIndex, FileIndex


def _out_of_tree_queryset():
    """Return the queryset of DirectoryIndex rows outside the albums root.

    Returns:
        QuerySet of out-of-tree DirectoryIndex rows.
    """
    albums_root = DirectoryIndex.get_albums_root()
    return DirectoryIndex.objects.exclude(fqpndirectory__startswith=albums_root)


class Command(BaseCommand):
    """Report on (default) or delete DirectoryIndex rows outside the albums root."""

    help = "Report on / delete DirectoryIndex rows whose path lies outside the albums root"

    def add_arguments(self, parser):
        """Register the --delete flag (without it, the command only reports).

        Args:
            parser: The argparse parser supplied by Django.
        """
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete the out-of-tree rows (and their FileIndex entries) after reporting",
        )

    def _print_report(self, dir_rows: list[tuple[int, str]], files_homed_count: int, links_pointing_count: int) -> None:
        """Print the out-of-tree row counts, grouped by volume prefix.

        Args:
            dir_rows: (pk, fqpndirectory) tuples of the out-of-tree rows.
            files_homed_count: FileIndex rows homed in those directories.
            links_pointing_count: Link files elsewhere pointing at them.
        """
        prefix_counts: Counter[str] = Counter()
        for _, fqpn in dir_rows:
            # Group by the first two path components (e.g. /volumes/f-16tb/)
            parts = fqpn.split("/")
            prefix_counts["/".join(parts[:3]) + "/"] += 1

        self.stdout.write("=" * 70)
        self.stdout.write(f"Albums root: {DirectoryIndex.get_albums_root()}")
        self.stdout.write(f"Out-of-tree DirectoryIndex rows: {len(dir_rows)}")
        self.stdout.write(f"FileIndex rows homed in them:    {files_homed_count}")
        self.stdout.write(f"Link files pointing at them:     {links_pointing_count}  (virtual_directory SET_NULL, re-resolved by repair)")
        self.stdout.write("-" * 70)
        for prefix, count in prefix_counts.most_common():
            self.stdout.write(f"  {count:6d}  {prefix}")
        self.stdout.write("=" * 70)

    def handle(self, *args, **options):
        """Report exact counts of out-of-tree rows; delete them when --delete is given.

        Args:
            *args: Unused positional arguments from Django.
            **options: Parsed command-line options ('delete').

        Example:
            $ manage.py purge_out_of_tree
            $ manage.py purge_out_of_tree --delete
        """
        dir_rows = list(_out_of_tree_queryset().values_list("pk", "fqpndirectory"))
        dir_pks = [pk for pk, _ in dir_rows]

        files_homed = FileIndex.objects.filter(home_directory_id__in=dir_pks)

        # Link files elsewhere whose virtual_directory points at an
        # out-of-tree row: the FK is SET_NULL on delete, after which the
        # existing virtual_directory_needs_repair() / repair_link_targets
        # machinery re-resolves them through find_by_physical_path.
        links_pointing_count = FileIndex.objects.filter(virtual_directory_id__in=dir_pks).exclude(home_directory_id__in=dir_pks).count()

        self._print_report(dir_rows, files_homed.count(), links_pointing_count)

        if not options["delete"]:
            self.stdout.write("Read-only report complete. Re-run with --delete to remove these rows.")
            return

        if not dir_pks:
            self.stdout.write("Nothing to delete.")
            return

        with transaction.atomic():
            # FileIndex.home_directory is SET_NULL — delete the files first
            # so they are not left orphaned.
            deleted_files, _ = files_homed.delete()
            deleted_dirs, _ = DirectoryIndex.objects.filter(pk__in=dir_pks).delete()

        # Evict any cached copies of the deleted rows.
        clear_layout_cache_for_directories(set(dir_pks))
        directoryindex_cache.clear()

        self.stdout.write(f"Deleted {deleted_dirs} DirectoryIndex rows and {deleted_files} related FileIndex rows.")
        self.stdout.write("Run 'manage.py repair_link_targets' to re-resolve any link files that pointed at them.")
