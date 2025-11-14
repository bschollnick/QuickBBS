# Unused Files in QuickBBS

This document lists all Python files and templates that are not actively used by the QuickBBS web application.

**Generated:** 2025-10-29
**Total Unused Python Files:** 25 files (~5,045 lines of code)
**Total Unused Templates:** 1 file

---

## Table of Contents

1. [Benchmark/Testing Files](#benchmarktesting-files)
2. [Prototype/Development Files](#prototypedevelopment-files)
3. [Standalone File Utilities](#standalone-file-utilities)
4. [Configuration/Reference Files](#configurationreference-files)
5. [Test/Debug Scripts](#testdebug-scripts)
6. [Disabled Middleware](#disabled-middleware)
7. [Empty/Minimal Files](#emptyminimal-files)
8. [Unused Templates](#unused-templates)
9. [Recommendations](#recommendations)

---

## Benchmark/Testing Files

**Status:** Safe to delete - standalone testing tools not used by web app
**Total:** 8 files (~3,383 lines)

### 1. `benchmark_models.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/benchmark_models.py`
- **Lines:** 575
- **Purpose:** Model performance benchmarking
- **Reason Unused:** Standalone benchmark script with Django setup, not imported anywhere
- **Safe to Delete:** Yes (useful for performance testing, consider keeping)

### 2. `benchmarks/compare_benchmark_results.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/benchmarks/compare_benchmark_results.py`
- **Lines:** 455
- **Purpose:** Benchmark result analysis
- **Reason Unused:** Standalone analysis script, not imported
- **Safe to Delete:** Yes (useful for performance analysis, consider keeping)

### 3. `benchmarks/create_test_files.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/benchmarks/create_test_files.py`
- **Lines:** 16
- **Purpose:** Test data generation utility
- **Reason Unused:** Test data generation utility, not imported
- **Safe to Delete:** Yes

### 4. `benchmarks/locustfile_downloads.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/benchmarks/locustfile_downloads.py`
- **Lines:** 488
- **Purpose:** Locust load testing
- **Reason Unused:** Locust load testing script, not imported
- **Safe to Delete:** Yes (useful for load testing, consider keeping)

### 5. `benchmarks/run_download_benchmark.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/benchmarks/run_download_benchmark.py`
- **Lines:** 1,238
- **Purpose:** Comprehensive download benchmarking
- **Reason Unused:** Standalone benchmark runner, not imported
- **Safe to Delete:** Yes (useful for performance testing, consider keeping)

### 6. `file_count_benchmarks.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/file_count_benchmarks.py`
- **Lines:** 112
- **Purpose:** File counting performance tests
- **Reason Unused:** No imports found, standalone benchmark
- **Safe to Delete:** Yes

### 7. `cache_watcher/benchmark_cache_watcher.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/cache_watcher/benchmark_cache_watcher.py`
- **Lines:** 265
- **Purpose:** Cache watcher performance testing
- **Reason Unused:** Standalone benchmark, not imported
- **Safe to Delete:** Yes (useful for performance testing, consider keeping)

### 8. `cache_watcher/check_cache_status.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/cache_watcher/check_cache_status.py`
- **Lines:** 74
- **Purpose:** Cache diagnostics utility
- **Reason Unused:** Diagnostic utility, not part of web app
- **Safe to Delete:** Yes (useful for debugging, consider keeping)

---

## Prototype/Development Files

**Status:** Safe to delete - experimental code not integrated
**Total:** 7 files (~299 lines)

### 9. `frontend/prototypes/nnhash.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/prototypes/nnhash.py`
- **Lines:** 45
- **Purpose:** Experimental hashing algorithm
- **Reason Unused:** In prototypes directory, only self-referential usage found
- **Safe to Delete:** Yes

### 10. `frontend/prototypes/pdf_utilities.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/prototypes/pdf_utilities.py`
- **Lines:** 126
- **Purpose:** PDF utility experiments
- **Reason Unused:** In prototypes directory, only self-referential usage found
- **Safe to Delete:** Yes

### 11. `frontend/prototypes/sha224.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/prototypes/sha224.py`
- **Lines:** 10
- **Purpose:** SHA224 hashing test
- **Reason Unused:** In prototypes directory, only self-referential usage found
- **Safe to Delete:** Yes

### 12. `frontend/quick_bench.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/quick_bench.py`
- **Lines:** 46
- **Purpose:** Quick benchmark utility
- **Reason Unused:** No imports found
- **Safe to Delete:** Yes

### 13. `frontend/subquery_test.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/subquery_test.py`
- **Lines:** 11
- **Purpose:** Django ORM subquery testing
- **Reason Unused:** No imports found, experimental code with incomplete logic
- **Safe to Delete:** Yes

### 14. `cache_watcher/prototypes/watchdog_test.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/cache_watcher/prototypes/watchdog_test.py`
- **Lines:** 24
- **Purpose:** Watchdog testing
- **Reason Unused:** In prototypes directory, no imports
- **Safe to Delete:** Yes

### 15. `cache_watcher/prototypes/watchdog_test2.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/cache_watcher/prototypes/watchdog_test2.py`
- **Lines:** 47
- **Purpose:** Watchdog testing variant
- **Reason Unused:** In prototypes directory, no imports
- **Safe to Delete:** Yes

---

## Standalone File Utilities

**Status:** Safe to delete - not part of web application
**Total:** 3 files (~1,004 lines)

### 16. `frontend/archives3.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/archives3.py`
- **Lines:** 350
- **Purpose:** ZIP/RAR archive support library
- **Reason Unused:** No imports found, standalone archive utility library
- **Safe to Delete:** Yes

### 17. `frontend/file_mover_colors3.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/file_mover_colors3.py`
- **Lines:** 427
- **Purpose:** File organization utility
- **Reason Unused:** Standalone file manipulation tool (header confirms "NO DATABASE OPERATIONS")
- **Safe to Delete:** Yes
- **Note:** This is explicitly documented in CLAUDE.md as a standalone tool

### 18. `frontend/organize_by_person_name.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/organize_by_person_name.py`
- **Lines:** 227
- **Purpose:** File organization by person names
- **Reason Unused:** No imports found, standalone utility
- **Safe to Delete:** Yes

---

## Configuration/Reference Files

**Status:** Verify before deleting - may be reference documentation
**Total:** 2 files (~107 lines)

### 19. `quickbbs/3rd_party_libraries.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/quickbbs/3rd_party_libraries.py`
- **Lines:** 22
- **Purpose:** CDN library version configuration
- **Reason Unused:** No imports found, CDN version references
- **Safe to Delete:** Verify first - may track CDN versions
- **Recommendation:** Review content before deleting

### 20. `quickbbs/logger.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/quickbbs/logger.py`
- **Lines:** 85
- **Purpose:** Alternative logging configuration
- **Reason Unused:** No imports found, settings.py has own logging config
- **Safe to Delete:** Verify first - may be alternative config
- **Recommendation:** Review if used for specific deployment scenarios

---

## Test/Debug Scripts

**Status:** Safe to delete - standalone diagnostic tools
**Total:** 2 files (~221 lines)

### 21. `conversions.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/conversions.py`
- **Lines:** 183
- **Purpose:** Database conversion testing/debugging
- **Reason Unused:** No imports found, test/debug code with Django setup
- **Safe to Delete:** Yes

### 22. `quickbbs/pdf_repair.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/quickbbs/pdf_repair.py`
- **Lines:** 38
- **Purpose:** PDF repair utility
- **Reason Unused:** No imports found, standalone CLI tool (sys.argv usage)
- **Safe to Delete:** Yes

---

## Disabled Middleware

**Status:** Safe to delete - not enabled in settings.py
**Total:** 1 file (22 lines)

### 23. `quickbbs/middleware/filter_ips.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/quickbbs/middleware/filter_ips.py`
- **Lines:** 22
- **Purpose:** IP filtering middleware
- **Reason Unused:** Not in settings.py MIDDLEWARE list, defines FilterHostMiddleware but not imported
- **Safe to Delete:** Yes (not enabled)

---

## Empty/Minimal Files

**Status:** Safe to delete - no content or unused
**Total:** 2 files (9 lines)

### 24. `DirScanning/scanner.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/DirScanning/scanner.py`
- **Lines:** 0 (EMPTY FILE)
- **Purpose:** Unknown - placeholder or leftover file
- **Reason Unused:** Empty file, no content
- **Safe to Delete:** Yes

### 25. `frontend/constants.py`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/constants.py`
- **Lines:** 9
- **Purpose:** Likely minimal/unused constants
- **Reason Unused:** No imports found
- **Safe to Delete:** Yes

---

## Unused Templates

**Total:** 1 file

### 1. `templates/frontend/item/old/gallery_htmx_image-videojs.jinja`
- **Location:** `/Volumes/C-8TB/gallery/quickbbs/quickbbs/templates/frontend/item/old/gallery_htmx_image-videojs.jinja`
- **Purpose:** Old video.js-based video viewer
- **Reason Unused:** In "old" directory, no references in views.py or other templates (replaced by current implementation)
- **Safe to Delete:** Yes

---

## Recommendations

### Immediate Cleanup (Safe to Delete)

The following files can be safely deleted without affecting the web application:

```bash
# Navigate to project directory
cd /Volumes/C-8TB/gallery/quickbbs/quickbbs

# Delete benchmark files (8 files)
rm -rf benchmarks/
rm benchmark_models.py
rm file_count_benchmarks.py
rm cache_watcher/benchmark_cache_watcher.py
rm cache_watcher/check_cache_status.py

# Delete prototype files (7 files)
rm -rf frontend/prototypes/
rm -rf cache_watcher/prototypes/
rm frontend/quick_bench.py
rm frontend/subquery_test.py

# Delete standalone utilities (3 files)
rm frontend/archives3.py
rm frontend/file_mover_colors3.py
rm frontend/organize_by_person_name.py

# Delete test/debug scripts (2 files)
rm conversions.py
rm quickbbs/pdf_repair.py

# Delete disabled middleware (1 file)
rm quickbbs/middleware/filter_ips.py

# Delete empty/minimal files (2 files)
rm DirScanning/scanner.py
rm frontend/constants.py

# Delete old template (1 file)
rm templates/frontend/item/old/gallery_htmx_image-videojs.jinja
```

**Total files to delete:** 24 Python files + 1 template = 25 files
**Total lines removed:** ~5,045 lines of Python code

### Consider Keeping (Developer Tools)

The following files may be useful for development and testing:

- **Benchmark files** - Useful for performance testing and optimization work
  - Could be moved to a separate repository or `dev-tools/` directory
  - `benchmarks/` directory and related benchmark files

### Verify Before Deleting

The following files should be reviewed before deletion:

1. **`quickbbs/3rd_party_libraries.py`** (22 lines)
   - May track CDN versions for frontend libraries
   - Review content to determine if it's documentation

2. **`quickbbs/logger.py`** (85 lines)
   - May be an alternative logging configuration
   - Verify it's not used in any deployment scenarios

### Files Verified as USED (Not in this list)

These files appeared questionable but ARE actively used:
- `quickbbs/natsort_model.py` - Imported by quickbbs/models.py
- `quickbbs/middleware/download_optimization.py` - Exists but commented out in settings (keep for reference)
- Thumbnail backends (avfoundation, core_image, pdfkit) - Conditionally imported based on platform

---

## Summary Statistics

| Category | Files | Lines | Safe to Delete |
|----------|-------|-------|----------------|
| Benchmark/Testing | 8 | ~3,383 | Yes (consider keeping for dev) |
| Prototype/Development | 7 | ~299 | Yes |
| Standalone Utilities | 3 | ~1,004 | Yes |
| Configuration/Reference | 2 | ~107 | Verify first |
| Test/Debug Scripts | 2 | ~221 | Yes |
| Disabled Middleware | 1 | 22 | Yes |
| Empty/Minimal | 2 | 9 | Yes |
| **Total Python** | **25** | **~5,045** | **23 safe, 2 verify** |
| **Templates** | **1** | N/A | **Yes** |

---

## Notes

- This analysis was performed on 2025-10-29
- All file paths are relative to `/Volumes/C-8TB/gallery/quickbbs/quickbbs/`
- Line counts are approximate and based on current file state
- "Safe to Delete" means the file is not imported or used by the web application
- Some files (like benchmarks) may be useful for development even if not used by the app
- Before bulk deletion, consider creating a backup or git commit

---

**Next Steps:**

1. Review the "Verify Before Deleting" section
2. Decide whether to keep benchmark files for development
3. Create a git commit before deletion (for safety)
4. Run the deletion commands in batches
5. Test the application after deletion
6. Run `pylint` to verify no import errors were introduced
