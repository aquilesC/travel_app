#!/bin/sh
# Only the web container prepares the database and static files
# (RUN_MIGRATIONS=1); worker and scheduler just wait for it and start.
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
    python manage.py createcachetable
    python manage.py collectstatic --noinput
fi

exec "$@"
