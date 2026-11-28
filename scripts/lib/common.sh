#!/usr/bin/env bash
# Shared helpers for scripts/backup.sh and scripts/restore.sh. Source it; do not run it.
#
# Where things live (detected, per piece):
#   database  - the Compose "db" container if it is running (pg_dump/pg_restore run
#               inside it, so client and server versions always match); otherwise
#               DATABASE_URL with local PostgreSQL client tools of the server's major
#               version or newer; otherwise those tools from the postgres image
#               ($PG_IMAGE) through Docker.
#   files     - the Compose "backend" container's /data volume if that container
#               exists (the full-stack Compose deployment); otherwise
#               LOCAL_STORAGE_DIR on this machine (relative to backend/).
#               STORAGE_BACKEND=supabase keeps files in Supabase: not backed up here.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PG_IMAGE="${PG_IMAGE:-postgres:19-alpine}"
# shellcheck disable=SC2034  # used by the scripts that source this file
CONTAINER_STORAGE_DIR="/data/storage"

die() { echo "error: $*" >&2; exit 1; }
info() { echo "==> $*" >&2; }

load_env() {
  # .env provides defaults; variables already set in the environment win.
  if [ -f "$ROOT/.env" ]; then
    local line key
    while IFS= read -r line || [ -n "$line" ]; do
      [[ "$line" =~ ^[[:space:]]*# ]] && continue
      line="${line%%[[:space:]]#*}"  # inline comment (as Compose reads .env)
      [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
      key="${BASH_REMATCH[1]}"
      if [ -z "${!key+x}" ]; then
        local value="${BASH_REMATCH[2]}"
        value="${value%"${value##*[![:space:]]}"}"  # trim trailing spaces
        value="${value#\"}"; value="${value%\"}"
        export "$key=$value"
      fi
    done < "$ROOT/.env"
  fi
  POSTGRES_USER="${POSTGRES_USER:-jobhunter}"
  POSTGRES_DB="${POSTGRES_DB:-jobhunter}"
  STORAGE_BACKEND="${STORAGE_BACKEND:-local}"
  LOCAL_STORAGE_DIR="${LOCAL_STORAGE_DIR:-./data/storage}"
}

compose() { docker compose --progress quiet --project-directory "$ROOT" "$@"; }

have_docker() { command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }

compose_running() {  # compose_running <service>
  [ "${BACKUP_IGNORE_COMPOSE:-0}" = 1 ] && return 1
  have_docker || return 1
  [ -n "$(compose ps --status running -q "$1" 2>/dev/null)" ]
}

compose_exists() {  # compose_exists <service>: container created (running or stopped)
  [ "${BACKUP_IGNORE_COMPOSE:-0}" = 1 ] && return 1
  have_docker || return 1
  [ -n "$(compose ps -a -q "$1" 2>/dev/null)" ]
}

# libpq form of DATABASE_URL (drops SQLAlchemy driver suffixes).
libpq_url() {
  local url="${DATABASE_URL:?Set DATABASE_URL (or start the Compose db service)}"
  url="${url/postgresql+asyncpg:\/\//postgresql://}"
  url="${url/postgresql+psycopg2:\/\//postgresql://}"
  url="${url/postgres:\/\//postgresql://}"
  echo "$url"
}

DB_MODE=""
select_db_mode() {
  if compose_running db; then
    DB_MODE="compose"
  elif command -v pg_dump >/dev/null 2>&1 && command -v psql >/dev/null 2>&1 \
      && local_tools_new_enough; then
    DB_MODE="local"
  elif have_docker; then
    DB_MODE="docker"
  else
    die "no way to reach PostgreSQL tools: start the Compose db, install PostgreSQL client tools of the server's version, or install Docker"
  fi
  info "database via: $DB_MODE"
}

local_tools_new_enough() {
  local client server
  client="$(pg_dump --version | grep -oE '[0-9]+' | head -1)"
  server="$(psql "$(libpq_url)" -XAtc 'SHOW server_version_num' 2>/dev/null)" || return 1
  [ "$client" -ge "$((server / 10000))" ]
}

# pg_tool <pg_dump|pg_restore|psql> [args...]: runs the tool against the app database.
# stdin and stdout pass through (dumps are streamed, never written inside containers).
pg_tool() {
  local tool="$1"; shift
  case "$DB_MODE" in
    compose)
      compose exec -T db "$tool" -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@" ;;
    local)
      "$tool" -d "$(libpq_url)" "$@" ;;
    docker)
      docker run --rm -i --network host "$PG_IMAGE" "$tool" -d "$(libpq_url)" "$@" ;;
    *) die "select_db_mode first" ;;
  esac
}

FILES_MODE=""
select_files_mode() {
  if [ "$STORAGE_BACKEND" = "supabase" ]; then
    FILES_MODE="supabase"
  elif compose_exists backend; then
    FILES_MODE="compose"
  else
    FILES_MODE="local"
  fi
  info "files via: $FILES_MODE"
}

local_storage_path() {
  case "$LOCAL_STORAGE_DIR" in
    /*) echo "$LOCAL_STORAGE_DIR" ;;
    ~*) echo "${LOCAL_STORAGE_DIR/#\~/$HOME}" ;;
    *) echo "$ROOT/backend/${LOCAL_STORAGE_DIR#./}" ;;
  esac
}

# Runs a command in a one-off container that mounts the backend's data volume
# (works whether the backend is running or stopped).
in_backend_volume() {
  compose run --rm --no-deps -T --entrypoint "" backend "$@"
}

# Newest migration revision this checkout knows (e.g. 0008).
code_head_revision() {
  local f head=""
  for f in "$ROOT"/backend/migrations/versions/[0-9][0-9][0-9][0-9]_*.py; do
    f="$(basename "$f")"
    [[ "${f:0:4}" > "$head" ]] && head="${f:0:4}"
  done
  echo "$head"
}

sha256_of() {  # GNU coreutils or macOS
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

backend_running() {
  if compose_running backend; then return 0; fi
  local port="${BACKEND_PORT:-8000}"
  curl -fsS -m 2 "http://127.0.0.1:${port}/health" >/dev/null 2>&1
}

# pg_exec <tool> [args...]: a PostgreSQL client tool without connection arguments
# (e.g. `pg_restore --list`), from the same place as pg_tool.
pg_exec() {
  local tool="$1"; shift
  case "$DB_MODE" in
    compose) compose exec -T db "$tool" "$@" ;;
    local) "$tool" "$@" ;;
    docker) docker run --rm -i "$PG_IMAGE" "$tool" "$@" ;;
    *) die "select_db_mode first" ;;
  esac
}

app_version() {
  grep -m1 -E '^version = ' "$ROOT/backend/pyproject.toml" | cut -d'"' -f2
}
