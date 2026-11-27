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

# Filtering and scoring API (Phase 6).
expect 200 GET "/api/v1/jobs?sort=score&filter_state=passed&min_score=50"
expect 422 GET "/api/v1/jobs?min_score=101"
expect 200 GET /api/v1/scoring/summary
expect 422 PATCH /api/v1/settings '{"job_types": ["gig"]}'
expect 200 PATCH /api/v1/settings '{"excluded_keywords": [], "claude_scoring_min_score": 60}'
SCORE=$(curl -fsS -X POST "$BASE/api/v1/scoring/runs") || fail "could not start scoring"
SCORE_TASK=$(echo "$SCORE" | python -c "import json,sys; print(json.load(sys.stdin)['task_id'])")
for _ in $(seq 1 60); do
  STATUS=$(curl -fsS "$BASE/api/v1/system/tasks/$SCORE_TASK" | python -c "import json,sys; print(json.load(sys.stdin)['status'])")
  [ "$STATUS" = "succeeded" ] && break
  [ "$STATUS" = "failed" ] && fail "scoring task failed"
  sleep 0.5
done
[ "$STATUS" = "succeeded" ] || fail "scoring did not finish"
curl -fsS "$BASE/api/v1/scoring/summary" | grep -q '"last_run_status":"succeeded"' \
  || fail "scoring run not recorded"
echo "ok  filtering and scoring run succeeded"

# Application packages (Phase 7): seed one job, generate, download, review, approve.
JOB_ID=$(python - <<'PY'
import os, uuid, psycopg2
conn = psycopg2.connect(os.environ["DATABASE_URL"])
with conn, conn.cursor() as cur:
    slug = f"smoke-{uuid.uuid4().hex[:8]}"
    cur.execute("INSERT INTO companies (name, source, slug) VALUES ('Smoke Co', 'greenhouse', %s) RETURNING id", (slug,))
    company = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO jobs (company_id, external_id, title, url, dedup_key, description, requirements) "
        "VALUES (%s, '1', 'Senior Backend Engineer', %s, %s, 'Python and PostgreSQL on AWS.', "
        "'[\"5+ years of Python\"]'::jsonb) RETURNING id",
        (company, f"https://example.com/{slug}", uuid.uuid4().hex * 2),
    )
    print(cur.fetchone()[0])
PY
) || fail "could not seed a job"
PKG=$(curl -fsS -X POST -H 'content-type: application/json' -d "{\"job_id\": \"$JOB_ID\"}" \
  "$BASE/api/v1/packages") || fail "could not start package generation"
PKG_ID=$(echo "$PKG" | python -c "import json,sys; print(json.load(sys.stdin)['package_id'])")
for _ in $(seq 1 60); do
  PKG_STATUS=$(curl -fsS "$BASE/api/v1/packages/$PKG_ID" | python -c "import json,sys; print(json.load(sys.stdin)['status'])")
  [ "$PKG_STATUS" != "generating" ] && break
  sleep 0.5
done
[ "$PKG_STATUS" = "generated" ] || fail "package generation ended as $PKG_STATUS"
echo "ok  package generated"
expect 200 GET "/api/v1/packages/$PKG_ID/files/resume.pdf"
expect 200 GET "/api/v1/packages/$PKG_ID/files/resume.docx"
expect 200 GET "/api/v1/packages/$PKG_ID/files/cover-letter.pdf"
expect 200 GET "/api/v1/packages/$PKG_ID/files/original-resume.pdf"
expect 200 GET "/api/v1/packages?status=generated"
expect 200 POST "/api/v1/packages/$PKG_ID/review"
expect 200 POST "/api/v1/packages/$PKG_ID/approve" '{"notes": "smoke"}'
expect 409 POST "/api/v1/packages/$PKG_ID/approve"
# Data lifecycle (MVP validation): an approved package is kept; storage report and cleanup.
expect 409 DELETE "/api/v1/packages/$PKG_ID"
expect 200 GET "/api/v1/system/storage"
expect 200 POST "/api/v1/system/storage/cleanup"
# Application automation (Phase 8, approval mode): queue and rules, no browser needed.
expect 200 GET "/api/v1/automation/status"
expect 200 GET "/api/v1/automation/queue"
expect 200 GET "/api/v1/automation/submissions"
expect 200 GET "/api/v1/automation/logs"
expect 422 POST "/api/v1/automation/submissions/00000000-0000-0000-0000-000000000000/submit" '{}'
expect 404 POST "/api/v1/automation/submissions" '{"package_id": "00000000-0000-0000-0000-000000000000"}'

grep -q "Traceback" "$LOG" && fail "traceback in server log"
echo "smoke test passed"
