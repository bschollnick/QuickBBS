# from cache.models import Cache_Storage
from django.core.management.base import BaseCommand

from cache_watcher.models import fs_Cache_Tracking


class Command(BaseCommand):
    """Mark every fs_Cache_Tracking record as invalidated, forcing a rescan of all directories."""

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
        fs_Cache_Tracking.clear_all_records()
