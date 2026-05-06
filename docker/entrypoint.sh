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
# Use the config file to manage the logging and IP logic
echo "Launching Gunicorn production server..."
exec gunicorn -c /app/docker/gunicorn.conf.py run:app