#!/bin/sh

# 1. Wait for Postgres to be ready
echo "Waiting for database..."
while ! nc -z $DB_HOST $DB_PORT; do
  sleep 0.5
done
echo "PostgreSQL started"

# 2. Apply Database Migrations (schema sync)
echo "Applying database migrations..."
flask db upgrade

# 3. Seed System Records
echo "Seeding system records..."
flask seed-db

# 4. Start Gunicorn (Production Server)
# Binding to 0.0.0.0 is mandatory for Docker
echo "Launching Gunicorn production server..."
exec gunicorn --bind 0.0.0.0:5001 \
              --access-logfile /app/data/logs/system.log \
              --error-logfile /app/data/logs/system.log \
              --log-level info \
              --capture-output \
              run:app