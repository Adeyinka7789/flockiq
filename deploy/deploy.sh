#!/bin/bash
set -euo pipefail

PROJECT_DIR="/www/wwwroot/flockiq"
VENV="$PROJECT_DIR/venv/bin"
LOG_DIR="$PROJECT_DIR/logs"

echo "=== FlockIQ Deploy $(date) ==="

cd $PROJECT_DIR

# Pull latest code
echo "Pulling latest code..."
git pull origin main

# Activate venv
source $VENV/activate

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements/production.txt --quiet

# Run migrations (check first, migrate if needed)
echo "Checking migrations..."
python manage.py migrate --check 2>/dev/null || {
    echo "Running migrations..."
    python manage.py migrate --noinput
}

# Verify RLS policies are applied on all tenant tables
echo "Verifying RLS policies..."
python manage.py verify_rls_policies

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput --quiet

# Ensure log directory exists
mkdir -p $LOG_DIR

# Restart services
echo "Restarting services..."
supervisorctl restart flockiq-gunicorn flockiq-celery flockiq-beat

echo "=== Deploy complete ==="

# Health check
sleep 5
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/api/health/)
if [ "$HTTP_STATUS" = "200" ]; then
    echo "Health check passed (HTTP $HTTP_STATUS)"
else
    echo "Health check FAILED (HTTP $HTTP_STATUS)"
    echo "Check logs: tail -f $LOG_DIR/gunicorn-error.log"
    exit 1
fi
