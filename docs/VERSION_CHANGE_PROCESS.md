# Version Change Process - QuickBBS Gallery

## Overview

This document outlines the complete process for updating version numbers in the QuickBBS Gallery project. This process MUST be followed whenever a new version is released.

---

## Version Number Locations

### Primary Version Numbers (MUST UPDATE)

1. **pyproject.toml** (Line 3)
   ```toml
   version = "3.75.0"
   ```
   - Format: Major.Minor.Patch (e.g., "3.75.0")
   - Location: `/Volumes/C-8TB/gallery/quickbbs/pyproject.toml`

2. **quickbbs/quickbbs/__init__.py** (Line 4)
   ```python
   __version__ = "3.75"
   ```
   - Format: Major.Minor (e.g., "3.75")
   - Location: `/Volumes/C-8TB/gallery/quickbbs/quickbbs/quickbbs/__init__.py`

### Sub-Application Versions (OPTIONAL - Ask for clarification)

3. **quickbbs/frontend/__init__.py** (Line 7)
   ```python
   __version__ = "2.9"
   ```
   - Format: Major.Minor (e.g., "2.9")
   - Location: `/Volumes/C-8TB/gallery/quickbbs/quickbbs/frontend/__init__.py`
   - **Status**: Currently versioned independently from main project
   - **Action**: Ask user if this should be synchronized with main version

4. **quickbbs/cache_watcher/__init__.py**
   - **Status**: Currently has NO version number
   - **Action**: Ask user if version should be added

5. **quickbbs/filetypes/__init__.py**
   - **Status**: Empty file - NO version number
   - **Action**: Ask user if version should be added

6. **quickbbs/thumbnails/__init__.py**
   - **Status**: Empty file - NO version number
   - **Action**: Ask user if version should be added

7. **quickbbs/user_preferences/__init__.py**
   - **Status**: Empty file - NO version number
   - **Action**: Ask user if version should be added

---

## Version Change Workflow

### Step 1: Clarify Version Scope

Before proceeding, ask the user:

1. **New version number**: What is the new version number? (e.g., "3.76.0")

2. **Sub-app synchronization**: Should sub-application versions be synchronized?
   - If YES: Update all sub-apps to match main version
   - If NO: Keep existing sub-app versions or skip empty ones

3. **Unknown sub-apps**: Are there any additional sub-applications that need versioning?

### Step 2: Compile Git Change History

Extract all commits between the last version tag and HEAD:

```bash
# Find the last version tag
git tag --sort=-version:refname | head -1

# Get commits since last version
git log --oneline [last-version-tag]..HEAD

# Get detailed commit messages
git log --pretty=format:"%h - %s%n%b" [last-version-tag]..HEAD
```

### Step 3: Transform Git History into Version History

Review the raw git commit history and transform it into user-friendly version history notes following the format in `Docs/Version History.md`.

**Format Guidelines** (from existing Version History.md):

1. **Major Enhancements Section**
   - Group related changes into categories
   - Use descriptive headers with bold emphasis
   - Include sub-bullets for specific features
   - Provide technical details where relevant

2. **Categories to Consider**
   - Performance improvements
   - New features
   - UI/UX improvements
   - Database optimizations
   - Code quality improvements
   - Bug fixes
   - Infrastructure changes

3. **Writing Style**
   - Use past tense for completed work
   - Be specific but concise
   - Include technical terms when relevant (e.g., "Django ORM", "PostgreSQL", "HTMX")
   - Reference specific files or modules when helpful
   - Explain the "why" not just the "what"

**Example Transformation**:

```
RAW GIT COMMIT:
"fix: Resolved issue with text file encoding detection"

TRANSFORMED VERSION HISTORY:
**Bug Fixes:**
- Fixed text file encoding detection regression that caused UTF-8 files to display incorrectly
```

### Step 4: Draft Version History Entry

Create a new version section in the style of existing entries. Example structure:

**IMPORTANT: Always include the specific release date in the version header!**

```markdown
## Version X.Y.Z (Month Day, Year)
**Technology**: Django 6.0 Alpha, HTMX, [Key Technologies]

Version X.Y.Z builds on the vX.Y foundation with [brief summary of major changes].

### Major Enhancements:

**[Category 1]:**
- [Enhancement 1]: [Description]
- [Enhancement 2]: [Description]

**[Category 2]:**
- [Enhancement 1]: [Description]

**[Category N]:**
- [Enhancement 1]: [Description]

---
```

**Release Date Format Examples:**
- Single date: `## Version 3.80 (October 24, 2025)`
- Date range: `## Version 2.0 (April 25, 2018 - 2022)`
- Month/Year range: `## Version 3.0 (December 2022 - March 2024)`
- Year only (if specific date unknown): `## Version 3.5 (2025)`

### Step 5: Get User Approval

Present the following to the user for approval:

1. **Version numbers to be updated**:
   - pyproject.toml: X.Y.Z
   - quickbbs/__init__.py: X.Y
   - [List any sub-apps being updated]

2. **Draft version history entry**: Show the complete formatted entry

3. **Request confirmation**: Ask user to review and approve or request changes

### Step 6: Update Files

After approval, update the version numbers in all specified files:

1. Update `pyproject.toml` (line 3)
2. Update `quickbbs/quickbbs/__init__.py` (line 4)
3. Update any sub-app `__init__.py` files as agreed upon

### Step 7: Append to Version History.md

Append the approved version history entry to `Docs/Version History.md`:

1. Insert the new version section BEFORE the "Performance Evolution Summary" section
2. Ensure proper markdown formatting
3. Verify table formatting if any tables were added
4. Add a horizontal rule (`---`) after the new version section
5. **CRITICAL: Update the Performance Evolution Summary table** to include the new version with its release date:
   ```markdown
   | Version | Release Date        | Storage                    | Thumbnails     | Monitoring             |
   | v3.XX   | Month Day, Year     | PostgreSQL                 | Database BLOBs | Watchdog + HTMX + ASGI |
   ```

### Step 8: Completion - DO NOT COMMIT

**CRITICAL: Claude should NOT stage files or create commits.**

After completing all version number updates and Version History.md changes:

1. **Report completion** to the user with a summary of all changes made
2. **List all modified files** so the user knows what to review
3. **DO NOT** run `git add` commands
4. **DO NOT** run `git commit` commands
5. **DO NOT** run `git push` commands

The user will review all changes and commit them through VS Code or their preferred git tool.

**Summary to provide:**
```
✅ Version Update Complete

Files Modified:
- pyproject.toml: 3.X.Y
- quickbbs/__init__.py: 3.X
- quickbbs/frontend/__init__.py: 3.X
- quickbbs/cache_watcher/__init__.py: 3.X (NEW/UPDATED)
- quickbbs/filetypes/__init__.py: 3.X (NEW/UPDATED)
- quickbbs/thumbnails/__init__.py: 3.X (NEW/UPDATED)
- quickbbs/user_preferences/__init__.py: 3.X (NEW/UPDATED)
- Docs/Version History.md: Added v3.X entry with release date

Please review the changes and commit when ready.
```

---

## Quick Reference Checklist

- [ ] Clarify new version number with user
- [ ] Ask about sub-app version synchronization
- [ ] Identify any unknown sub-apps that need versioning
- [ ] Extract git commit history since last version
- [ ] Transform commits into user-friendly version history
- [ ] Draft version history entry following existing format
- [ ] **CRITICAL: Include release date in version header (Month Day, Year)**
- [ ] Get user approval for:
  - [ ] Version numbers
  - [ ] Version history content
- [ ] Update pyproject.toml
- [ ] Update quickbbs/quickbbs/__init__.py
- [ ] Update sub-app __init__.py files (if applicable)
- [ ] Append to Docs/Version History.md
- [ ] **CRITICAL: Update Performance Evolution Summary table with new version and release date**
- [ ] **Report completion to user with file summary**
- [ ] **DO NOT stage or commit files - user will review and commit via VS Code**

---

## Important Notes

1. **Version Format Differences**:
   - `pyproject.toml` uses three-part versioning: "X.Y.Z" (e.g., "3.75.0")
   - `__init__.py` files use two-part versioning: "X.Y" (e.g., "3.75")

2. **Sub-App Versioning**:
   - Sub-apps may have independent version numbers
   - Always clarify with the user whether to synchronize or maintain independence
   - Document any version synchronization decisions

3. **Git History Processing**:
   - Focus on user-visible changes
   - Combine related commits into single bullet points
   - Omit trivial commits (typo fixes, minor refactoring without impact)
   - Group commits by category for better organization

4. **Version History Style**:
   - Maintain consistency with existing entries
   - Use the same markdown formatting and structure
   - Include technical depth appropriate for developer audience
   - Balance between comprehensive and concise

5. **Always Get Approval**:
   - Never append to Version History.md without explicit user approval
   - Show the complete formatted entry before making changes
   - Allow user to request revisions

6. **Git Operations - DO NOT COMMIT**:
   - **CRITICAL**: Claude should NEVER stage files (`git add`) or create commits (`git commit`)
   - Claude's role is to make file changes only
   - The user will review all changes and commit them through VS Code or their preferred git tool
   - After completing all changes, provide a summary of modified files and stop
   - Do not attempt to push changes to remote repositories

---

## Example Session

**Claude**: I need to update the version number. What should the new version be?

**User**: 3.76.0

**Claude**: Should I synchronize the sub-application versions?
- frontend (currently 2.9)
- cache_watcher (no version)
- filetypes (no version)
- thumbnails (no version)
- user_preferences (no version)

**User**: Yes, update frontend to 3.76, but leave the others without versions.

**Claude**: [Compiles git history and presents transformed version history entry]

Here's the draft version history entry:

```markdown
## Version 3.76.0 (2025)
[... formatted entry ...]
```

Should I proceed with updating the version numbers and appending this to Version History.md?

**User**: Yes, approved.

**Claude**: [Updates files]

✅ Version Update Complete

Files Modified:
- pyproject.toml: 3.76.0
- quickbbs/__init__.py: 3.76
- quickbbs/frontend/__init__.py: 3.76
- Docs/Version History.md: Added v3.76.0 entry with release date (October 24, 2025)

Please review the changes and commit when ready.

---

Last Updated: 2025-10-24
