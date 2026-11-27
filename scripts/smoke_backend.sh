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

STORE="$(mktemp -d)"
WORK=""
# APP_ENV=test: no auto-reload. Scheduler stays on so startup is exercised fully.
APP_ENV=test BACKEND_PORT="$PORT" LOCAL_STORAGE_DIR="$STORE" ANTHROPIC_API_KEY= \
  python -m app >"$LOG" 2>&1 &
PID=$!
cleanup() {
  kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  rm -rf "$STORE" "$WORK"
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

# Resume flow: upload -> background processing -> profile.
WORK="$(mktemp -d)"
python -c "from tests.fixtures.documents import make_pdf; import sys; sys.stdout.buffer.write(make_pdf())" \
  >"$WORK/cv.pdf"
UPLOAD=$(curl -s -w '\n%{http_code}' -F "file=@$WORK/cv.pdf;type=application/pdf" "$BASE/api/v1/resumes")
[ "$(echo "$UPLOAD" | tail -1)" = "201" ] || [ "$(echo "$UPLOAD" | tail -1)" = "409" ] \
  || fail "upload -> $(echo "$UPLOAD" | tail -1)"
echo "ok  POST /api/v1/resumes"
TASK=$(echo "$UPLOAD" | head -1 | python -c "import json,sys; print(json.load(sys.stdin).get('task_id') or '')")
if [ -n "$TASK" ]; then
  for _ in $(seq 1 60); do
    STATUS=$(curl -fsS "$BASE/api/v1/system/tasks/$TASK" | python -c "import json,sys; print(json.load(sys.stdin)['status'])")
    [ "$STATUS" = "succeeded" ] && break
    [ "$STATUS" = "failed" ] && fail "resume processing task failed"
    sleep 0.5
  done
  [ "$STATUS" = "succeeded" ] || fail "resume processing did not finish"
fi
curl -fsS "$BASE/api/v1/profile" | grep -q '"inference_status":"complete"' || fail "profile not generated"
echo "ok  profile generated"

# Discovery API (no network needed: the run targets an id that matches no company).
expect 200 GET /api/v1/jobs
expect 200 GET "/api/v1/jobs?q=engineer&remote_type=remote&sort=posted"
expect 200 GET /api/v1/jobs/stats
expect 404 GET /api/v1/jobs/00000000-0000-0000-0000-000000000000
expect 200 GET /api/v1/companies
expect 200 GET /api/v1/companies/directory
expect 422 POST /api/v1/companies '{"source": "workday", "slug": "x"}'
expect 200 GET /api/v1/discovery/health
expect 200 GET /api/v1/discovery/runs
RUN=$(curl -fsS -X POST -H 'content-type: application/json' \
  -d '{"company_ids": ["00000000-0000-0000-0000-000000000000"]}' "$BASE/api/v1/discovery/runs") \
  || fail "could not start a discovery run"
RUN_ID=$(echo "$RUN" | python -c "import json,sys; print(json.load(sys.stdin)['run_id'])")
for _ in $(seq 1 60); do
  RUN_STATUS=$(curl -fsS "$BASE/api/v1/discovery/runs/$RUN_ID" | python -c "import json,sys; print(json.load(sys.stdin)['status'])")
  [ "$RUN_STATUS" != "running" ] && break
  sleep 0.5
done
[ "$RUN_STATUS" = "succeeded" ] || fail "discovery run ended as $RUN_STATUS"
echo "ok  discovery run $RUN_STATUS"

grep -q "Traceback" "$LOG" && fail "traceback in server log"
echo "smoke test passed"
