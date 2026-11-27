#!/usr/bin/env bash
# Run database migrations from the host against the docker-compose Postgres.
# Usage: ./scripts/init_db.sh [alembic args]   (default: upgrade head)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$ROOT/.env" ]; then
  set -a; . "$ROOT/.env"; set +a
fi

# Older .env files used the docker hostname "db"; from the host it is localhost.
export DATABASE_URL="${DATABASE_URL//@db:/@localhost:}"

cd "$ROOT/backend"
if [ "$#" -eq 0 ]; then
  alembic upgrade head
else
  alembic "$@"
fi
