from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

# Pre-compiled regex patterns for name extraction
_PREFIX_RE = re.compile(
    r"^(Miss|Mr|Mrs|Ms|Dr|Classic|Young|Cute|Happy|Gorgeous|Goddess|English\s+actress|Indian\s+Bollywood\s+Actress|Favourite\s+redhead|singer|beautiful)\s+",
    re.IGNORECASE,
)
_AGE_YEARS_OLD_RE = re.compile(r"\b\d{1,2}\s+year[s]?-old\b", re.IGNORECASE)
_AGE_AT_RE = re.compile(r"\bat\s+\d{1,2}\b", re.IGNORECASE)
_AGE_TURNS_RE = re.compile(r"\bTurns?\s+\d{1,2}\s+(Today|today)!?\b", re.IGNORECASE)
_AGE_IS_RE = re.compile(r"\bis\s+\d{1,2}\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_IN_FROM_YEAR_RE = re.compile(r"\b(in|from)\s+(19|20)\d{2}\b", re.IGNORECASE)
_LAST_YEAR_RE = re.compile(r"\blast\s+year\s+\((19|20)\d{2}\)", re.IGNORECASE)
_BIRTHDAY_RE = re.compile(r"^Happy\s+(Birthday|30th\s+Birthday|birthday)\s+(to\s+)?", re.IGNORECASE)
_UNIVERSE_RE = re.compile(r"^Universe\s+", re.IGNORECASE)
_QUOTED_NAME_RE = re.compile(r"^'([^']+)'$")
_MULTI_SPACE_RE = re.compile(r"\s+")
_UNSAFE_CHARS_RE = re.compile(r'[<>:"/\\|?*]')

# Pre-compiled descriptive patterns
_DESCRIPTIVE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\b(VS|Victoria\'s\s+Secret)\s+model\b",
        r"\bone\s+of\s+Canada\'s\s+top\s+female\s+chess\s+players\.?\b",
        r"\bfrom\s+Ash\s+vs\s+Evil\s+Dead\b",
        r"\bKatana\s+from\s+Suicide\s+Squad\b",
        r"\ba\.k\.a\.?\s+[^,]+",
        r"\bAKA\s+[^,]+",
        r"\bOtherwise\s+known\s+as\s+[^,]+",
        r"\bBritish\s+TV\s+presenter\s+and\s+singer\b",
        r"\bIranian\s+actress\b",
        r"\bages\s+like\s+a\s+wine\b",
        r"\bknows\s+exactly\s+what\s+she\'s\s+doing\b",
        r"\bhas\s+never\s+looked\s+better\s+IMO\b",
        r"\bis\s+truly\s+beautiful\b",
        r"\bis\s+perfection\b",
        r"\bis\s+Mighty\s+Fine!\b",
        r"\bWhat\s+A\s+Stunner\b",
        r"\balways\s+looks\s+amazing\s+on\s+talk\s+shows\s+\(MIC\)\b",
        r"\bstrolling\b",
        r"\bBackless\b",
        r"\bsexy\s+in\s+Red\b",
        r"\bRed\s+Stripped\s+Dress\b",
        r"\bFloral\s+Dress\b",
        r"\bRed\s+Dress\b",
        r"\bin\s+black\b",
        r"\bin\s+Venice\b",
        r"\bin\s+a\s+retro\s+car\b",
        r"\bLeg\s+Show\b",
        r"\bas\s+a\s+brunette\b",
        r"\b\(blonde\)\b",
        r"\blooking\s+adorable\b",
        r"\blooking\s+over\s+her\s+shoulder.*\b",
        r"\bwith\s+No\s+flashy\s+photography.*\b",
        r"\b\[.*\]\b",
        r"\b\(.*\)\b",
        r"\.+$",
        r"\?.*$",
        r"!.*$",
    ]
]


def extract_person_name(filename: str) -> str:
    """
    Extract person's name from filename.

    Handles various patterns including descriptive text, ages, dates, and group photos.

    Args:
        filename: Original filename

    Returns:
        Extracted person name
    """
    # Remove file extension
    name_part = os.path.splitext(filename)[0]

    # Handle HTML entities
    name_part = name_part.replace("&amp;", "&")

    # For group photos, take the first name mentioned
    if "," in name_part or " & " in name_part or " and " in name_part:
        # Split on various separators and take the first name
        for separator in [",", " & ", " and "]:
            if separator in name_part:
                name_part = name_part.split(separator)[0].strip()
                break

    # Remove common prefixes
    name_part = _PREFIX_RE.sub("", name_part)

    # Remove age patterns like "46 year-old", "at 45", "Turns 50 Today", etc.
    name_part = _AGE_YEARS_OLD_RE.sub("", name_part)
    name_part = _AGE_AT_RE.sub("", name_part)
    name_part = _AGE_TURNS_RE.sub("", name_part)
    name_part = _AGE_IS_RE.sub("", name_part)

    # Remove years and dates
    name_part = _YEAR_RE.sub("", name_part)
    name_part = _IN_FROM_YEAR_RE.sub("", name_part)
    name_part = _LAST_YEAR_RE.sub("", name_part)

    # Remove birthday wishes and similar phrases
    name_part = _BIRTHDAY_RE.sub("", name_part)

    # Remove descriptive phrases and terms
    for pattern in _DESCRIPTIVE_PATTERNS:
        name_part = pattern.sub("", name_part)

    # Remove "Universe" prefix (for Miss Universe entries)
    name_part = _UNIVERSE_RE.sub("", name_part)

    # Remove single quotes around names
    name_part = _QUOTED_NAME_RE.sub(r"\1", name_part)

    # Clean up extra spaces and special characters
    name_part = _MULTI_SPACE_RE.sub(" ", name_part)
    name_part = name_part.strip(" .,!?-_")

    # Handle special cases where name might be empty after cleaning
    if not name_part or len(name_part) < 2:
        # Return original filename without extension as fallback
        return os.path.splitext(filename)[0]

    return name_part


def create_safe_directory_name(name: str) -> str:
    """
    Create a safe directory name from person's name.

    Replace spaces with underscores and remove/replace problematic characters.

    Args:
        name: Person's name

    Returns:
        Safe directory name
    """
    # Replace spaces with underscores
    safe_name = name.replace(" ", "_")

    # Replace problematic characters with underscores
    safe_name = _UNSAFE_CHARS_RE.sub("_", safe_name)

    # Remove leading/trailing dots and underscores
    safe_name = safe_name.strip("._").split("—")[0].rstrip("_").rstrip("_")

    return safe_name


def organize_files(source_directory, create_subdirs=True):
    """
    Organize files into directories based on person names.

    Args:
        source_directory (str): Path to directory containing the files
        create_subdirs (bool): Whether to actually create directories and move files
    """

    source_path = Path(source_directory)

    # Get all image files in the directory
    image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
    image_files = []

    for ext in image_extensions:
        image_files.extend(source_path.glob(f"*{ext}"))
        image_files.extend(source_path.glob(f"*{ext.upper()}"))

    # Dictionary to track what files go where
    organization_plan = {}

    for file_path in image_files:
        filename = file_path.name

        # Extract person name
        person_name = extract_person_name(filename)

        if not person_name:
            print(f"Warning: Could not extract name from '{filename}'")
            continue

        # Create safe directory name
        dir_name = create_safe_directory_name(person_name)
        target_dir = source_path / dir_name

        # Add to organization plan
        if dir_name not in organization_plan:
            organization_plan[dir_name] = []
        organization_plan[dir_name].append(filename)

        if create_subdirs:
            # Create directory if it doesn't exist
            target_dir.mkdir(exist_ok=True)

            # Move file to target directory
            target_file = target_dir / filename
            try:
                shutil.move(str(file_path), str(target_file))
                print(f"Moved '{filename}' to '{dir_name}/' directory")
            except (OSError, shutil.Error) as e:
                print(f"Error moving '{filename}': {e}")

    # Print organization summary
    print("\n" + "=" * 50)
    print("ORGANIZATION SUMMARY")
    print("=" * 50)

    for dir_name, files in sorted(organization_plan.items()):
        print(f"\n{dir_name}/")
        for file in sorted(files):
            print(f"  └── {file}")


def main():
    """
    Main function to run the file organizer.
    """
    print("File Organizer by Person Name")
    print("=" * 40)

    # Get source directory from user
    source_dir = input("Enter the path to the directory containing your files: ").strip()

    if not source_dir:
        source_dir = "."  # Current directory if nothing entered

    if not os.path.exists(source_dir):
        print(f"Error: Directory '{source_dir}' does not exist!")
        return

    print(f"\nAnalyzing files in: {os.path.abspath(source_dir)}")

    # Ask user if they want to proceed with moving files
    response = input("\nDo you want to actually move the files? (y/n): ").strip().lower()

    if response in ["y", "yes"]:
        organize_files(source_dir, create_subdirs=True)
        print("\nFiles have been organized!")
    else:
        print("\nShowing organization plan only (no files will be moved):")
        organize_files(source_dir, create_subdirs=False)


if __name__ == "__main__":
    main()
