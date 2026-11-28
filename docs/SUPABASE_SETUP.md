# Supabase (optional)

The default setup keeps everything on your machine: PostgreSQL in Docker and files on
local disk. Supabase can replace either part. Most people should not: it puts your resume
and job-search history on a hosted service, and the backup scripts cover it only partly
(BACKUP_AND_RECOVERY.md).

## Storage (files)

1. Create a Supabase project.
2. In the SQL editor, run [`supabase/storage.sql`](../supabase/storage.sql). It creates the
   **private** bucket `job-hunter` (no public or anonymous access; 10 MB per file; PDF, DOCX
   and PNG). Re-running it updates an existing bucket (versions before 0.10.0 did not allow
   PNG, so automation screenshots failed to store).
3. In `.env`:

   ```
   STORAGE_BACKEND=supabase
   SUPABASE_URL=https://<project>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<service role key>   # Settings -> API; server-side only
   SUPABASE_BUCKET=job-hunter
   ```

The service-role key bypasses Supabase's row-level security: it stays in `.env` on your
machine and is never sent to the browser. Downloads go through the API (`/api/v1/...`),
never directly from Supabase.

## Database

Set `DATABASE_URL` to the project's connection string (Settings -> Database):

- **Session pooler or direct connection (port 5432)**: recommended.
- **Transaction pooler (port 6543)**: works; the app detects it and turns off prepared
  statements.

Then run the migrations with `scripts/init_db.sh` and run the backend natively
(DEPLOYMENT.md, section 3). The Compose backend always uses the Compose `db` service: its
`DATABASE_URL` is set in `docker-compose.yml` and overrides `.env`.

Requires PostgreSQL 15 or newer (Supabase's current versions qualify).

## Backups with Supabase

- `scripts/backup.sh` dumps a Supabase database when its PostgreSQL client tools can reach
  it (`DATABASE_URL`), but `scripts/restore.sh` does not restore into Supabase (it drops
  and recreates the `public` schema, which Supabase manages). Use Supabase's own backups
  and point-in-time recovery for a hosted database.
- Files in a Supabase bucket are not included in `files.tar.gz`.
