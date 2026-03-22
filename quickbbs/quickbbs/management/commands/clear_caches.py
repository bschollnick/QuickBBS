"""
Django management command to clear all in-process LRU caches.

Usage:
    python manage.py clear_caches
    python manage.py clear_caches --cache webpaths breadcrumbs
    python manage.py clear_caches --list
"""

from __future__ import annotations

import importlib

from django.core.management.base import BaseCommand

from cachetools import LRUCache


def _load_all_caches() -> list[tuple[str, LRUCache]]:
    """
    Load all caches registered in tasks._MONITORED_CACHE_LOCATIONS.

    Returns:
        List of (label, cache) tuples for every cache that could be imported.
    """
    from quickbbs.tasks import _MONITORED_CACHE_LOCATIONS  # pylint: disable=import-outside-toplevel

    results = []
    for module_path, attr_name, class_name in _MONITORED_CACHE_LOCATIONS:
        label = f"{module_path}.{attr_name}"
        try:
            module = importlib.import_module(module_path)
            if class_name is not None:
                owner = getattr(module, class_name)
                cache = getattr(owner, attr_name)
            else:
                cache = getattr(module, attr_name)
            if isinstance(cache, LRUCache):
                results.append((label, cache))
        except (ImportError, AttributeError) as exc:
            results.append((label, exc))
    return results


class Command(BaseCommand):
    """Clear all in-process LRU caches or a named subset."""

    help = "Clear in-process LRU caches (webpaths, breadcrumbs, layout_manager, etc.)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cache",
            nargs="+",
            metavar="NAME",
            help=(
                "Clear only caches whose label contains NAME (e.g. webpaths breadcrumbs). "
                "Omit to clear all caches."
            ),
        )
        parser.add_argument(
            "--list",
            action="store_true",
            help="List all known caches and their current sizes, then exit.",
        )

    def handle(self, *args, **options):
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
