# IndexDirs to DirectoryIndex Rename Plan

## Overview
Rename the `IndexDirs` model class to `DirectoryIndex` throughout the entire codebase, including all references, imports, variables, and documentation.

## Scope Analysis
Based on codebase analysis, the following items need updates:

### Name Variations to Change
1. **`IndexDirs`** - Class name (PascalCase) - 42 files
2. **`Index_Dirs`** - Snake_case variant in comments/strings - 12 files
3. **`index_dirs`** - Snake_case variant for variables - 3 files
4. **`indexdirs`** - Lowercase variant in module/cache names - multiple occurrences
5. **`indexdirs.py`** - Module filename

### Target Name Variations
1. **`DirectoryIndex`** - New class name (PascalCase)
2. **`Directory_Index`** - Snake_case equivalent in comments/strings
3. **`directory_index`** - Snake_case for variables
4. **`directoryindex`** - Lowercase for module/cache names
5. **`directoryindex.py`** - New module filename

---

## Phase 1: Pre-Migration Preparation

### 1.1 Create Backup Branch
```bash
git checkout -b refactor/indexdirs-to-directoryindex
git add -A
git commit -m "Checkpoint before IndexDirs to DirectoryIndex rename"
```

### 1.2 Run Full Test Suite
```bash
# Ensure all tests pass before starting
python manage.py test
```

### 1.3 Document Current Pylint Scores
```bash
# Record baseline scores for affected modules
python -m pylint quickbbs/indexdirs.py > pre-rename-pylint-indexdirs.txt
python -m pylint quickbbs/indexdata.py > pre-rename-pylint-indexdata.txt
python -m pylint quickbbs/models.py > pre-rename-pylint-models.txt
python -m pylint frontend/utilities.py > pre-rename-pylint-utilities.txt
python -m pylint cache_watcher/models.py > pre-rename-pylint-cache-watcher.txt
```

---

## Phase 2: Database Migration Preparation

### 2.1 Understand Django Model Renaming
Django migrations handle model renames through `RenameModel` operations. We will also rename the database table from `quickbbs_indexdirs` to `quickbbs_directoryindex` using `AlterModelTable`.

**Important:** Django will automatically handle:
- Renaming the table
- Updating all foreign key constraints
- Updating all indexes
- Preserving all data

No raw SQL required - Django migrations handle everything!

### 2.2 Create Django Migration
```bash
# After code changes, Django will detect the rename
python manage.py makemigrations --name rename_indexdirs_to_directoryindex
```

**Expected Migration Content:**
```python
operations = [
    migrations.RenameModel(
        old_name='IndexDirs',
        new_name='DirectoryIndex',
    ),
    migrations.AlterModelTable(
        name='DirectoryIndex',
        table='quickbbs_directoryindex',
    ),
]
```

**What Django Will Do:**
1. Rename the table: `quickbbs_indexdirs` → `quickbbs_directoryindex`
2. Update all foreign key constraints automatically
3. Update all indexes automatically (they reference the table name)
4. Update Django's ContentType registry
5. Preserve all data and relationships

### 2.3 Review Migration
- Verify migration contains both `RenameModel` and `AlterModelTable` operations
- Check for any related field renames in related models
- Ensure no data changes occur
- Verify Django will handle all index updates automatically

---

## Phase 3: Core Model Changes

### 3.1 Rename Module File
```bash
cd /Volumes/C-8TB/gallery/quickbbs/quickbbs/quickbbs/
git mv indexdirs.py directoryindex.py
```

### 3.2 Update directoryindex.py
**File:** `quickbbs/directoryindex.py`

**Changes:**
1. Update module docstring: `"""IndexDirs Model..."""` → `"""DirectoryIndex Model..."""`
2. Rename class: `class IndexDirs(models.Model):` → `class DirectoryIndex(models.Model):`
3. Update class docstring references
4. Update all internal method references to class name
5. Update all type hints: `"IndexDirs"` → `"DirectoryIndex"`
6. Update cache variable references if needed
7. **Add explicit `db_table` to Meta class** (optional but recommended for clarity):
   ```python
   class Meta:
       db_table = 'quickbbs_directoryindex'
       verbose_name = "Master Directory Index"
       verbose_name_plural = "Master Directory Index"
       indexes = [...]
   ```

**Key sections to update:**
- Line 46: Class declaration
- Line 47-49: Class docstring
- Line 71: `parent_directory` ForeignKey `related_name` considerations
- Line 109: Type hint for reverse relationship
- Line 115-122: Meta class - add explicit `db_table` setting
- Throughout: All `DirectoryIndex.objects`, `DirectoryIndex.search_for_directory`, etc.

### 3.3 Update models.py
**File:** `quickbbs/models.py`

**Changes:**
1. Update imports section to import from new module
2. Update constant names:
   - `INDEXDIRS_SELECT_RELATED_LIST` → `DIRECTORYINDEX_SELECT_RELATED_LIST`
   - `INDEXDIRS_PREFETCH_LIST` → `DIRECTORYINDEX_PREFETCH_LIST`
3. Update cache names:
   - `indexdirs_cache` → `directoryindex_cache`
4. Update all type hints and references throughout the file

**Lines to check:**
- Line 46: Cache variable declaration
- Lines 82-96: Constant definitions
- All function signatures using these constants

### 3.4 Update indexdata.py
**File:** `quickbbs/indexdata.py`

**Changes:**
1. Update import statement: `from .indexdirs import IndexDirs` → `from .directoryindex import DirectoryIndex`
2. Update all class references throughout
3. Update type hints: `"IndexDirs"` → `"DirectoryIndex"`
4. Update foreign key references: `home_directory`, `virtual_directory` field definitions
5. Update all method implementations that reference the class

**Key areas:**
- Imports section
- Field definitions (ForeignKey relationships)
- All methods that call `IndexDirs.search_for_directory()`, etc.
- Type hints in method signatures

---

## Phase 4: Application Code Updates

### 4.1 Frontend App
**Files to update:**
- `frontend/views.py`
- `frontend/utilities.py`
- `frontend/managers.py`
- `frontend/tests/test_search_integration.py`
- `frontend/tests/test_search_views.py`
- `frontend/tests/test_search_utils.py`
- `frontend/prototypes/subquery_test.py`

**Changes for each:**
1. Update imports
2. Update all class references
3. Update variable names (e.g., `index_dirs` → `directory_index`)
4. Update type hints
5. Update cache references

### 4.2 Cache Watcher App
**Files to update:**
- `cache_watcher/models.py`
- `cache_watcher/utilities.py`
- `cache_watcher/admin.py`
- `cache_watcher/tests/test_cache.py`
- `cache_watcher/depreciated/old-models.py`
- `cache_watcher/depreciated/models - single events.py`

**Key changes:**
1. Update `fs_Cache_Tracking.directory` ForeignKey reference
2. Update imports and class references
3. Update reverse relationship access patterns
4. Update cache clearing logic

### 4.3 Management Commands
**Files to update:**
- `quickbbs/management/commands/add_directories.py`
- `quickbbs/management/commands/add_files.py`
- `quickbbs/management/commands/scan.py`
- `quickbbs/management/commands/management_helper.py`

**Changes:**
1. Update imports
2. Update all object creation/query calls
3. Update variable names for clarity

### 4.4 Admin Interface
**File:** `quickbbs/admin.py`

**Changes:**
1. Update import statement
2. Update `admin.site.register()` call
3. Update any admin class definitions

### 4.5 Other Core Files
**Files to update:**
- `quickbbs/common.py` - Update any references in utility functions
- `filetypes/models.py` - Update reverse relationship references
- `conversions.py` - Update any model references
- `benchmarks/benchmark_models.py` - Update test/benchmark code

### 4.6 Test Files
**Files to update:**
- `quickbbs/tests/test_bulk_cache_clearing.py`
- `quickbbs/tests/test_parent_optimization.py`

**Changes:**
1. Update imports
2. Update test class references
3. Update fixture creation code
4. Update assertion references

---

## Phase 5: Documentation Updates

### 5.1 Project Documentation
**Files to update:**
- `CLAUDE.md`
- `.claude/README.md`
- `.claude/architecture.md`
- `.claude/development.md`
- `.claude/critical-runtime.md`
- `Docs/DATABASE_ERD.md`
- `Docs/QuickBBS.md`
- `Docs/OPTIMIZATION_CHANGES_IMPLEMENTED.md`
- `README.md`

**Changes:**
1. Update all model name references
2. Update code examples
3. Update entity relationship diagrams
4. Update architectural descriptions

### 5.2 Internal Documentation
**Files to update:**
- `quickbbs/materialization_optimizations.md`
- `quickbbs/refactoring-phase2.md`
- `quickbbs/methods to relocate.md`
- `quickbbs/models.py refactor.md`
- `Docs/materialization_optimizations.md`
- `Docs/unused_files.md`
- `indexdata-refactor.md`
- `htmx_improvements.md`

**Changes:**
1. Update model references
2. Update variable name examples
3. Update any diagrams or flow descriptions

### 5.3 Benchmark/Test Output Files
**Files (informational only, may skip):**
- All files in `benchmarks/tests/*.txt`

These are historical benchmark outputs and don't need updating unless used as reference.

---

## Phase 6: Migration Execution

### 6.1 Verify All Code Changes
```bash
# Search for any remaining references
cd /Volumes/C-8TB/gallery/quickbbs/quickbbs/
grep -r "IndexDirs" --exclude-dir=migrations --exclude-dir=benchmarks --exclude="*.pyc"
grep -r "Index_Dirs" --exclude-dir=migrations --exclude-dir=benchmarks --exclude="*.pyc"
grep -r "index_dirs" --exclude-dir=migrations --exclude-dir=benchmarks --exclude="*.pyc"
grep -r "indexdirs" --exclude-dir=migrations --exclude-dir=benchmarks --exclude="*.pyc" | grep -v directoryindex
```

### 6.2 Run Django Migration
```bash
# Generate migration
python manage.py makemigrations

# Review generated migration
cat quickbbs/migrations/000X_rename_indexdirs_to_directoryindex.py

# Apply migration to development database
python manage.py migrate

# Verify migration applied
python manage.py showmigrations quickbbs
```

### 6.3 Database Verification
```bash
# Connect to PostgreSQL and verify table was renamed
python manage.py dbshell
```

**PostgreSQL Commands:**
```sql
-- Verify table was renamed
\dt quickbbs_directoryindex

-- Check indexes were updated
\d quickbbs_directoryindex

-- Verify foreign keys point to new table name
SELECT
    conname AS constraint_name,
    conrelid::regclass AS table_name,
    confrelid::regclass AS referenced_table
FROM pg_constraint
WHERE confrelid = 'quickbbs_directoryindex'::regclass
   OR conrelid = 'quickbbs_directoryindex'::regclass;

-- Verify all expected indexes exist
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'quickbbs_directoryindex';

-- Exit psql
\q
```

**Expected Results:**
- Table `quickbbs_directoryindex` exists
- All indexes have been renamed/recreated
- Foreign key constraints from other tables point to new table
- Self-referential FK (`parent_directory`) updated
- All data preserved (count should match original)

---

## Phase 7: Quality Assurance

### 7.1 Type Checking
```bash
cd /Volumes/C-8TB/gallery/quickbbs/quickbbs/
PYTHONPATH=. mypy quickbbs/
```

### 7.2 Code Formatting
```bash
cd /Volumes/C-8TB/gallery/quickbbs/
./format_code.sh quickbbs/directoryindex.py
./format_code.sh quickbbs/indexdata.py
./format_code.sh quickbbs/models.py
./format_code.sh frontend/utilities.py
./format_code.sh frontend/views.py
./format_code.sh cache_watcher/models.py
# ... format all modified files
```

### 7.3 Pylint Verification
```bash
# Check all modified modules
python -m pylint quickbbs/directoryindex.py
python -m pylint quickbbs/indexdata.py
python -m pylint quickbbs/models.py
python -m pylint frontend/utilities.py
python -m pylint cache_watcher/models.py

# Compare with baseline scores - must not decrease
# Review and fix any new issues introduced
```

### 7.4 Test Suite Execution
```bash
# Run full test suite
python manage.py test

# Run specific app tests
python manage.py test quickbbs
python manage.py test frontend
python manage.py test cache_watcher
python manage.py test filetypes
```

### 7.5 Manual Testing Checklist
- [ ] Directory listing page loads correctly
- [ ] Directory navigation works (prev/next, breadcrumbs)
- [ ] Directory thumbnails display properly
- [ ] Directory search functionality works
- [ ] Directory cache invalidation works
- [ ] File upload to directories works
- [ ] Directory deletion works
- [ ] Parent-child directory relationships maintained
- [ ] Admin interface for DirectoryIndex works
- [ ] Cache watcher properly tracks directories

---

## Phase 8: Deployment Preparation

### 8.1 Update Migration Documentation
Create migration notes documenting:
- What changed (model name only)
- What didn't change (database table name)
- Rollback procedure if needed
- Any cache clearing required post-deployment

### 8.2 Create Rollback Plan
```bash
# If issues arise, rollback migration:
python manage.py migrate quickbbs <previous_migration_number>

# Revert code changes:
git revert <commit_hash>
```

### 8.3 Cache Invalidation Strategy
After deployment, may need to clear caches:
```python
# In Django shell or management command
from django.core.cache import cache
cache.clear()

# Or specifically clear model caches
from quickbbs.models import directoryindex_cache
directoryindex_cache.clear()
```

---

## Phase 9: Post-Deployment

### 9.1 Monitor Logs
- Check application logs for any model-related errors
- Monitor database query logs for issues
- Watch for cache-related errors

### 9.2 Verify Functionality
- Test all directory-related features in production
- Verify cache performance
- Check admin interface

### 9.3 Update Version History
**File:** `Docs/Version History.md`

Add entry:
```markdown
## [Version X.X.X] - YYYY-MM-DD
### Refactoring
- Renamed `IndexDirs` model to `DirectoryIndex` for improved clarity and naming consistency
- Updated all references throughout codebase
- Database table name remains unchanged for backward compatibility
```

---

## Phase 10: Cleanup

### 10.1 Remove Baseline Files
```bash
rm pre-rename-pylint-*.txt
```

### 10.2 Archive Old Documentation
Move any outdated refactoring notes to archive if needed.

### 10.3 Update This Plan
Mark this plan as completed and archive it:
```bash
git mv "IndexDirs rename plan.md" "Docs/completed/IndexDirs rename plan - COMPLETED.md"
```

---

## Risk Assessment

### Low Risk Items
- Class name changes (caught by Python at import time)
- Module rename (Git tracks this correctly)
- Documentation updates (no runtime impact)

### Medium Risk Items
- Cache variable names (may cause KeyErrors if not updated consistently)
- Type hints (may cause mypy errors but not runtime issues)
- Test files (will fail if not updated, but won't affect production)

### High Risk Items
- Database migration (must be tested thoroughly)
- Foreign key relationships (Django handles via migrations)
- Reverse relationship accessors (must verify all `related_name` attributes)

### Mitigation Strategies
1. **Comprehensive Testing:** Run full test suite at each phase
2. **Incremental Commits:** Commit after each phase for easy rollback
3. **Staging Environment:** Test migration in staging before production
4. **Database Backup:** Backup database before applying migration
5. **Gradual Deployment:** Deploy to subset of servers first if applicable

---

## Estimated Timeline

- **Phase 1 (Preparation):** 30 minutes
- **Phase 2 (Migration Prep):** 15 minutes
- **Phase 3 (Core Models):** 2 hours
- **Phase 4 (Application Code):** 3-4 hours
- **Phase 5 (Documentation):** 1-2 hours
- **Phase 6 (Migration):** 30 minutes
- **Phase 7 (QA):** 2 hours
- **Phase 8 (Deployment Prep):** 1 hour
- **Phase 9 (Post-Deployment):** 1 hour (monitoring)
- **Phase 10 (Cleanup):** 15 minutes

**Total Estimated Time:** 11-13 hours

---

## Success Criteria

- [ ] All imports updated and working
- [ ] All tests passing
- [ ] Pylint scores maintained or improved
- [ ] Type checking passes (mypy)
- [ ] Migration applied successfully
- [ ] All functionality verified in development
- [ ] Documentation completely updated
- [ ] No references to old name remain (except in git history)
- [ ] Cache functionality working correctly
- [ ] Admin interface functional

---

## Notes

### Database Table Name
The database table name **WILL** be renamed from `quickbbs_indexdirs` to `quickbbs_directoryindex` using Django's `AlterModelTable` migration operation.

**What Django Handles Automatically:**
- Table rename via `ALTER TABLE` SQL
- All foreign key constraint updates
- All index updates (Django renames indexes that reference the old table name)
- All sequence updates (for auto-increment fields)
- ContentType registry updates

**No manual SQL or index management required!**

### Import Compatibility
No backward compatibility layer will be maintained. This is an internal refactoring, not a public API change.

### Related Models Impact
Models with ForeignKey to `IndexDirs`:
- `IndexData.home_directory`
- `IndexData.virtual_directory`
- `IndexDirs.parent_directory` (self-referential)
- `fs_Cache_Tracking.directory`

All will be updated to reference `DirectoryIndex`. Django migrations will automatically update all foreign key constraints to point to the new table name.

### Cache Names
Cache variables will be renamed for consistency:
- `indexdirs_cache` → `directoryindex_cache`
- `INDEXDIRS_SELECT_RELATED_LIST` → `DIRECTORYINDEX_SELECT_RELATED_LIST`
- `INDEXDIRS_PREFETCH_LIST` → `DIRECTORYINDEX_PREFETCH_LIST`

### Index Handling
Django's migration system automatically handles all index renames:
- Primary key indexes
- Foreign key indexes
- Custom indexes defined in `Meta.indexes`
- Unique constraints

All indexes will be properly renamed to reference `quickbbs_directoryindex`.

---

## File Checklist

### Python Source Files (42 files)
- [ ] `quickbbs/indexdirs.py` → `quickbbs/directoryindex.py`
- [ ] `quickbbs/indexdata.py`
- [ ] `quickbbs/models.py`
- [ ] `quickbbs/admin.py`
- [ ] `quickbbs/common.py`
- [ ] `frontend/views.py`
- [ ] `frontend/utilities.py`
- [ ] `frontend/managers.py`
- [ ] `frontend/tests/test_search_integration.py`
- [ ] `frontend/tests/test_search_views.py`
- [ ] `frontend/tests/test_search_utils.py`
- [ ] `frontend/prototypes/subquery_test.py`
- [ ] `cache_watcher/models.py`
- [ ] `cache_watcher/utilities.py`
- [ ] `cache_watcher/admin.py`
- [ ] `cache_watcher/tests/test_cache.py`
- [ ] `cache_watcher/depreciated/old-models.py`
- [ ] `cache_watcher/depreciated/models - single events.py`
- [ ] `filetypes/models.py`
- [ ] `conversions.py`
- [ ] `quickbbs/management/commands/add_directories.py`
- [ ] `quickbbs/management/commands/add_files.py`
- [ ] `quickbbs/management/commands/scan.py`
- [ ] `quickbbs/management/commands/management_helper.py`
- [ ] `quickbbs/tests/test_bulk_cache_clearing.py`
- [ ] `quickbbs/tests/test_parent_optimization.py`
- [ ] `benchmarks/benchmark_models.py`

### Documentation Files
- [ ] `CLAUDE.md`
- [ ] `.claude/README.md`
- [ ] `.claude/architecture.md`
- [ ] `.claude/development.md`
- [ ] `.claude/critical-runtime.md`
- [ ] `.claude/commands.md`
- [ ] `.claude/templates-frontend.md`
- [ ] `Docs/DATABASE_ERD.md`
- [ ] `Docs/QuickBBS.md`
- [ ] `Docs/OPTIMIZATION_CHANGES_IMPLEMENTED.md`
- [ ] `Docs/materialization_optimizations.md`
- [ ] `Docs/Version History.md`
- [ ] `README.md`
- [ ] `quickbbs/materialization_optimizations.md`
- [ ] `quickbbs/refactoring-phase2.md`
- [ ] `quickbbs/methods to relocate.md`
- [ ] `quickbbs/models.py refactor.md`
- [ ] `indexdata-refactor.md`
- [ ] `htmx_improvements.md`

### Informational Only (Optional)
- [ ] `models.py refactor.md`
- [ ] `methods to relocate.md`
- [ ] `refactoring-phase2.md`
- [ ] All benchmark output files in `benchmarks/tests/`

---

## End of Plan
