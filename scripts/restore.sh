#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh. This REPLACES the current database
# and stored files with the backup's.
#
# Usage: scripts/restore.sh BACKUP_FOLDER [--yes] [--no-safety-backup] [--force]
#   --yes               do not ask for confirmation
#   --no-safety-backup  skip the automatic backup of the current state first
#   --force             restore even though the backend seems to be running
#
# Steps: verify checksums and that this code can read the backup's schema;
# refuse while the backend runs; back up the current state into
# BACKUP_FOLDER/../pre-restore/; replace the database (drop and recreate the
# public schema, then pg_restore in one transaction); replace the stored files.
# Then start the backend: in Compose it migrates on start; natively run
# scripts/init_db.sh first. See BACKUP_AND_RECOVERY.md.
set -euo pipefail
# shellcheck source=lib/common.sh
. "$(dirname "$0")/lib/common.sh"

SRC=""
YES=0
SAFETY=1
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1; shift ;;
    --no-safety-backup) SAFETY=0; shift ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    -*) die "unknown option: $1 (see --help)" ;;
    *) [ -z "$SRC" ] || die "one backup folder only"; SRC="$1"; shift ;;
  esac
done
[ -n "$SRC" ] || die "usage: scripts/restore.sh BACKUP_FOLDER [--yes] [--no-safety-backup] [--force]"
SRC="$(cd "$SRC" && pwd)" || die "no such folder: $SRC"
[ -f "$SRC/manifest.json" ] && [ -f "$SRC/SHA256SUMS" ] && [ -f "$SRC/database.dump" ] \
  || die "$SRC is not a backup made by scripts/backup.sh"

load_env
umask 077

info "verifying checksums"
while read -r sum file; do
  [ -f "$SRC/$file" ] || die "missing $file"
  [ "$(sha256_of "$SRC/$file")" = "$sum" ] || die "$file is corrupted (checksum mismatch)"
done < "$SRC/SHA256SUMS"

REVISION="$(grep -oE '"schema_revision": *"[0-9]+"' "$SRC/manifest.json" | grep -oE '[0-9]{4}')"
HEAD="$(code_head_revision)"
[ -n "$REVISION" ] || die "manifest.json has no schema_revision"
if [ "$REVISION" \> "$HEAD" ]; then
  die "the backup is from a newer version (schema $REVISION; this code knows up to $HEAD): update the code first"
fi

if backend_running; then
  if [ "$FORCE" = 1 ]; then
    info "warning: the backend seems to be running (--force given)"
  else
    die "stop the backend first (Compose: docker compose stop backend frontend; scripts/dev.sh: Ctrl+C), or pass --force"
  fi
fi

if [ "$YES" != 1 ]; then
  echo "This replaces the current database and stored files with:"
  echo "  $SRC"
  grep -E '"(created_at|app_version|schema_revision)"' "$SRC/manifest.json" | sed 's/^/  /'
  read -r -p "Type 'restore' to continue: " answer
  [ "$answer" = "restore" ] || die "cancelled"
fi

if [ "$SAFETY" = 1 ]; then
  info "backing up the current state first"
  "$ROOT/scripts/backup.sh" --out "$(dirname "$SRC")/pre-restore" >/dev/null \
    || die "the safety backup failed; fix that, or pass --no-safety-backup if the current data does not matter"
fi

select_db_mode
info "restoring the database (schema revision $REVISION)"
pg_tool psql -X -q -v ON_ERROR_STOP=1 -c "SET client_min_messages = warning" \
  -c "DROP SCHEMA public CASCADE" -c "CREATE SCHEMA public" >/dev/null
pg_tool pg_restore --no-owner --no-privileges --exit-on-error --single-transaction \
  < "$SRC/database.dump"
RESTORED="$(pg_tool psql -XAtc 'SELECT version_num FROM alembic_version')"
[ "$RESTORED" = "$REVISION" ] || die "restored schema revision is $RESTORED, expected $REVISION"

select_files_mode
if [ -f "$SRC/files.tar.gz" ]; then
  case "$FILES_MODE" in
    supabase)
      info "warning: the backup has local files but STORAGE_BACKEND=supabase; they were not restored"
      ;;
    compose)
      info "restoring stored files into the backend data volume"
      in_backend_volume sh -c \
        "rm -rf $CONTAINER_STORAGE_DIR && mkdir -p $CONTAINER_STORAGE_DIR && tar -C $CONTAINER_STORAGE_DIR -xzf -" \
        < "$SRC/files.tar.gz"
      ;;
    local)
      STORE="$(local_storage_path)"
      info "restoring stored files into $STORE"
      OLD="$STORE.pre-restore.$$"
      [ ! -e "$STORE" ] || mv "$STORE" "$OLD"
      mkdir -p "$STORE"
      if tar -C "$STORE" -xzf "$SRC/files.tar.gz"; then
        rm -rf "$OLD"
      else
        rm -rf "$STORE"; [ ! -e "$OLD" ] || mv "$OLD" "$STORE"
        die "could not extract the files; the previous files were put back"
      fi
      ;;
  esac
else
  info "the backup has no files (it was made with Supabase storage)"
fi

info "restore complete (schema revision $REVISION; this code: $HEAD)"
if [ "$REVISION" \< "$HEAD" ]; then
  info "the backup's schema is older: migrations run on the next start (Compose) or with scripts/init_db.sh"
fi
