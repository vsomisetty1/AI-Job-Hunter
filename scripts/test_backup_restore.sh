#!/usr/bin/env bash
# Round-trip test of scripts/backup.sh and scripts/restore.sh (CI runs it after
# the smoke test, whose data it uses). DESTRUCTIVE for DATABASE_URL: it replaces
# that database twice. Point it only at a disposable database.
#
# Usage: DATABASE_URL=postgresql://... scripts/test_backup_restore.sh
# Checks: every table's content and every stored file come back byte for byte;
# a newer change is undone; a corrupted backup and a backup from a newer schema
# are refused; the automatic safety backup is written; --keep prunes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${DATABASE_URL:?Set DATABASE_URL to a disposable, migrated database}"
export BACKUP_IGNORE_COMPOSE=1 STORAGE_BACKEND=local
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export LOCAL_STORAGE_DIR="$WORK/storage"
OUT="$WORK/backups"
# shellcheck source=lib/common.sh
. "$ROOT/scripts/lib/common.sh"
load_env
select_db_mode >/dev/null 2>&1

fail() { echo "BACKUP TEST FAIL: $*" >&2; exit 1; }
ok() { echo "ok  $*"; }

# Content fingerprint of every table (rows in a stable order) and of the files.
fingerprint() {
  local tables
  tables="$(pg_tool psql -XAtc "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")"
  for t in $tables; do
    printf '%s %s\n' "$t" "$(pg_tool psql -XAtc \
      "SELECT count(*) || ':' || coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '-') FROM $t x")"
  done
  (cd "$LOCAL_STORAGE_DIR" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum)
}

mkdir -p "$LOCAL_STORAGE_DIR/resumes/a" "$LOCAL_STORAGE_DIR/packages"
echo "resume bytes" > "$LOCAL_STORAGE_DIR/resumes/a/cv.pdf"
head -c 4096 /dev/urandom > "$LOCAL_STORAGE_DIR/packages/binary.docx"
echo "name with spaces" > "$LOCAL_STORAGE_DIR/packages/a file.txt"
ROWS="$(pg_tool psql -XAtc "SELECT count(*) FROM settings")"
[ "$ROWS" = 1 ] || fail "database is not migrated (settings has $ROWS rows)"

BEFORE="$(fingerprint)"
B1="$("$ROOT/scripts/backup.sh" --out "$OUT" 2>/dev/null | tail -1)"
[ -f "$B1/database.dump" ] && [ -f "$B1/files.tar.gz" ] || fail "backup files missing"
grep -q '"count": 3' "$B1/manifest.json" || fail "manifest file count: $(cat "$B1/manifest.json")"
[ "$(stat -c '%a' "$B1")" = 700 ] || fail "backup folder is readable by others"
ok "backup written ($(basename "$B1"))"

# Change everything after the backup.
pg_tool psql -XAqc "INSERT INTO companies (name, source, slug) VALUES ('After', 'lever', 'after-backup')"
pg_tool psql -XAqc "UPDATE settings SET salary_min = 1"
rm "$LOCAL_STORAGE_DIR/resumes/a/cv.pdf"
echo "new" > "$LOCAL_STORAGE_DIR/new-after-backup.txt"
[ "$(fingerprint)" != "$BEFORE" ] || fail "the change was not visible"

"$ROOT/scripts/restore.sh" "$B1" --yes >/dev/null 2>"$WORK/restore.log" \
  || { cat "$WORK/restore.log" >&2; fail "restore failed"; }
[ "$(fingerprint)" = "$BEFORE" ] || fail "restored data differs from the backup"
ok "restore brings back every table and file exactly"
ls -d "$OUT"/pre-restore/ajh-backup-*Z >/dev/null 2>&1 || fail "no safety backup before restoring"
ok "safety backup of the replaced state written"

# A corrupted backup is refused before anything is touched.
cp -r "$B1" "$WORK/corrupt"
printf 'x' >> "$WORK/corrupt/files.tar.gz"
if "$ROOT/scripts/restore.sh" "$WORK/corrupt" --yes --no-safety-backup 2>"$WORK/err"; then
  fail "a corrupted backup was restored"
fi
grep -q "checksum mismatch" "$WORK/err" || fail "unexpected error: $(cat "$WORK/err")"
ok "corrupted backup refused"

# A backup from a newer schema than this code knows is refused.
cp -r "$B1" "$WORK/newer"
sed -i 's/"schema_revision": "[0-9]*"/"schema_revision": "9999"/' "$WORK/newer/manifest.json"
if "$ROOT/scripts/restore.sh" "$WORK/newer" --yes --no-safety-backup 2>"$WORK/err"; then
  fail "a backup from a newer schema was restored"
fi
grep -q "newer version" "$WORK/err" || fail "unexpected error: $(cat "$WORK/err")"
ok "backup from a newer schema refused"
[ "$(fingerprint)" = "$BEFORE" ] || fail "a refused restore changed data"

# Retention.
sleep 1; "$ROOT/scripts/backup.sh" --out "$OUT" >/dev/null 2>&1
sleep 1; "$ROOT/scripts/backup.sh" --out "$OUT" --keep 2 >/dev/null 2>&1
[ "$(ls -1d "$OUT"/ajh-backup-*Z | wc -l)" = 2 ] || fail "--keep 2 left $(ls -1d "$OUT"/ajh-backup-*Z | wc -l)"
[ ! -e "$B1" ] || fail "--keep did not remove the oldest backup"
ok "--keep prunes old backups"
echo "backup/restore round trip OK"
