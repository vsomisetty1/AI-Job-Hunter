#!/usr/bin/env bash
# Local development launcher: database (docker compose), migrations, backend
# and frontend in one command. Ctrl+C stops the backend and frontend; the
# database container keeps running (`docker compose stop db` to stop it).
#
# Usage: ./scripts/dev.sh
# Needs: Docker, Python 3.14, Node 26 (see LOCAL_SETUP.md).
# Every run checks the dependencies and installs only what changed or is
# missing, so an interrupted first run is completed by the next one.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

die() { echo "error: $*" >&2; exit 1; }

if [ ! -f .env ]; then
  echo "No .env found. Create it first:"
  echo "  cp .env.example .env   # then set POSTGRES_PASSWORD (and the same password in DATABASE_URL)"
  exit 1
fi
if grep -q '^POSTGRES_PASSWORD=change_me' .env; then
  echo "warning: POSTGRES_PASSWORD is still 'change_me' in .env" >&2
fi

command -v docker >/dev/null || die "Docker is not installed (LOCAL_SETUP.md, step 2)"
docker info >/dev/null 2>&1 || die "Docker is not running: start Docker Desktop (or the docker service)"
command -v python3.14 >/dev/null || die "python3.14 not found on PATH (LOCAL_SETUP.md, step 2)"
command -v node >/dev/null || die "Node.js not found on PATH (LOCAL_SETUP.md, step 2)"
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge 26 ] || die "Node $node_major found; Node 26 or newer is required"

sha() {  # sha <file>: GNU coreutils or macOS
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

echo "==> database"
docker compose up -d --wait db

echo "==> backend dependencies"
[ -x backend/.venv/bin/python ] || python3.14 -m venv backend/.venv
stamp=backend/.venv/.requirements.sha256
want="$(sha backend/requirements.txt) $(sha backend/requirements-dev.txt)"
if [ "$(cat "$stamp" 2>/dev/null)" != "$want" ]; then
  backend/.venv/bin/pip install -q -r backend/requirements-dev.txt
  echo "$want" > "$stamp"
fi
# Chromium for application automation; a quick no-op once installed. A failed
# download does not stop the app: everything but automation works without it.
if ! grep -qE '^AUTOMATION_BROWSER_PATH=.+' .env; then
  backend/.venv/bin/python -m playwright install chromium \
    || echo "warning: Chromium download failed; application automation will not work until 'backend/.venv/bin/python -m playwright install chromium' succeeds" >&2
fi
# shellcheck disable=SC1091
. backend/.venv/bin/activate

echo "==> migrations"
./scripts/init_db.sh

echo "==> frontend dependencies"
lock_stamp=frontend/node_modules/.package-lock.sha256
if [ "$(cat "$lock_stamp" 2>/dev/null)" != "$(sha frontend/package-lock.json)" ]; then
  (cd frontend && npm ci)
  sha frontend/package-lock.json > "$lock_stamp"
fi

PIDS=()
cleanup() {
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# exec: the recorded PIDs are the servers themselves, so stopping them stops everything.
(cd backend && exec python -m app) &
PIDS+=($!)
(cd frontend && exec ./node_modules/.bin/next dev -p 3000) &
PIDS+=($!)

echo
echo "  App:      http://localhost:3000"
echo "  API docs: http://127.0.0.1:8000/api/v1/docs"
echo "  Ctrl+C to stop."
# Stop both when either exits (portable: macOS ships bash 3.2, without `wait -n`).
while kill -0 "${PIDS[0]}" 2>/dev/null && kill -0 "${PIDS[1]}" 2>/dev/null; do
  sleep 1
done
echo "a server exited; stopping" >&2
