#!/bin/sh
# Container entrypoint: apply database migrations, then run the command
# (default: the API server). MIGRATE_ON_START=false skips migrations.
set -eu
if [ "${MIGRATE_ON_START:-true}" = "true" ]; then
  echo "applying database migrations"
  alembic upgrade head
fi
exec "$@"
