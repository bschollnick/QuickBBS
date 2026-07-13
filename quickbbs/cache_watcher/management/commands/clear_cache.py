"""Management command that marks every directory's scan cache invalidated."""

from django.core.management.base import BaseCommand

from quickbbs.models import DirectoryIndex


class Command(BaseCommand):
    """Mark every DirectoryIndex record as cache-invalidated, forcing a rescan of all directories."""

    help = "Clear the Filesystem Cache (mark all directories invalidated)"

    def add_arguments(self, parser):
        """Register the --clear_cache flag (informational; the cache is always cleared).

        Args:
            parser: The argparse parser supplied by Django.
        """
        parser.add_argument(
            "--clear_cache",
            action="store_true",
            help="Clear the Filesystem Cache",
        )

    def handle(self, *args, **options):
        """Invalidate all cache records so every directory is rescanned on next access.

        Args:
            *args: Unused positional arguments from Django.
            **options: Parsed command-line options (unused).

        Example:
            $ manage.py clear_cache
        """
        DirectoryIndex.invalidate_all_caches()
