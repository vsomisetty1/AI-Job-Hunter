# Backup and recovery

Everything AI Job Hunter knows lives in two places:

| What | Where (Compose) | Where (native, `scripts/dev.sh`) |
|---|---|---|
| **Database**: profile, parsed and tailored resume versions, jobs, scores, packages, answers, applications, submissions and their logs, interview outcomes, learning history, settings | volume `pgdata19` (service `db`) | the same Compose `db` service |
| **Stored files**: uploaded resumes, generated PDF/DOCX, cover letters, automation screenshots | volume `appdata`, `/data/storage` in the backend container | `backend/data/storage` (`LOCAL_STORAGE_DIR`) |

Jobs can be rediscovered; your outcomes, edits and history cannot. Back up before every
update and regularly while you are applying.

## Back up

```bash
./scripts/backup.sh                       # into ./backups/
./scripts/backup.sh --out /mnt/usb/ajh    # somewhere else
./scripts/backup.sh --keep 14             # and delete all but the newest 14
```

Safe while the app is running (`pg_dump` reads a consistent snapshot). The script finds
the database and files itself:
- database: inside the Compose `db` container if it is running (client and server
  versions always match); otherwise `DATABASE_URL` with local PostgreSQL tools of the
  server's version or newer; otherwise those tools from the `postgres:19-alpine` image.
- files: the Compose backend's `/data` volume if the Compose backend exists; otherwise
  `LOCAL_STORAGE_DIR` (relative to `backend/`).

Each backup is a folder `ajh-backup-<UTC time>` (written as `.partial` and renamed only
when complete):

| File | Content |
|---|---|
| `database.dump` | `pg_dump` custom format, without owners or privileges; checked with `pg_restore --list` before the backup is called done |
| `files.tar.gz` | every stored file (absent with `STORAGE_BACKEND=supabase`) |
| `manifest.json` | creation time, app version, **schema revision**, where each part came from, table and file counts, sizes |
| `SHA256SUMS` | checksums of the dump and the archive |

Backups contain your resume and personal data. They are created readable by you only
(folder mode 700); `backups/` is git-ignored. Keep a copy off the machine (an encrypted
disk or a cloud drive you trust); a backup on the same disk does not survive the disk.

### Schedule it

macOS / Linux, every day at 21:30, keeping two weeks (`crontab -e`):

```
30 21 * * * cd /path/to/AI-Job-Hunter && ./scripts/backup.sh --keep 14 >> backups/backup.log 2>&1
```

The machine must be on, and for Compose, Docker running. A missed run is simply skipped.

## Restore

```bash
docker compose stop backend frontend      # Compose: stop the app, keep the database running
./scripts/restore.sh backups/ajh-backup-20261128T004240Z
docker compose up -d --wait               # the backend migrates the restored data if needed
```

Natively: stop `scripts/dev.sh` (Ctrl+C), run the restore, then `./scripts/dev.sh`.

What `restore.sh` does, in order, stopping at the first problem:
1. Verifies every checksum (a corrupted backup is refused before anything changes).
2. Refuses a backup whose schema revision is newer than this code (update the code first).
3. Refuses while the backend is running (`--force` overrides; do not).
4. Asks you to type `restore` (`--yes` skips this).
5. **Backs up the current state** into `<backups>/pre-restore/` (`--no-safety-backup`
   skips this, for example when the current database is broken).
6. Replaces the database: drops and recreates the `public` schema, then `pg_restore` in a
   single transaction; checks the restored schema revision.
7. Replaces the stored files (natively, the previous folder is put back if extraction
   fails).

An older backup restores into newer code: its schema is migrated when the backend starts
(Compose) or with `scripts/init_db.sh` (native).

## Verify your backups

A backup you have never restored is a hope, not a backup. CI restores one on every push
(`scripts/test_backup_restore.sh` on the native layout, `scripts/smoke_compose.sh` on the
Compose volumes) and checks that every table and file comes back byte for byte. To check
your own, restore it into a separate, throwaway Compose project next to your running app
(same code version as the backup or newer):

```bash
git clone /path/to/AI-Job-Hunter /tmp/ajh-restore-test && cd /tmp/ajh-restore-test
cp /path/to/AI-Job-Hunter/.env .
export COMPOSE_PROJECT_NAME=ajh-restore-test POSTGRES_PORT=5433 BACKEND_PORT=8002 FRONTEND_PORT=3002
docker compose up -d --wait db
docker compose create --build backend      # its volume receives the files
./scripts/restore.sh /path/to/backups/ajh-backup-... --yes --no-safety-backup
docker compose up -d --build --wait        # look around at http://localhost:3002
docker compose down -v                     # removes only the throwaway project
```

`COMPOSE_PROJECT_NAME` keeps the test's containers and volumes apart from your real ones.

## Recovery scenarios

| Situation | What to do |
|---|---|
| A bad update or migration | `docker compose stop backend frontend`, check out the previous version, `docker compose up -d --build --wait db`, restore the backup made before updating, start the app. |
| Deleted data by mistake (a resume, a package) | Restore the latest backup from before the deletion. Everything after it is lost, so back up first (the restore does) and compare. |
| `docker compose down -v` or a lost volume | `docker compose up -d --wait db`, restore the latest backup, `docker compose up -d --build --wait`. |
| New machine | Clone the repository, copy `.env` and the backup folder, `docker compose up -d --wait db`, restore, start the app. |
| Interrupted work at a crash or restart | Nothing to restore: at startup the app marks runs, package generations and automation runs that were cut off as failed or cancelled; retry them from the UI. |
| Lost `POSTGRES_PASSWORD` | The volume keeps the old password. Restore into a fresh volume: `docker compose down`, `docker volume rm ai-job-hunter_pgdata19`, set a new password, start `db`, restore. |

## Not covered

- **Supabase storage** (`STORAGE_BACKEND=supabase`): files stay in the bucket and are not
  in `files.tar.gz`; use Supabase's own backups. Restoring into Supabase Postgres is not
  supported by `restore.sh` (it drops and recreates the `public` schema).
- **Files already uploaded to an ATS**: attaching a resume in an application form uploads it
  to that company's system (AUTOMATION_VALIDATION.md); deleting or restoring here does not
  change that.
- `.env`: back it up yourself, separately (it holds your database password and API keys).
