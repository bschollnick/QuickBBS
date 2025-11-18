#!/usr/bin/env python
"""
Test if moving inline imports to top-level causes circular dependencies.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "quickbbs.settings")

import django

django.setup()

print("=" * 80)
print("TESTING FILEINDEX.PY IMPORTS")
print("=" * 80)
print()

# Test 1: Can we import DirectoryIndex at module level?
print("Test 1: Import DirectoryIndex from .directoryindex")
try:
    from quickbbs.directoryindex import DirectoryIndex
    print("  ✅ SUCCESS - DirectoryIndex can be imported")
    print(f"  DirectoryIndex: {DirectoryIndex}")
except ImportError as e:
    print(f"  ❌ CIRCULAR DEPENDENCY: {e}")
except Exception as e:
    print(f"  ⚠️ OTHER ERROR: {e}")
print()

# Test 2: Import FileIndex (which uses DirectoryIndex)
print("Test 2: Import FileIndex (uses DirectoryIndex in TYPE_CHECKING)")
try:
    from quickbbs.fileindex import FileIndex
    print("  ✅ SUCCESS - FileIndex imports correctly")
    print(f"  FileIndex: {FileIndex}")
except ImportError as e:
    print(f"  ❌ CIRCULAR DEPENDENCY: {e}")
except Exception as e:
    print(f"  ⚠️ OTHER ERROR: {e}")
print()

# Test 3: Check if DirectoryIndex imports FileIndex
print("Test 3: Check if DirectoryIndex uses FileIndex")
try:
    import inspect
    import quickbbs.directoryindex as dir_module
    source = inspect.getsource(dir_module)

    if "from .fileindex import FileIndex" in source or "from quickbbs.fileindex import FileIndex" in source:
        print("  ⚠️ DirectoryIndex imports FileIndex directly")
    elif "FileIndex" in source:
        print("  ℹ️ DirectoryIndex references FileIndex (possibly TYPE_CHECKING or inline)")
    else:
        print("  ✅ DirectoryIndex doesn't import FileIndex")
except Exception as e:
    print(f"  ⚠️ ERROR checking: {e}")
print()

print("=" * 80)
print("CONCLUSION:")
print("=" * 80)
print()
print("DirectoryIndex is already in TYPE_CHECKING block in fileindex.py")
print("This is the correct approach - it avoids circular imports while")
print("providing type hints.")
print()
print("The inline imports marked as 'avoid circular dependencies' should")
print("be tested individually to see if they can be moved to top-level.")
print("=" * 80)
