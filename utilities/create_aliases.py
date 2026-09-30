#!/usr/bin/env python
"""
Create a pair of bidirectional macOS Finder aliases between two directories.

Given two directory paths, creates:
  * <dir_a>/<dir_b's basename>.alias  -> points to dir_b
  * <dir_b>/<dir_a's basename>.alias  -> points to dir_a

Both alias files are real Finder aliases (bookmark-based, survive the target
being renamed or moved), and both are tagged with a Finder label color.

Usage:
    python create_aliases.py <dir_a> <dir_b> [--label grey]
"""

# pylint: disable=no-name-in-module  # pyobjc uses dynamic imports

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from Foundation import NSURL, NSURLBookmarkCreationSuitableForBookmarkFile

# Finder label numbers, in the order they appear in Finder's label menu.
FINDER_LABELS: dict[str, int] = {
    "none": 0,
    "grey": 1,
    "gray": 1,
    "green": 2,
    "purple": 3,
    "blue": 4,
    "yellow": 5,
    "red": 6,
    "orange": 7,
}


class AliasCreationError(RuntimeError):
    """Raised when a Finder alias cannot be created or labeled."""


def make_finder_alias(target: Path, alias_path: Path, label: int | None = None) -> None:
    """Create a Finder alias file at alias_path pointing to target.

    Args:
        target: The directory or file the alias should resolve to.
        alias_path: Full path (including "<name>.alias") for the file to create.
        label: Finder label color number (0=none, 1=grey, 2=green, 3=purple,
            4=blue, 5=yellow, 6=red, 7=orange). None leaves the label unset.

    Raises:
        AliasCreationError: If bookmark creation, writing, or labeling fails.
    """
    target_url = NSURL.fileURLWithPath_(str(target))
    bookmark, error = target_url.bookmarkDataWithOptions_includingResourceValuesForKeys_relativeToURL_error_(
        NSURLBookmarkCreationSuitableForBookmarkFile,
        None,
        None,
        None,
    )
    if error is not None:
        raise AliasCreationError(f"Failed to create bookmark for {target}: {error}")

    alias_url = NSURL.fileURLWithPath_(str(alias_path))
    ok, error = NSURL.writeBookmarkData_toURL_options_error_(bookmark, alias_url, 0, None)
    if not ok:
        raise AliasCreationError(f"Failed to write alias at {alias_path}: {error}")

    if label is not None:
        ok, error = alias_url.setResourceValue_forKey_error_(label, "NSURLLabelNumberKey", None)
        if not ok:
            raise AliasCreationError(f"Failed to set label on {alias_path}: {error}")


def create_bidirectional_aliases(dir_a: Path, dir_b: Path, label: int | None = None) -> tuple[Path, Path]:
    """Create aliases in dir_a pointing to dir_b and vice versa.

    Args:
        dir_a: First directory.
        dir_b: Second directory.
        label: Finder label color number to apply to both aliases, or None.

    Returns:
        Tuple of (alias_in_a, alias_in_b) paths created.

    Raises:
        FileNotFoundError: If either directory does not exist.
        NotADirectoryError: If either path is not a directory.
        FileExistsError: If either destination alias path already exists.
        AliasCreationError: If alias creation fails.
    """
    for directory in (dir_a, dir_b):
        if not directory.exists():
            raise FileNotFoundError(f"No such directory: {directory}")
        if not directory.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")

    alias_in_a = dir_a / f"{dir_b.name}.alias"
    alias_in_b = dir_b / f"{dir_a.name}.alias"

    for alias_path in (alias_in_a, alias_in_b):
        if alias_path.exists() or alias_path.is_symlink():
            raise FileExistsError(f"Alias already exists: {alias_path}")

    make_finder_alias(dir_b, alias_in_a, label=label)
    make_finder_alias(dir_a, alias_in_b, label=label)

    return alias_in_a, alias_in_b


def main() -> int:
    """Parse arguments and create the bidirectional alias pair."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dir_a", type=Path, help="First directory")
    parser.add_argument("dir_b", type=Path, help="Second directory")
    parser.add_argument(
        "--label",
        default="grey",
        choices=sorted(FINDER_LABELS),
        help="Finder label color to apply to both aliases (default: grey)",
    )
    args = parser.parse_args()

    dir_a = args.dir_a.resolve()
    dir_b = args.dir_b.resolve()
    label = FINDER_LABELS[args.label]

    try:
        alias_in_a, alias_in_b = create_bidirectional_aliases(dir_a, dir_b, label=label)
    except (FileNotFoundError, NotADirectoryError, FileExistsError, AliasCreationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created {alias_in_a}")
    print(f"Created {alias_in_b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
