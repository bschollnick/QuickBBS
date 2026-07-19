"""
Django management command to clear all in-process LRU caches.

Usage:
    python manage.py clear_caches
    python manage.py clear_caches --cache webpaths breadcrumbs
    python manage.py clear_caches --list
"""

from __future__ import annotations

from cachetools import LRUCache
from django.core.management.base import BaseCommand

from quickbbs.cache_registry import resolve_monitored_caches


def _load_all_caches() -> list[tuple[str, LRUCache | Exception]]:
    """
    Load all caches registered in the cache registry.

    Returns:
        List of (label, value) tuples for every registered location. `value`
        is the LRUCache instance when it could be imported, or the raised
        ImportError/AttributeError when it could not (callers check
        isinstance(value, Exception) to distinguish the two).
    """
    return [(label, cache) for label, cache in resolve_monitored_caches() if isinstance(cache, (LRUCache, Exception))]


class Command(BaseCommand):
    """Clear all in-process LRU caches or a named subset."""

    help = "Clear in-process LRU caches (webpaths, breadcrumbs, layout_manager, etc.)"

    def add_arguments(self, parser):
        """Register --cache (name filter) and --list options.

        Args:
            parser: The argparse parser supplied by Django.
        """
        parser.add_argument(
            "--cache",
            nargs="+",
            metavar="NAME",
            help=("Clear only caches whose label contains NAME (e.g. webpaths breadcrumbs). " "Omit to clear all caches."),
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all known caches and their current sizes, then exit.",
        )

    def handle(self, *args, **options):
        """List caches (--list) or clear all/matching in-process LRU caches.

        Note: this clears the caches of THIS process only — a running web
        server or taskrunner keeps its own in-process caches.

        Args:
            *args: Unused positional arguments from Django.
            **options: Parsed command-line options.
        """
        caches = _load_all_caches()

        if options["list"]:
            self.stdout.write("Known caches:")
            for label, cache in caches:
                if isinstance(cache, Exception):
                    self.stdout.write(f"  {label}  [ERROR: {cache}]")
                else:
                    self.stdout.write(f"  {label}  ({cache.currsize}/{cache.maxsize} entries)")
            return

        filter_names = options.get("cache") or []

        cleared = 0
        for label, cache in caches:
            if isinstance(cache, Exception):
                self.stderr.write(f"  SKIP  {label}  (could not load: {cache})")
                continue

            if filter_names and not any(name in label for name in filter_names):
                continue

            size_before = cache.currsize
            cache.clear()
            self.stdout.write(f"  CLEAR {label}  ({size_before} entries removed)")
            cleared += 1

        if filter_names and cleared == 0:
            self.stderr.write(f"No caches matched: {filter_names}")
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Cleared {cleared} cache(s)."))
