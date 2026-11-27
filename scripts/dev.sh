#!/usr/bin/env bash
# Local development launcher: database (docker compose), migrations, backend
# and frontend in one command. Ctrl+C stops the backend and frontend; the
# database container keeps running (`docker compose stop db` to stop it).
#
# Usage: ./scripts/dev.sh
# Needs: Docker, Python 3.14, Node 26. First run installs dependencies.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "No .env found. Create it first:"
  echo "  cp .env.example .env   # then set POSTGRES_PASSWORD (and the same password in DATABASE_URL)"
  exit 1
fi
if grep -q '^POSTGRES_PASSWORD=change_me' .env; then
  echo "warning: POSTGRES_PASSWORD is still 'change_me' in .env" >&2
fi

echo "==> database"
docker compose up -d --wait db

echo "==> backend dependencies"
if [ ! -x backend/.venv/bin/python ]; then
  python3.14 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements-dev.txt
  # Chromium for application automation (Phase 8); a no-op once installed.
  backend/.venv/bin/python -m playwright install chromium
fi
# shellcheck disable=SC1091
. backend/.venv/bin/activate

echo "==> migrations"
./scripts/init_db.sh

echo "==> frontend dependencies"
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm ci)
fi

PIDS=()
cleanup() {
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd backend && python -m app) &
PIDS+=($!)
(cd frontend && npm run dev) &
PIDS+=($!)

echo
echo "  App:      http://localhost:3000"
echo "  API docs: http://127.0.0.1:8000/api/v1/docs"
echo "  Ctrl+C to stop."
wait -n "${PIDS[@]}"
