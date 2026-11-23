#!/usr/bin/env bash
# Apply schema changes before starting the web server.  This must run before
# Gunicorn starts, otherwise Render's first health check can reach an empty DB.
set -euo pipefail

flask --app run:app db upgrade

# Seed the public demo farm the first time it is enabled. A failure must not
# keep the real app down, so it only logs; POST /api/auth/demo then returns 503.
if [ "${DEMO_ENABLED:-False}" = "True" ]; then
  flask --app run:app demo seed --if-missing || echo "WARNING: demo seed failed; the demo stays unavailable." >&2
fi

exec gunicorn \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  run:app
