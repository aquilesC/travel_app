#!/bin/sh
# Runs on every container start: apply migrations and collect static files,
# then hand over to the CMD (gunicorn by default).
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
