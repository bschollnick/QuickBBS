# Frontend Search Tests

This directory contains comprehensive test cases for the search functionality in the QuickBBS gallery application.

## Test Files

### `test_search_views.py`
- **Purpose**: Tests the main search view function (`search_viewresults`)
- **Covers**:
  - Basic search functionality
  - Separator-agnostic search (spaces, underscores, dashes)
  - Directory and file search
  - Pagination
  - Context variables
  - HTMX template selection
  - Exclusion of deleted files

### `test_search_integration.py`
- **Purpose**: Integration tests for the complete search workflow
- **Covers**:
  - URL routing
  - Form submission
  - Various query patterns
  - Pagination URLs
  - Sort options
  - HTMX requests
  - Performance edge cases
  - Special characters and Unicode
  - Template rendering issues

### `test_search_utils.py`
- **Purpose**: Unit tests for search utility functions
- **Covers**:
  - Search variations function
  - Q object construction
  - Case insensitivity
  - Delete pending exclusion
  - Edge cases and error conditions

## Running Tests

### Run all frontend tests:
```bash
cd /path/to/quickbbs
python manage.py test frontend.tests
```

### Run specific test modules:
```bash
# Test search views only
python manage.py test frontend.tests.test_search_views

# Test search integration only
python manage.py test frontend.tests.test_search_integration

# Test search utilities only
python manage.py test frontend.tests.test_search_utils
```

### Run with pytest (if available):
```bash
# Run all tests
pytest frontend/tests/

# Run with verbose output
pytest frontend/tests/ -v

# Run specific test file
pytest frontend/tests/test_search_views.py

# Run specific test class
pytest frontend/tests/test_search_views.py::TestSearchViews

# Run specific test method
pytest frontend/tests/test_search_views.py::TestSearchViews::test_separator_agnostic_search
```

## Test Coverage

The tests cover:

1. **Core Functionality**:
   - Search across files and directories
   - Separator-agnostic matching (Mary Jane Watson = Mary_Jane_Watson = Mary-Jane-Watson)
   - Case-insensitive search
   - Proper ordering (directories first, then files)

2. **Edge Cases**:
   - Empty search queries
   - Very long search strings
   - Special characters
   - Unicode characters
   - Files marked for deletion

3. **Integration**:
   - URL routing
   - Template rendering
   - HTMX requests
   - Pagination
   - Form submission

4. **Template Issues**:
   - Breadcrumb format compatibility
   - Jinja2 compatibility (no hasattr usage)
   - Context variable availability

## Key Test Data Patterns

Tests use realistic file naming patterns:
- `Mary_Jane_Watson_01.jpg`
- `Mary-Jane-Watson-02.jpg`
- `Mary Jane Watson 03.jpg`
- `Spider_Man_Amazing_01.jpg`
- `Spider-Man-Web-of-Shadows.jpg`
- `SPIDER-MAN-COMIC-01.jpg`

## Expected Behavior

1. **Separator Agnostic**: Search for "Mary Jane Watson" finds files named with underscores, dashes, or spaces
2. **Case Insensitive**: "spider man" matches "Spider_Man", "SPIDER-MAN", etc.
3. **Directory Priority**: Directories appear before files in results
4. **Deleted Files Excluded**: Files with `delete_pending=True` don't appear in results
5. **Pagination**: Large result sets are properly paginated
6. **Template Safety**: No Jinja2 compatibility issues

## Debugging Test Failures

Common issues and solutions:

1. **Template Rendering Failures**:
   - Check that Jinja2 templates don't use `hasattr()`
   - Verify breadcrumbs format is correct
   - Ensure context variables are properly passed

2. **Database Issues**:
   - Verify test data is created correctly
   - Check that filetypes are properly set up
   - Ensure foreign key relationships are valid

3. **Search Logic Issues**:
   - Check Q object construction
   - Verify search variations are generated correctly
   - Test case sensitivity and separator handling

## Test Performance

Tests are designed to:
- Use minimal test data for fast execution
- Clean up after themselves
- Use Django's transaction test cases where appropriate
- Mock external dependencies when possible