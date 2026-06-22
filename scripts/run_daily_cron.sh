#!/bin/bash
# AgriPlot Connect - Master Daily Cron Script
# This script should be added to the server's crontab to run daily (e.g., at midnight).
# It replaces the need for Celery scheduled tasks.

# Exit immediately if a command exits with a non-zero status
set -e

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$DIR")"

echo "=================================================="
echo "Starting AgriPlot Daily Cron Jobs at $(date)"
echo "Project Root: $PROJECT_ROOT"
echo "=================================================="

cd "$PROJECT_ROOT"

# Activate virtual environment if it exists
if [ -f "env/bin/activate" ]; then
    echo "Activating virtual environment..."
    source env/bin/activate
else
    echo "Warning: Virtual environment not found at env/bin/activate. Using system python."
fi

echo "--- 1. Running Verification SLA Tasks ---"
python manage.py run_sla_tasks

echo "--- 2. Processing Lease Lifecycle ---"
python manage.py process_lease_lifecycle

echo "=================================================="
echo "Daily Cron Jobs completed successfully at $(date)"
echo "=================================================="
