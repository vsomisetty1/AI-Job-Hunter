#!/usr/bin/env bash
# Back up everything AI Job Hunter knows about you: the PostgreSQL database
# (profile, resumes' parsed data, jobs, packages, applications, outcomes,
# learning history) and the stored files (resumes, generated PDFs/DOCX,
# screenshots).
#
# Usage: scripts/backup.sh [--out DIR] [--keep N]
#   --out DIR  where backups are written (default: $BACKUP_DIR or ./backups)
#   --keep N   afterwards, delete all but the newest N backups in that folder
#
# Works with the full Compose stack, with `docker compose up db` plus a native
# backend (scripts/dev.sh), or with any PostgreSQL in DATABASE_URL. Safe while the
# app is running: pg_dump takes a consistent snapshot. A backup is a folder:
#   database.dump   pg_dump custom format (pg_restore)
#   files.tar.gz    stored files (absent with STORAGE_BACKEND=supabase)
#   manifest.json   app version, schema revision, sources, sizes, checksums
#   SHA256SUMS      checksums, verified by scripts/restore.sh
# Backups hold personal data: they are created readable by you only (umask 077).
# See BACKUP_AND_RECOVERY.md.
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "$0")/lib/common.sh"

OUT=""
KEEP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="${2:?--out needs a folder}"; shift 2 ;;
    --keep) KEEP="${2:?--keep needs a number}"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done
[ -z "$KEEP" ] || [[ "$KEEP" =~ ^[1-9][0-9]*$ ]] || die "--keep needs a positive number"

load_env
umask 077
OUT="${OUT:-${BACKUP_DIR:-$ROOT/backups}}"
mkdir -p "$OUT"
NAME="ajh-backup-$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT/$NAME"
WORK="$DEST.partial"
[ ! -e "$DEST" ] || die "$DEST already exists"
rm -rf "$WORK"
mkdir "$WORK"
trap 'rm -rf "$WORK"' EXIT

select_db_mode
REVISION="$(pg_tool psql -XAtc 'SELECT version_num FROM alembic_version' 2>/dev/null || true)"
[ -n "$REVISION" ] || die "could not read the schema revision: is the database migrated and reachable?"

info "dumping the database (schema revision $REVISION)"
pg_tool pg_dump --format=custom --no-owner --no-privileges --compress=6 > "$WORK/database.dump"
# Proves the dump is complete and readable before it is called a backup.
TABLES="$(pg_exec pg_restore --list < "$WORK/database.dump" | grep -cE ' TABLE public ' || true)"
[ "$TABLES" -gt 0 ] || die "the database dump lists no tables"

select_files_mode
FILE_COUNT=0
case "$FILES_MODE" in
  supabase)
    info "STORAGE_BACKEND=supabase: files stay in the Supabase bucket (not backed up here)"
    ;;
  compose)
    info "archiving stored files from the backend data volume"
    in_backend_volume sh -c "mkdir -p $CONTAINER_STORAGE_DIR && tar -C $CONTAINER_STORAGE_DIR -czf - ." \
      > "$WORK/files.tar.gz"
    ;;
  local)
    STORE="$(local_storage_path)"
    info "archiving stored files from $STORE"
    if [ -d "$STORE" ]; then
      tar -C "$STORE" -czf "$WORK/files.tar.gz" .
    else
      info "no storage folder yet: archiving nothing"
      tar -czf "$WORK/files.tar.gz" -T /dev/null
    fi
    ;;
esac
if [ -f "$WORK/files.tar.gz" ]; then
  FILE_COUNT="$(tar -tzf "$WORK/files.tar.gz" | grep -vc '/$' || true)"
fi

(
  cd "$WORK"
  for f in database.dump files.tar.gz; do
    [ -f "$f" ] && echo "$(sha256_of "$f")  $f"
  done
) > "$WORK/SHA256SUMS"

size_of() { [ -f "$1" ] && wc -c < "$1" | tr -d ' ' || echo 0; }
cat > "$WORK/manifest.json" <<JSON
{
  "format": 1,
  "name": "$NAME",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "app_version": "$(app_version)",
  "schema_revision": "$REVISION",
  "database": {"source": "$DB_MODE", "file": "database.dump", "tables": $TABLES,
               "bytes": $(size_of "$WORK/database.dump")},
  "files": {"source": "$FILES_MODE", "file": $([ -f "$WORK/files.tar.gz" ] && echo '"files.tar.gz"' || echo null),
            "count": $FILE_COUNT, "bytes": $(size_of "$WORK/files.tar.gz")}
}
JSON

mv "$WORK" "$DEST"
trap - EXIT
info "backup written: $DEST ($TABLES tables, $FILE_COUNT files)"

if [ -n "$KEEP" ]; then
  # Names sort by time; delete all but the newest N complete backups.
  ls -1d "$OUT"/ajh-backup-*Z 2>/dev/null | sort | head -n "-$KEEP" | while read -r old; do
    info "removing old backup $(basename "$old")"
    rm -rf "$old"
  done
fi
echo "$DEST"
