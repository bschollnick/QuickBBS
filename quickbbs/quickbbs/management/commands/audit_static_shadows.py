"""
Audit for custom assets duplicated between resources/ and static/.

The rule for this project is that custom assets live in resources/ and
static/ holds only Django/third-party files. Because both trees are served
from the same /static/ and /resources/ URL namespaces
(frontend.serve_up.static_or_resources), a copy of a custom file that leaks
into static/ (e.g. via an old collectstatic run) is a shadowing hazard: it
can be served in place of the maintained resources/ copy, silently hiding
edits. This command finds every relative path that exists in both trees,
reports whether the two copies are identical or divergent, and can delete
the static/ copies with --delete.
"""

from __future__ import annotations

import filecmp
import os
from datetime import datetime
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand


def _walk_relative_files(root: str) -> set[str]:
    """
    Collect every file under a directory tree as a relative path.

    Args:
        root: Absolute path of the directory tree to walk.

    Returns:
        Set of file paths relative to root. Empty if root does not exist.
    """
    relative_paths: set[str] = set()
    if not os.path.isdir(root):
        return relative_paths
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if filename == ".DS_Store":
                continue
            full_path = os.path.join(dirpath, filename)
            relative_paths.add(os.path.relpath(full_path, root))
    return relative_paths


def _describe_file(path: str) -> str:
    """
    Return a short size/mtime description of a file for the audit report.

    Args:
        path: Absolute path of the file to describe.

    Returns:
        String of the form "<size> bytes, modified <YYYY-MM-DD HH:MM:SS>".
    """
    stat_result = os.stat(path)
    modified = datetime.fromtimestamp(stat_result.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return f"{stat_result.st_size} bytes, modified {modified}"


class Command(BaseCommand):
    """Find (and optionally delete) static/ copies that shadow resources/ files."""

    help = (
        "Audit for files that exist in both resources/ and static/. "
        "The static/ copy shadows the resources/ copy and should be deleted. "
        "Use --delete to remove the static/ copies."
    )

    def add_arguments(self, parser: Any) -> None:
        """
        Register command-line options.

        Args:
            parser: Django's argument parser for this command.
        """
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete the shadowing static/ copies (resources/ copies are never touched).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """
        Run the audit and print a report of duplicated relative paths.

        Args:
            *args: Unused positional arguments from Django.
            **options: Command options; "delete" removes static/ duplicates.
        """
        resources_root = settings.RESOURCES_PATH
        static_root = settings.STATIC_ROOT

        self.stdout.write(f"resources/: {resources_root}")
        self.stdout.write(f"static/   : {static_root}")

        duplicates = sorted(_walk_relative_files(resources_root) & _walk_relative_files(static_root))
        if not duplicates:
            self.stdout.write(self.style.SUCCESS("No duplicated files - static/ does not shadow resources/."))
            return

        self.stdout.write(self.style.WARNING(f"\n{len(duplicates)} file(s) exist in BOTH trees:\n"))
        for relative_path in duplicates:
            resource_file = os.path.join(resources_root, relative_path)
            static_file = os.path.join(static_root, relative_path)
            identical = filecmp.cmp(resource_file, static_file, shallow=False)
            status = "identical" if identical else "DIFFERENT"
            self.stdout.write(f"  {relative_path}  [{status}]")
            self.stdout.write(f"      resources: {_describe_file(resource_file)}")
            self.stdout.write(f"      static   : {_describe_file(static_file)}")
            if options["delete"]:
                os.remove(static_file)
                self.stdout.write(self.style.SUCCESS(f"      deleted  : {static_file}"))

        if options["delete"]:
            self.stdout.write(self.style.SUCCESS(f"\nDeleted {len(duplicates)} shadowing static/ cop(ies)."))
        else:
            self.stdout.write(self.style.WARNING("\nRun with --delete to remove the static/ copies."))
