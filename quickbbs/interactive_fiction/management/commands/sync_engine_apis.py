"""Scan for real engine API files and upsert an EngineAPI row for each
(claude_docs/plans/external_expansion_IF_engine.md's plugin-discovery
redesign, 2026-08-22).

Run this after adding/removing an API file under
interactive_fiction/engine_systems/ (or, once a configurable external scan
directory exists, after installing a third-party API package there) — new
APIs are created disabled by default (safe-by-default, matching
Story.is_engine_trusted's own posture); an admin must explicitly enable
one via the EngineAPI admin before any story can actually use it.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from interactive_fiction.models import sync_engine_apis


class Command(BaseCommand):
    """Scan interactive_fiction/engine_systems/ for real API files and
    upsert an EngineAPI row per discovery."""

    help = "Scan for engine API files and sync the EngineAPI table (new APIs start disabled)"

    def handle(self, *args: object, **options: object) -> None:
        """Run the scan and report what was found.

        Args:
            *args: Unused positional arguments from Django.
            **options: Unused parsed command-line options.
        """
        created_count, updated_count = sync_engine_apis()
        self.stdout.write(
            self.style.SUCCESS(f"Engine APIs synced: {created_count} newly discovered (disabled by default), {updated_count} already known.")
        )
