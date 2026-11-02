#!/usr/bin/env bash
# Render build: Python deps, frontend (once it exists), static files, migrations.
set -o errexit

pip install -r backend/requirements.txt

if [ -f frontend/package.json ]; then
  (cd frontend && npm ci && npm run build)
fi

cd backend
python manage.py collectstatic --no-input
python manage.py migrate --no-input
# Demo deployments seed the demo family once; later deploys keep its data.
if [ "${DEMO_MODE:-false}" = "true" ]; then
  python manage.py seed_demo --if-missing
fi
