#!/bin/bash
#
# Start QuickBBS Background Task Worker
#
# QuickBBS uses Django's background task system for work that should happen
# outside the web request cycle:
#
#   - generate_missing_thumbnails: Generates thumbnails for files that don't
#     have them yet. Enqueued automatically when a gallery page loads and
#     missing thumbnails are detected.
#
#   - daily_cleanup_finished_jobs: Periodic task that runs at midnight to
#     purge completed task records from the database.
#
# This script runs the task worker using django-dbtasks (the default backend).
# Any django-tasks compatible backend can be substituted via settings.py.
#
# Usage:
#   ./start_task_worker.sh
#
# Requirements:
#   - django-dbtasks installed (included in project dependencies)
#   - Database migrations applied (python manage.py migrate)
#
# To run in the background:
#   nohup ./start_task_worker.sh &> logs/task_worker.log &
#

# Change to the quickbbs directory (where manage.py is)
cd "$(dirname "$0")"

# Worker configuration
NUMBER_OF_WORKERS=3  # Number of concurrent worker threads

echo "Starting QuickBBS Task Worker"
echo "============================="
echo "Workers:  $NUMBER_OF_WORKERS"
echo "Backend:  django-dbtasks (DatabaseBackend)"
echo ""
echo "Tasks handled:"
echo "  - generate_missing_thumbnails (on-demand)"
echo "  - daily_cleanup_finished_jobs (daily at midnight)"
echo ""

# Start the task worker
# -w sets number of concurrent worker threads
python manage.py taskrunner -w "$NUMBER_OF_WORKERS"

echo ""
echo "Task worker has exited."
