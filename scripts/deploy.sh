#!/bin/bash
set -e

echo "=== FlockIQ Deploy Script ==="

echo "→ Pulling latest code..."
git pull origin main

echo "→ Installing dependencies..."
pip install -r requirements/production.txt

echo "→ Running migrations..."
python manage.py migrate --noinput

echo "→ Collecting static files..."
python manage.py collectstatic --noinput

echo "→ Seeding Celery beat tasks..."
python manage.py seed_celery_beat

echo "→ Seeding billing plans..."
python manage.py seed_billing_plans

echo "→ Seeding hatcheries..."
python manage.py seed_hatcheries

echo "→ Running system checks..."
python manage.py check --deploy

echo "→ Restarting services..."
sudo systemctl restart flockiq-gunicorn
sudo systemctl restart flockiq-celery-worker
sudo systemctl restart flockiq-celery-beat

echo "=== Deploy complete ==="
