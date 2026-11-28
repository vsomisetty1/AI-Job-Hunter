#!/usr/bin/env bash
# Smoke test of the full Compose deployment (CI runs it; safe to run locally on a
# stack that holds no data you care about: it backs up and RESTORES the stack).
#
# Usage: docker compose up -d --build --wait && scripts/smoke_compose.sh
#        SMOKE_SKIP_BROWSER=1 for an image built with INSTALL_BROWSER=false
# Checks: readiness and migrations; the frontend serves pages with security
# headers; every port is published on 127.0.0.1 only; containers do not run as
# root; the local request guard refuses foreign Host names and cross-site
# writes; headless Chromium launches inside the backend image; a backup of the
# Compose volumes restores data and files exactly.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lib/common.sh
. scripts/lib/common.sh
load_env
API="http://127.0.0.1:${BACKEND_PORT:-8000}"
WEB="http://127.0.0.1:${FRONTEND_PORT:-3000}"
fail() { echo "COMPOSE SMOKE FAIL: $*" >&2; exit 1; }
ok() { echo "ok  $*"; }

ready="$(curl -fsS "$API/health/ready")" || fail "backend not ready"
echo "$ready" | grep -q '"migrations":{"ok":true,"detail":"'"$(code_head_revision)"'"}' \
  || fail "migrations not at head: $ready"
ok "backend ready, schema at $(code_head_revision)"

headers="$(curl -fsS -D - -o /dev/null "$WEB/")" || fail "frontend not serving"
echo "$headers" | grep -qi '^x-frame-options: DENY' || fail "frontend lacks X-Frame-Options"
ok "frontend serves pages with security headers"

while read -r svc port; do
  for published in $(compose port "$svc" "$port"); do
    case "$published" in
      127.0.0.1:*) ;;
      *) fail "$svc:$port is published on $published (must be 127.0.0.1)" ;;
    esac
  done
done <<'PORTS'
db 5432
backend 8000
frontend 3000
PORTS
ok "all ports published on 127.0.0.1 only"

for svc in backend frontend; do
  uid="$(compose exec -T "$svc" id -u)"
  [ "$uid" != 0 ] || fail "$svc runs as root"
done
ok "containers run as unprivileged users"

code="$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: rebind.example' "$API/api/v1/resumes")"
[ "$code" = 400 ] || fail "foreign Host answered $code"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Origin: https://evil.example' "$API/api/v1/discovery/runs")"
[ "$code" = 403 ] || fail "cross-site POST answered $code"
code="$(curl -s -o /dev/null -w '%{http_code}' -X PATCH -H 'content-type: application/json' \
  -H "Origin: http://localhost:${FRONTEND_PORT:-3000}" -d '{"application_mode": "AUTONOMOUS_MODE"}' \
  "$API/api/v1/settings")"
[ "$code" = 422 ] || fail "autonomous mode PATCH answered $code"
ok "request guard and approval-mode-only settings active"

if [ "${SMOKE_SKIP_BROWSER:-0}" = 1 ]; then
  echo "--  Chromium check skipped (SMOKE_SKIP_BROWSER=1)"
else
compose exec -T backend python - <<'PY' || fail "Chromium does not launch in the backend image"
import asyncio
from playwright.async_api import async_playwright

async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("<label for=x>Name</label><input id=x>")
        await page.fill("#x", "ok")
        assert await page.input_value("#x") == "ok"
        await browser.close()

asyncio.run(main())
PY
ok "headless Chromium fills a form inside the backend image"
fi

# Backup -> change -> restore, through the Compose volumes.
compose exec -T backend sh -c 'mkdir -p /data/storage/smoke && echo kept > /data/storage/smoke/file.txt'
compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -qc \
  "INSERT INTO companies (name, source, slug) VALUES ('Smoke', 'lever', 'compose-smoke') ON CONFLICT DO NOTHING"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT
BK="$(scripts/backup.sh --out "$OUT" 2>/dev/null | tail -1)"
grep -q '"source": "compose"' "$BK/manifest.json" || fail "backup did not use the Compose services"
compose stop backend frontend >/dev/null
compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -qc "DELETE FROM companies WHERE slug = 'compose-smoke'"
compose run --rm --no-deps -T --entrypoint "" backend rm -rf /data/storage/smoke
scripts/restore.sh "$BK" --yes >/dev/null 2>&1 || fail "restore failed"
[ "$(compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
  "SELECT count(*) FROM companies WHERE slug = 'compose-smoke'")" = 1 ] || fail "row not restored"
[ "$(compose run --rm --no-deps -T --entrypoint "" backend cat /data/storage/smoke/file.txt)" = kept ] \
  || fail "file not restored"
compose start backend frontend >/dev/null
for _ in $(seq 1 60); do curl -fsS "$API/health/ready" >/dev/null 2>&1 && break; sleep 2; done
curl -fsS "$API/health/ready" >/dev/null || fail "backend did not come back after the restore"
ok "backup and restore of the Compose volumes"
echo "compose smoke test passed"
