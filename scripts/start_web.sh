#!/usr/bin/env bash
# Apply schema changes before starting the web server.  This must run before
# Gunicorn starts, otherwise Render's first health check can reach an empty DB.
set -euo pipefail

flask --app run:app db upgrade

exec gunicorn \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  run:app
