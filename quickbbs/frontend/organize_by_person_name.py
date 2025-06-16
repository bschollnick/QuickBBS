import os
import shutil
import re
from pathlib import Path

def extract_person_name(filename):
    """
    Extract person's name from filename.
    Handles various patterns including descriptive text, ages, dates, and group photos.
    """
    # Remove file extension
    name_part = os.path.splitext(filename)[0]
    
    # Handle HTML entities
    name_part = name_part.replace('&amp;', '&')
    
    # For group photos, take the first name mentioned
    if ',' in name_part or ' & ' in name_part or ' and ' in name_part:
        # Split on various separators and take the first name
        for separator in [',', ' & ', ' and ']:
            if separator in name_part:
                name_part = name_part.split(separator)[0].strip()
                break
    
    # Remove common prefixes
    name_part = re.sub(r'^(Miss|Mr|Mrs|Ms|Dr|Classic|Young|Cute|Happy|Gorgeous|Goddess|English\s+actress|Indian\s+Bollywood\s+Actress|Favourite\s+redhead|singer|beautiful)\s+', '', name_part, flags=re.IGNORECASE)
    
    # Remove age patterns like "46 year-old", "at 45", "Turns 50 Today", etc.
    name_part = re.sub(r'\b\d{1,2}\s+year[s]?-old\b', '', name_part, flags=re.IGNORECASE)
    name_part = re.sub(r'\bat\s+\d{1,2}\b', '', name_part, flags=re.IGNORECASE)
    name_part = re.sub(r'\bTurns?\s+\d{1,2}\s+(Today|today)!?\b', '', name_part, flags=re.IGNORECASE)
    name_part = re.sub(r'\bis\s+\d{1,2}\b', '', name_part, flags=re.IGNORECASE)
    
    # Remove years and dates
    name_part = re.sub(r'\b(19|20)\d{2}\b', '', name_part)  # Remove years
    name_part = re.sub(r'\b(in|from)\s+(19|20)\d{2}\b', '', name_part, flags=re.IGNORECASE)
    name_part = re.sub(r'\blast\s+year\s+\((19|20)\d{2}\)', '', name_part, flags=re.IGNORECASE)
    
    # Remove birthday wishes and similar phrases
    name_part = re.sub(r'^Happy\s+(Birthday|30th\s+Birthday|birthday)\s+(to\s+)?', '', name_part, flags=re.IGNORECASE)
    
    # Remove descriptive phrases and terms
    descriptive_patterns = [
        r'\b(VS|Victoria\'s\s+Secret)\s+model\b',
        r'\bone\s+of\s+Canada\'s\s+top\s+female\s+chess\s+players\.?\b',
        r'\bfrom\s+Ash\s+vs\s+Evil\s+Dead\b',
        r'\bKatana\s+from\s+Suicide\s+Squad\b',
        r'\ba\.k\.a\.?\s+[^,]+',
        r'\bAKA\s+[^,]+',
        r'\bOtherwise\s+known\s+as\s+[^,]+',
        r'\bBritish\s+TV\s+presenter\s+and\s+singer\b',
        r'\bIranian\s+actress\b',
        r'\bages\s+like\s+a\s+wine\b',
        r'\bknows\s+exactly\s+what\s+she\'s\s+doing\b',
        r'\bhas\s+never\s+looked\s+better\s+IMO\b',
        r'\bis\s+truly\s+beautiful\b',
        r'\bis\s+perfection\b',
        r'\bis\s+Mighty\s+Fine!\b',
        r'\bWhat\s+A\s+Stunner\b',
        r'\balways\s+looks\s+amazing\s+on\s+talk\s+shows\s+\(MIC\)\b',
        r'\bstrolling\b',
        r'\bBackless\b',
        r'\bsexy\s+in\s+Red\b',
        r'\bRed\s+Stripped\s+Dress\b',
        r'\bFloral\s+Dress\b',
        r'\bRed\s+Dress\b',
        r'\bin\s+black\b',
        r'\bin\s+Venice\b',
        r'\bin\s+a\s+retro\s+car\b',
        r'\bLeg\s+Show\b',
        r'\bas\s+a\s+brunette\b',
        r'\b\(blonde\)\b',
        r'\blooking\s+adorable\b',
        r'\blooking\s+over\s+her\s+shoulder.*\b',
        r'\bwith\s+No\s+flashy\s+photography.*\b',
        r'\b\[.*\]\b',  # Remove text in square brackets
        r'\b\(.*\)\b',  # Remove text in parentheses
        r'\.+$',  # Remove trailing dots
        r'\?.*$',  # Remove question marks and everything after
        r'!.*$'   # Remove exclamation marks and everything after (but not birthday ones handled above)
    ]
    
    for pattern in descriptive_patterns:
        name_part = re.sub(pattern, '', name_part, flags=re.IGNORECASE)
    
    # Remove "Universe" prefix (for Miss Universe entries)
    name_part = re.sub(r'^Universe\s+', '', name_part, flags=re.IGNORECASE)
    
    # Remove single quotes around names
    name_part = re.sub(r"^'([^']+)'$", r'\1', name_part)
    
    # Clean up extra spaces and special characters
    name_part = re.sub(r'\s+', ' ', name_part)  # Multiple spaces to single space
    name_part = name_part.strip(' .,!?-_')
    
    # Handle special cases where name might be empty after cleaning
    if not name_part or len(name_part) < 2:
        # Return original filename without extension as fallback
        return os.path.splitext(filename)[0]
    
    return name_part

def create_safe_directory_name(name):
    """
    Create a safe directory name from person's name.
    Replace spaces with underscores and remove/replace problematic characters.
    """
    # Replace spaces with underscores
    safe_name = name.replace(' ', '_')
    
    # Replace problematic characters with underscores
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', safe_name)
    
    # Remove leading/trailing dots and underscores
    safe_name = safe_name.strip('._').split("—")[0].rstrip("_").rstrip("_")
    
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
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
    image_files = []
    
    for ext in image_extensions:
        image_files.extend(source_path.glob(f'*{ext}'))
        image_files.extend(source_path.glob(f'*{ext.upper()}'))
    
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
            except Exception as e:
                print(f"Error moving '{filename}': {e}")
    
    # Print organization summary
    print("\n" + "="*50)
    print("ORGANIZATION SUMMARY")
    print("="*50)
    
    for dir_name, files in sorted(organization_plan.items()):
        print(f"\n{dir_name}/")
        for file in sorted(files):
            print(f"  └── {file}")

def main():
    """
    Main function to run the file organizer.
    """
    print("File Organizer by Person Name")
    print("="*40)
    
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
    
    if response in ['y', 'yes']:
        organize_files(source_dir, create_subdirs=True)
        print("\nFiles have been organized!")
    else:
        print("\nShowing organization plan only (no files will be moved):")
        organize_files(source_dir, create_subdirs=False)

if __name__ == "__main__":
    main()