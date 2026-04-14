#!/bin/sh

# 1. Wait for Postgres to be ready
echo "Waiting for database..."
while ! nc -z $DB_HOST $DB_PORT; do
  sleep 0.1
done
echo "PostgreSQL started"

# 2. Apply migrations (Fortress schema sync)
flask db upgrade

# 3. Smart Seed (Handled in Step 3.2)
flask seed-db

# 4. Start Gunicorn (Production Server)
# Binding to 0.0.0.0 is mandatory for Docker
exec gunicorn --bind 0.0.0.0:5001 run:app