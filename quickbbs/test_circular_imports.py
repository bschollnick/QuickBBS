#!/usr/bin/env python
"""
Test which inline imports in fileindex.py can be moved to top-level.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

import django

django.setup()

print("=" * 80)
print("TESTING CIRCULAR IMPORT DEPENDENCIES")
print("=" * 80)
print()

# List of inline imports to test
inline_imports = [
    ("frontend.managers", "clear_layout_cache_for_directories"),
    ("filetypes.models", None),
    ("quickbbs.common", "normalize_string_title"),
    ("quickbbs.common", "normalize_fqpn"),
    ("django.db", "transaction"),
    (".directoryindex", "DirectoryIndex"),  # from .directoryindex (relative import)
    ("aiofiles", None),
    ("Foundation", "NSURL"),
]

results = []

for module_path, specific_import in inline_imports:
    try:
        if specific_import:
            if module_path.startswith("."):
                # Relative import
                exec(f"from quickbbs{module_path} import {specific_import}")
            else:
                exec(f"from {module_path} import {specific_import}")
            status = "✅ CAN MOVE TO TOP"
        else:
            if module_path.startswith("."):
                exec(f"from quickbbs import {module_path.lstrip('.')}")
            else:
                exec(f"import {module_path}")
            status = "✅ CAN MOVE TO TOP"

        results.append((module_path, specific_import, status, None))

    except ImportError as e:
        status = "❌ CIRCULAR DEPENDENCY"
        results.append((module_path, specific_import, status, str(e)))

    except Exception as e:
        status = "⚠️ OTHER ERROR"
        results.append((module_path, specific_import, status, str(e)))

print("\nRESULTS:")
print("=" * 80)
print()

for module_path, specific_import, status, error in results:
    import_str = f"from {module_path} import {specific_import}" if specific_import else f"import {module_path}"
    print(f"{status}")
    print(f"  {import_str}")
    if error:
        print(f"  Error: {error}")
    print()

# Summary
can_move = sum(1 for _, _, status, _ in results if "CAN MOVE" in status)
circular = sum(1 for _, _, status, _ in results if "CIRCULAR" in status)
other = sum(1 for _, _, status, _ in results if "OTHER" in status)

print("=" * 80)
print("SUMMARY:")
print(f"  Can move to top-level: {can_move}/{len(results)}")
print(f"  Circular dependencies: {circular}/{len(results)}")
print(f"  Other errors: {other}/{len(results)}")
print("=" * 80)
