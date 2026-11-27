#!/usr/bin/env bash
# Real-world discovery check against the RUNNING backend:
#   1. backend is up   2. track sample company boards   3. trigger discovery
#   4. wait for the run   5. verify jobs are stored (API, and DB when psql is available)
#   6. print the UI links to look at them.
#
# Usage (backend already running, e.g. via ./scripts/dev.sh):
#   ./scripts/validate_discovery.sh
#   BOARDS="greenhouse:stripe lever:palantir" ./scripts/validate_discovery.sh
# Env: API (default http://127.0.0.1:8000), UI (default http://localhost:3000),
#      BOARDS (source:slug ...), DATABASE_URL (optional, for the DB check),
#      API_KEY (only if AUTH_MODE=api_key).
# This calls the real Greenhouse / Lever / Ashby APIs, so it needs internet access.
set -euo pipefail

API="${API:-http://127.0.0.1:8000}"
UI="${UI:-http://localhost:3000}"
BOARDS="${BOARDS:-greenhouse:figma lever:spotify ashby:ramp}"
V1="$API/api/v1"
AUTH=()
[ -n "${API_KEY:-}" ] && AUTH=(-H "X-API-Key: $API_KEY")

py() { python3 -c "import json,sys; d=json.load(sys.stdin); $1"; }
BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT
call() {  # call METHOD PATH [JSON]: sets CODE, response body in $BODY
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    CODE=$(curl -s -o "$BODY" -w '%{http_code}' "${AUTH[@]}" -X "$method" \
      -H 'content-type: application/json' -d "$body" "$V1$path")
  else
    CODE=$(curl -s -o "$BODY" -w '%{http_code}' "${AUTH[@]}" -X "$method" "$V1$path")
  fi
}
get() {  # get PATH: prints the body; fails on non-2xx
  call GET "$1"
  case "$CODE" in 2*) cat "$BODY" ;; *) echo "GET $1 -> $CODE: $(cat "$BODY")" >&2; exit 1 ;; esac
}

echo "==> 1. backend at $API"
curl -fsS "$API/health/ready" >/dev/null || { echo "Backend is not running/ready. Start it: ./scripts/dev.sh"; exit 1; }
echo "    ready"

echo "==> 2. tracking company boards: $BOARDS"
for board in $BOARDS; do
  source="${board%%:*}"; slug="${board#*:}"
  call POST /companies "{\"source\":\"$source\",\"slug\":\"$slug\"}"
  body=$(cat "$BODY")
  case "$CODE" in
    201) echo "    added   $source/$slug ($(echo "$body" | py 'print(d["name"])'))" ;;
    409) echo "    already $source/$slug" ;;
    *)   echo "    FAILED  $source/$slug -> $CODE $(echo "$body" | py 'print(d["error"]["message"])' 2>/dev/null || echo "$body")"; exit 1 ;;
  esac
done

echo "==> 3. triggering discovery"
call POST /discovery/runs '{}'
body=$(cat "$BODY")
if [ "$CODE" = "409" ]; then
  echo "    a run is already in progress; following it"
  RUN_ID=$(get "/discovery/runs?limit=1" | py 'print(d["items"][0]["id"])')
elif [ "$CODE" = "202" ]; then
  RUN_ID=$(echo "$body" | py 'print(d["run_id"])')
else
  echo "    FAILED -> $CODE $body"; exit 1
fi
echo "    run $RUN_ID"

echo "==> 4. waiting for the run"
STATUS=running
for _ in $(seq 1 300); do
  RUN=$(get "/discovery/runs/$RUN_ID")
  STATUS=$(echo "$RUN" | py 'print(d["status"])')
  [ "$STATUS" != "running" ] && break
  sleep 1
done
echo "$RUN" | py '
d["secs"] = (d["duration_ms"] or 0) / 1000
print("    status {status} in {secs:.1f}s: {jobs_found} found, {jobs_inserted} new, {jobs_updated} updated, "
      "{jobs_unchanged} unchanged, {jobs_skipped} skipped, {jobs_expired} expired".format(**d))
for c in d["details"]:
    c["extra"] = c["error"] or ", ".join("%s %s" % (n, r) for r, n in c["skip_reasons"].items())
    print("      {status:9} {source}/{slug}: {found} found, {inserted} new {extra}".format(**c))'
[ "$STATUS" = "succeeded" ] || [ "$STATUS" = "partial" ] || { echo "Run did not succeed ($STATUS)"; exit 1; }

echo "==> 5. verifying stored jobs"
TOTAL=$(get "/jobs?limit=1" | py 'print(d["total"])')
echo "    API: $TOTAL active jobs"
[ "$TOTAL" -gt 0 ] || { echo "No jobs stored"; exit 1; }
get "/jobs?limit=3&sort=newest" | py '
for j in d["items"]:
    print("      {company_name}: {title} ({location}, {remote_type})".format(**j))'
FIRST_ID=$(get "/jobs?limit=1" | py 'print(d["items"][0]["id"])')
get "/jobs/$FIRST_ID" | py '
assert d["description"], "empty description"
print("    detail ok: %d chars of description, %d requirements" % (len(d["description"]), len(d["requirements"])))'
get "/jobs/$FIRST_ID/raw" | py 'print("    raw payload ok (%s #%s)" % (d["source"], d["external_id"]))'
if [ -n "${DATABASE_URL:-}" ] && command -v psql >/dev/null; then
  DB_URL="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"
  echo "    DB: $(psql "$DB_URL" -Atc "SELECT count(*) || ' jobs, ' || count(DISTINCT company_id) || ' companies, last seen ' || max(last_seen_at) FROM jobs WHERE status <> 'expired'")"
fi

echo "==> 6. look at them in the UI"
echo "    $UI/jobs           (search and filter)"
echo "    $UI/jobs/$FIRST_ID"
echo "    $UI/discovery      (runs, companies, connector health)"
echo "validation passed"
