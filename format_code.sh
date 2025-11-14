#!/bin/bash
# format_code.sh - Reliable wrapper for black and isort
# Usage: ./format_code.sh <file_or_directory>
#
# This script ensures tools run from the correct directory and with proper paths

set -e  # Exit on error

# Get the directory where this script lives (project root)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"
QUICKBBS_DIR="$PROJECT_ROOT/quickbbs"

# Change to quickbbs directory (where manage.py lives)
cd "$QUICKBBS_DIR" || exit 1

echo "Working directory: $(pwd)"
echo "Formatting: $*"
echo ""

# Run black and isort on provided arguments
if [ $# -eq 0 ]; then
    echo "Usage: $0 <file_or_directory> [additional files...]"
    echo "Example: $0 frontend/utilities.py"
    echo "Example: $0 quickbbs/frontend/managers.py"
    exit 1
fi

# Normalize paths - strip "quickbbs/" prefix if present since we're already in that directory
NORMALIZED_ARGS=()
for arg in "$@"; do
    # Remove leading "quickbbs/" if present
    normalized="${arg#quickbbs/}"

    # Check if the normalized path exists relative to current directory
    if [ -e "$normalized" ]; then
        NORMALIZED_ARGS+=("$normalized")
        echo "  → $normalized"
    else
        # If it doesn't exist, try the original path (might be absolute)
        if [ -e "$arg" ]; then
            NORMALIZED_ARGS+=("$arg")
            echo "  → $arg"
        else
            echo "Warning: Cannot find $arg or $normalized - trying anyway"
            NORMALIZED_ARGS+=("$normalized")
        fi
    fi
done

echo ""

# Run black
echo "Running black..."
black "${NORMALIZED_ARGS[@]}" || { echo "Black failed"; exit 1; }

# Run isort
echo "Running isort..."
isort "${NORMALIZED_ARGS[@]}" || { echo "Isort failed"; exit 1; }

echo ""
echo "✅ Formatting complete!"
