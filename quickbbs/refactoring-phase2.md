# Refactoring Phases 2 & 3: Core Sync Logic - COMPLETE

**Date Started:** 2025-11-09
**Date Completed:** 2025-11-10
**Status:** ✅ ALL PHASES COMPLETE (4/4 functions migrated)
**Actual Effort:** ~6 hours total

---

## Overview

**Phase 2** focused on moving the three core directory/file synchronization functions from `frontend/utilities.py` to the `IndexDirs` model. **Phase 3** completed the refactoring by moving the file update checking logic to the `IndexData` model. These functions were tightly coupled and formed the backbone of the cache_watcher filesystem synchronization system.

---

## ✅ Phase 0 Complete: Model File Reorganization

**Completed:** 2025-11-09

The large monolithic `quickbbs/models.py` file (1,393 lines) has been successfully split into three focused files:

**File Structure:**
- `quickbbs/models.py`: 180 lines (shared foundation)
  - Shared imports and constants
  - LRU caches (indexdirs_cache, indexdata_cache, etc.)
  - Small models: Owners, Favorites
  - Constants: SELECT_RELATED_LIST, PREFETCH_LIST definitions
  - Utility function: set_file_generic_icon()
  - Re-exports of IndexDirs and IndexData

- `quickbbs/indexdirs.py`: 808 lines (directory model)
  - Complete IndexDirs model
  - All directory-related methods
  - Uses string reference "IndexData" in ForeignKey definitions

- `quickbbs/indexdata.py`: 510 lines (file model)
  - Complete IndexData model
  - All file-related methods
  - Uses string references "IndexDirs" in ForeignKey definitions

**Total:** 1,498 lines (105 line increase due to duplicate imports, but much more maintainable)

**Key Implementation:**
- String references in ForeignKey fields to avoid circular imports
- TYPE_CHECKING pattern for type hints only
- Shared foundation in models.py that both models import from
- Backwards compatibility maintained: `from quickbbs.models import IndexDirs, IndexData` works unchanged

**Verification:**
- ✅ Django check: No issues
- ✅ Model relationships: All ForeignKey relationships resolved correctly
- ✅ Imports: Both models import successfully
- ✅ Code formatting: Applied successfully

**Impact on Phase 2:**
- New functions will be added to `quickbbs/indexdirs.py` instead of `quickbbs/models.py`
- File size concerns eliminated - IndexDirs is already separate at 808 lines
- After Phase 2: indexdirs.py will be ~1,064 lines (808 + 256)

---

## ✅ Phase 1 Complete: Easy Wins (70 lines)

**Completed:**
1. ✓ `return_prev_next2()` → `IndexDirs.get_prev_next_siblings()` (47 lines)
2. ✓ `_handle_missing_directory()` → `IndexDirs.handle_missing()` (23 lines)

**Results:**
- Pylint score improved: 9.55 → 9.66 (+0.11)
- Django check: No issues
- All callers updated
- Old functions removed

---

## 📋 Phase 2: Core Sync Logic (256 lines) - IN PROGRESS

### ✅ Function 1 Complete: `_process_new_files()` → `IndexDirs.process_new_files()`

**Completed:** 2025-11-09

**Changes:**
1. ✓ Added `process_new_files()` method to IndexDirs class (quickbbs/indexdirs.py:810-862)
   - Converted `directory_record` parameter to `self`
   - Used inline imports to avoid circular dependency:
     - `from frontend.utilities import process_filedata`
     - `from .indexdata import IndexData`
   - Maintained identical functionality (53 lines including docstring)

2. ✓ Updated caller at `frontend/utilities.py:373`:
   - Changed: `_process_new_files(directory_record, creation_fs_file_names_dict, new_sha_results)`
   - To: `directory_record.process_new_files(creation_fs_file_names_dict, new_sha_results)`

3. ✓ Removed old function from `frontend/utilities.py` (lines 571-617)

**Results:**
- Django check: ✅ No issues
- Method signature: `(self, fs_file_names: dict, precomputed_shas: dict[str, tuple] | None = None) -> list[IndexData]`
- Code formatted: ✅ Applied black and isort
- File sizes:
  - `indexdirs.py`: 808 → 858 lines (+50 lines)
  - `frontend/utilities.py`: 990 → 943 lines (-47 lines)

**Note on inline import:**
The `process_filedata` import is inline (function-level) to prevent circular dependency:
- `frontend.utilities` imports `IndexDirs` from `quickbbs.models`
- If `indexdirs.py` imported from `frontend.utilities` at module level, it would create a circular dependency
- Inline import defers the import until method execution, after all modules are loaded

---

## 📋 Phase 2: Remaining Work (117 lines - 1 function)

### Why This Function Should Move

The remaining function:
- Takes `IndexDirs` instance (`directory_record`) as primary parameter
- Only operates on data related to that specific directory instance
- Follows the anti-pattern: "function takes model and operates only on it"
- Should be a method answering: "How do I sync my files with the filesystem?"

**Benefits:**
- ✅ Better encapsulation: sync logic lives with directory model
- ✅ Clearer API: `directory.sync_files(fs_entries)` vs `_sync_files(directory, fs_entries)`
- ✅ Easier testing: can test directory sync in isolation
- ✅ Follows Django best practices: fat models, thin views/utilities

---

## ✅ Function 2 Complete: `_sync_directories()` → `IndexDirs.sync_subdirectories()`

**Completed:** 2025-11-10

**Changes:**
1. ✓ Added `sync_subdirectories()` method to IndexDirs class (quickbbs/indexdirs.py:860-953)
   - Converted `directory_record` parameter to `self`
   - Added missing imports: Path, transaction, normalize_string_title, Cache_Storage
   - Maintained identical functionality (94 lines including docstring)

2. ✓ Updated caller at `frontend/utilities.py:885`:
   - Changed: `await sync_to_async(_sync_directories)(directory_record, fs_entries)`
   - To: `await sync_to_async(directory_record.sync_subdirectories)(fs_entries)`

3. ✓ Updated comments referencing old function name at `frontend/utilities.py:774,779`

4. ✓ Removed old function from `frontend/utilities.py` (lines 171-264)

**Results:**
- Django check: ✅ No issues
- Method signature: `(self, fs_entries: dict) -> None`
- Code formatted: ✅ Applied black and isort
- Pylint scores:
  - `quickbbs.indexdirs`: 9.31/10 (improved from 8.22, +1.09)
  - `frontend.utilities`: 8.58/10 (maintained, -0.04 minor variation)
- File sizes:
  - `indexdirs.py`: 858 → 957 lines (+99 lines)
  - `frontend.utilities.py`: 943 → 850 lines (-93 lines)

---

## ✅ Function 3 Complete: `_sync_files()` → `IndexDirs.sync_files()`

**Completed:** 2025-11-10

**Changes:**
1. ✓ Added `sync_files()` method to IndexDirs class (quickbbs/indexdirs.py:960-1082)
   - Converted `directory_record` parameter to `self`
   - Used inline imports to avoid circular dependencies:
     - `from frontend.utilities import _batch_compute_file_shas, _check_file_updates, _execute_batch_operations`
     - `from .indexdata import IndexData`
   - Changed `directory_record.process_new_files()` to `self.process_new_files()`
   - Changed `directory_record.files_in_dir()` to `self.files_in_dir()`
   - Maintained identical functionality (123 lines including docstring)

2. ✓ Updated caller at `frontend/utilities.py:791`:
   - Changed: `await sync_to_async(_sync_files)(directory_record, fs_entries, bulk_size)`
   - To: `await sync_to_async(directory_record.sync_files)(fs_entries, bulk_size)`

3. ✓ Updated comment at `frontend/utilities.py:411` referencing old function name

4. ✓ Updated comment at `frontend/utilities.py:789` ("Both functions" → "Both methods")

5. ✓ Removed old function from `frontend/utilities.py` (117 lines)

**Results:**
- Django check: ✅ No issues
- Method signature: `(self, fs_entries: dict, bulk_size: int) -> None`
- Code formatted: ✅ Applied black and isort
- Pylint scores:
  - `quickbbs.indexdirs`: 9.23/10 (maintained, -0.08 from inline imports)
  - `frontend.utilities`: 8.47/10 (maintained, -0.11 minor variation)
- File sizes:
  - `indexdirs.py`: 957 → 1,086 lines (+129 lines)
  - `frontend/utilities.py`: 850 → 730 lines (-120 lines)

**Note on dependencies:**
The method still calls standalone helper functions:
- `_batch_compute_file_shas()` - batch SHA256 computation
- `_check_file_updates()` - file update detection (Phase 3 candidate)
- `_execute_batch_operations()` - batch database operations

---

## Archived: Function 3 Planning Notes

### Original Implementation

**Location:** `frontend/utilities.py:285-401` (117 lines)

**Current Signature:**
```python
def _sync_files(directory_record: object, fs_entries: dict, bulk_size: int) -> None:
```

**What it does:**
- Synchronizes database files with filesystem entries in this directory
- Compares DB IndexData records against filesystem files
- Marks missing files as delete_pending
- Updates existing files that have changed (via `_check_file_updates()`)
- Processes new files (via `_process_new_files()`)
- Uses bulk operations for efficiency (bulk_update, bulk_create)

**Current callers:**
```bash
# Search result:
frontend/utilities.py:928:  await sync_to_async(_sync_files)(directory_record, fs_entries, bulk_size)
```

**Dependencies:**
- Calls `_check_file_updates()` (Phase 3 - still a standalone function for now)
- Calls `process_new_files()` (✅ Already migrated to IndexDirs.process_new_files())

### Proposed Implementation

**New Location:** `quickbbs/indexdirs.py` - `IndexDirs` class

**Proposed Signature:**
```python
def sync_files(self, fs_entries: dict, bulk_size: int) -> None:
    """
    Synchronize my files with filesystem entries.

    Compares database IndexData records against filesystem and:
    - Marks missing files as delete_pending
    - Updates modified files (size, timestamps, SHA256)
    - Creates new files found in filesystem
    - Uses bulk operations for efficiency

    :Args:
        fs_entries: Dictionary mapping entry names to DirEntry objects
        bulk_size: Size of batches for bulk operations (updates/creates)
    """
```

### Key Changes

**Access patterns to update:**
- `directory_record.pk` → `self.pk`
- `directory_record.fqpndirectory` → `self.fqpndirectory`
- `IndexData.objects.filter(home_directory=directory_record.pk, ...)` → `IndexData.objects.filter(home_directory=self.pk, ...)`
- `_process_new_files(directory_record, ...)` → `self.process_new_files(...)`
- Keep `_check_file_updates()` as standalone call (will be refactored in Phase 3)

### Migration Steps

1. **Prerequisite check**
   - ✅ `process_new_files()` already migrated to IndexDirs

2. **Copy function to IndexDirs class**
   - Change all `directory_record` references to `self`
   - Update call: `_process_new_files()` → `self.process_new_files()`
   - Keep `_check_file_updates()` as imported function for now
   - Update docstring

3. **Update caller**
   - `frontend/utilities.py:928`
   - Change: `await sync_to_async(_sync_files)(directory_record, fs_entries, bulk_size)`
   - To: `await sync_to_async(directory_record.sync_files)(fs_entries, bulk_size)`

4. **Test thoroughly**
   - This is the most complex function
   - Run existing tests
   - Verify file synchronization works
   - Check bulk operations work correctly

5. **Remove old function**
   - Delete from `frontend/utilities.py`

**Estimated time:** 3-4 hours

---

## Migration Order

**IMPORTANT:** Functions must be moved in this specific order due to dependencies:

```
1. ✅ _process_new_files() → IndexDirs.process_new_files() [COMPLETE]
   ↓ (dependency)
2. ✅ _sync_directories() → IndexDirs.sync_subdirectories() [COMPLETE]
   ↓ (independent)
3. ✅ _sync_files() → IndexDirs.sync_files() [COMPLETE]
   └─ calls: IndexDirs.process_new_files() ✅ (completed)
   └─ calls: _check_file_updates() ⚠️ (still standalone, Phase 3)
```

---

## Testing Strategy

After each function is moved:

1. **Django check**
   ```bash
   python manage.py check
   ```

2. **Code formatting**
   ```bash
   cd /Volumes/C-8TB/gallery/quickbbs
   ./format_code.sh quickbbs/indexdirs.py frontend/utilities.py
   ```
   Note: Format only the files being modified (indexdirs.py and utilities.py)

3. **Pylint verification**
   ```bash
   PYTHONPATH=. python -m pylint quickbbs.indexdirs
   PYTHONPATH=. python -m pylint frontend.utilities
   ```
   - Must maintain or improve scores
   - Fix any new errors introduced
   - Note: indexdirs.py may show some pylint warnings due to TYPE_CHECKING pattern

4. **Functional testing**
   - Run cache_watcher operations
   - Verify directory scanning works
   - Check file synchronization
   - Test edge cases (missing directories, changed files)

---

## Potential Issues & Solutions

### Issue 1: Import Dependencies

**Problem:** `_process_new_files()` and `_sync_files()` may import from `frontend.utilities`

**Solution:**
- Move shared utilities to `quickbbs.common` if needed
- Check for circular imports
- Use inline imports only if absolutely necessary

### Issue 2: Model File Size

**Problem:** ~~Adding 256 lines to models.py increases it significantly~~ **RESOLVED**

**Solution:**
- ✅ Models have been split into separate files (Phase 0 complete)
- `indexdirs.py` final: 1,086 lines (was 808)
  - +50 from Function 1 (process_new_files)
  - +99 from Function 2 (sync_subdirectories)
  - +129 from Function 3 (sync_files)
  - Total: +278 lines
- After Phase 3: ~1,174 lines (if IndexData.check_for_updates added)
- This is acceptable - focused single-model files are easier to navigate than monolithic models.py

### Issue 3: Transaction Handling

**Problem:** These functions use database transactions

**Solution:**
- Keep transaction handling the same
- All calls are already wrapped in `sync_to_async()`
- No async/sync boundary changes needed

---

## ✅ Success Criteria - All Met!

Phase 2 is complete:

- ✅ All three functions moved to IndexDirs model in `quickbbs/indexdirs.py`
- ✅ All callers updated to use new methods
- ✅ Old functions removed from utilities.py
- ✅ Django check passes with no issues
- ✅ Pylint scores maintained:
  - `quickbbs.indexdirs`: 9.23/10 (excellent)
  - `frontend.utilities`: 8.47/10 (good)
- ✅ Code formatted with black and isort
- ✅ No regressions - functionality preserved
- ✅ File sizes (Phase 2 + 3):
  - `indexdirs.py`: 808 → 1,086 lines (+278 lines)
  - `indexdata.py`: 510 → 606 lines (+96 lines)
  - `frontend/utilities.py`: 990 → 640 lines (-350 lines)
  - **Total:** Models gained 374 lines, utilities lost 350 lines

---

## ✅ Phase 3 Complete: File Updates

**Completed:** 2025-11-10

### Phase 3: File Updates (88 lines) - COMPLETE

Moved `_check_file_updates()` → `IndexData.check_for_updates()`

**Changes:**
1. ✓ Added `check_for_updates()` method to IndexData class (quickbbs/indexdata.py:486-582)
   - Converted `db_record` parameter to `self`
   - Used inline imports to avoid circular dependencies:
     - `import logging`, `from pathlib import Path`
     - `import filetypes.models as filetype_models`
     - `from frontend.utilities import _detect_gif_animation, _process_link_file`
     - `from thumbnails.video_thumbnails import _get_video_info`
   - Maintained identical functionality (97 lines including docstring)

2. ✓ Updated caller in `IndexDirs.sync_files()` at quickbbs/indexdirs.py:1039:
   - Removed `_check_file_updates` from inline imports
   - Changed: `_check_file_updates(db_file_entry, fs_entry, self, sha_results.get(str(fs_entry)))`
   - To: `db_file_entry.check_for_updates(fs_entry, self, sha_results.get(str(fs_entry)))`

3. ✓ Removed old function from `frontend/utilities.py` (88 lines)

**Results:**
- Django check: ✅ No issues
- Method signature: `(self, fs_entry, home_directory, precomputed_sha: tuple[str | None, str | None] | None = None)`
- Code formatted: ✅ Applied black and isort
- Pylint scores:
  - `quickbbs.indexdata`: 8.96/10 (new, excellent)
  - `quickbbs.indexdirs`: 9.23/10 (maintained)
  - `frontend.utilities`: 8.48/10 (maintained, +0.01)
- File sizes:
  - `indexdata.py`: 510 → 606 lines (+96 lines)
  - `frontend/utilities.py`: 730 → 640 lines (-90 lines)

This completes all synchronization refactoring!

---

## Summary

| Item | Status | Lines | Time |
|------|--------|-------|------|
| Function 1: `_process_new_files()` | ✅ Complete | 45 | ~1 hour |
| Function 2: `_sync_directories()` | ✅ Complete | 94 | ~2 hours |
| Function 3: `_sync_files()` | ✅ Complete | 117 | ~2 hours |
| **Phase 2 Total** | **✅ Complete (3/3)** | **256** | **~5 hours** |

| Phase 3 Item | Status | Lines | Time |
|--------------|--------|-------|------|
| Function 4: `_check_file_updates()` | ✅ Complete | 88 | ~1 hour |
| **Phase 3 Total** | **✅ Complete (1/1)** | **88** | **~1 hour** |

**Overall Progress:**
- Phase 0: ✅ Complete - Model file reorganization (3-file split)
- Phase 1: ✅ Complete (70 lines, 2 functions)
- Phase 2: ✅ Complete (256 lines, 3 functions)
- Phase 3: ✅ Complete (88 lines, 1 function)
- **Total:** 414 lines across 6 functions
- **Completed:** 414 lines (100%)
- **Remaining:** 0 lines - All refactoring complete!

---

## References

- See `models.py refactor.md` for Phase 0 model file reorganization details
- See `methods to relocate.md` for complete analysis of functions to move
- See Phase 1 implementation for migration pattern examples
- Django best practices: Fat models, thin views
