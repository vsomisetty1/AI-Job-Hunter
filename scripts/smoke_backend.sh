#!/usr/bin/env bash
# End-to-end smoke test of the real server: migrate, start `python -m app`,
# hit the main endpoints, stop. Used by CI; safe to run locally.
#
# Usage: DATABASE_URL=postgresql://... ./scripts/smoke_backend.sh
# Requires the backend virtualenv to be active. Uses port $SMOKE_PORT (default 8765).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${SMOKE_PORT:-8765}"
BASE="http://127.0.0.1:${PORT}"
LOG="$(mktemp)"
: "${DATABASE_URL:?Set DATABASE_URL}"

cd "$ROOT/backend"
alembic upgrade head

# APP_ENV=test: no auto-reload. Scheduler stays on so startup is exercised fully.
APP_ENV=test BACKEND_PORT="$PORT" python -m app >"$LOG" 2>&1 &
PID=$!
cleanup() {
  kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
}
trap cleanup EXIT

fail() {
  echo "SMOKE FAIL: $*" >&2
  echo "--- server log ---" >&2
  cat "$LOG" >&2
  exit 1
}

for _ in $(seq 1 60); do
  curl -fsS "$BASE/health" >/dev/null 2>&1 && break
  kill -0 "$PID" 2>/dev/null || fail "server exited during startup"
  sleep 0.5
done

expect() {  # expect <status> <method> <path> [json-body]
  local want="$1" method="$2" path="$3" body="${4:-}" got
  if [ -n "$body" ]; then
    got=$(curl -s -o /dev/null -w '%{http_code}' -X "$method" -H 'content-type: application/json' \
      -d "$body" "$BASE$path")
  else
    got=$(curl -s -o /dev/null -w '%{http_code}' -X "$method" "$BASE$path")
  fi
  [ "$got" = "$want" ] || fail "$method $path -> $got (expected $want)"
  echo "ok  $method $path -> $got"
}

expect 200 GET /health
expect 200 GET /health/ready
expect 200 GET /api/v1/settings
expect 200 PATCH /api/v1/settings '{"daily_application_cap": 10}'
expect 422 PATCH /api/v1/settings '{"auto_apply_threshold": 101}'
expect 200 GET /api/v1/system/jobs
expect 200 GET /api/v1/openapi.json
expect 404 GET /api/v1/does-not-exist

curl -fsS "$BASE/health/ready" | grep -q '"scheduler":{"ok":true,"detail":"running"}' \
  || fail "scheduler not running"
grep -q "Traceback" "$LOG" && fail "traceback in server log"
echo "smoke test passed"
