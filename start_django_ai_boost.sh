#!/bin/bash
# Django AI Boost MCP Server Startup Script
# This script starts the django-ai-boost MCP server for QuickBBS

set -e

# Navigate to the QuickBBS source directory
cd "$(dirname "$0")/quickbbs"

# Set Django settings module
export DJANGO_SETTINGS_MODULE="quickbbs.settings"
export PYTHONPATH="$(pwd)"

# Get the django-ai-boost CLI path from the active Poetry virtualenv
DJANGO_AI_BOOST="$(poetry run which django-ai-boost)"

echo "Starting django-ai-boost MCP server..."
echo "Django Settings: $DJANGO_SETTINGS_MODULE"
echo "Python Path: $PYTHONPATH"
echo ""

# Start the server with stdio transport (default)
# Pass additional arguments like --transport sse --host 127.0.0.1 --port 8000
$DJANGO_AI_BOOST --settings quickbbs.settings "$@"
