#!/bin/sh
set -eu

if [ "${RUN_STARTUP_MIGRATIONS:-true}" = "true" ]; then
  python manage.py migrate --noinput
  if [ -n "${BOOTSTRAP_ADMIN_PASSWORD:-}" ]; then
    python manage.py bootstrap_admin
  fi
  if [ "${SEED_INITIAL_REFERENCE:-true}" = "true" ]; then
    python manage.py seed_initial_reference
  fi
  python manage.py collectstatic --noinput
fi

exec "$@"
