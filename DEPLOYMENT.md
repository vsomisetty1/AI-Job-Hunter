# Deployment

AI Job Hunter is a **personal, single-user app that runs on your own machine**. It is not
built for a server, a LAN or the internet: the API has no login (`AUTH_MODE=none`) and is
safe only because nothing outside your machine can reach it. Everything below keeps it
that way.

There are two ways to run it:

| | Docker Compose (recommended) | Native (development) |
|---|---|---|
| Needs | Docker with Compose v2.24+ | Docker (for Postgres), Python 3.14, Node 26 |
| Starts | `docker compose up -d --build --wait` | `./scripts/dev.sh` |
| Code changes | rebuild the images | live reload |
| Browser automation | headless only | headless or visible (`AUTOMATION_HEADLESS=false`), so you can watch runs and solve CAPTCHAs |
| Data | Docker volumes `pgdata19` and `appdata` | volume `pgdata19` and `backend/data/storage` |

## 1. Configure

```bash
cp .env.example .env
```

Edit `.env`:
- `POSTGRES_PASSWORD`: a strong password. Use the same one inside `DATABASE_URL` (only the
  native backend reads `DATABASE_URL`; Compose builds its own).
- Optional: `ANTHROPIC_API_KEY` (Claude features; set a spend cap in the Anthropic Console),
  `DISCOVERY_INTERVAL_MINUTES`, `AUTOMATION_*`. Every setting is documented in `.env.example`.
- Leave `AUTH_MODE=none`, `BACKEND_HOST=127.0.0.1` and `ALLOWED_HOSTS` as they are.

`.env` is git-ignored. Never commit it.

## 2. Run with Docker Compose

```bash
docker compose up -d --build --wait
```

Open http://localhost:3000. The API and its docs are at http://localhost:8000/api/v1/docs.

What runs:

| Service | Image | Published on | Notes |
|---|---|---|---|
| `db` | `postgres:19-alpine` | `127.0.0.1:5432` | Data in volume `pgdata19` |
| `backend` | built from `backend/Dockerfile` | `127.0.0.1:8000` | Migrates the database on start; data in volume `appdata` (`/data`); runs as an unprivileged user with no Linux capabilities |
| `frontend` | built from `frontend/Dockerfile` | `127.0.0.1:3000` | Next.js standalone server, read-only filesystem |

Everyday commands:

```bash
docker compose ps                    # health of each service
docker compose logs -f backend       # follow the backend log (JSON lines)
docker compose stop                  # stop; data is kept
docker compose up -d --wait          # start again
```

### Updating

```bash
./scripts/backup.sh                  # always back up first (BACKUP_AND_RECOVERY.md)
git pull
docker compose up -d --build --wait  # new images; the backend applies new migrations on start
```

Migrations only move forward. To go back to an older version, restore the backup you
made before updating.

### Options

| `.env` setting | Default | Effect |
|---|---|---|
| `BACKEND_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT` | 8000, 3000, 5432 | Host ports (always on 127.0.0.1). Changing `BACKEND_PORT` needs a rebuild of the frontend (`docker compose build frontend`): the browser bundle contains the API URL. |
| `INSTALL_BROWSER` | `true` | `false` builds a smaller backend image without Chromium; application automation runs then fail because no browser can start |

Not supported in Compose: a visible browser (`AUTOMATION_HEADLESS=false`), because the
container has no display. To watch a run or solve a CAPTCHA, stop the Compose backend and
run the backend natively against the same database (section 3) for that session; files
stored by the native backend go to `backend/data/storage`, not the Compose volume.

## 3. Run natively (development)

```bash
./scripts/dev.sh
```

It starts the Compose `db` service, creates `backend/.venv` and installs dependencies and
Chromium on first run, applies migrations, then runs the backend (`python -m app`, port
8000, auto-reload) and the frontend (`npm run dev`, port 3000). Ctrl+C stops both; the
database keeps running (`docker compose stop db`).

By hand:

```bash
docker compose up -d --wait db
cd backend && source .venv/bin/activate
../scripts/init_db.sh                # alembic upgrade head
python -m app                        # always one worker: the scheduler is in-process
cd ../frontend && npm ci && npm run dev
```

## 4. Security model (read this before changing any network setting)

The API trusts every request it receives. It is protected by four layers (ADR-004, ADR-016):

1. **Loopback only.** The native backend listens on 127.0.0.1; Compose publishes every
   port on 127.0.0.1. The backend refuses to start with `AUTH_MODE=none` on any other
   address (inside its container it may bind 0.0.0.0 because the image sets
   `CONTAINER_LOOPBACK_ONLY=true`, and Compose publishes the port on loopback only).
2. **Host allowlist.** Requests whose `Host` is not in `ALLOWED_HOSTS` (default
   `localhost, 127.0.0.1, ::1`) get 400. This stops DNS-rebinding pages from reading your
   data through your browser.
3. **Cross-site write protection.** Requests that change data and come from another web
   origin than `CORS_ORIGINS` get 403, so a page you visit cannot upload, start runs or
   change settings.
4. **No framing.** Every page and API response forbids being embedded in another site.

Never:
- change a Compose port to `"0.0.0.0:..."` or a bare `"8000:8000"`;
- set `BACKEND_HOST=0.0.0.0` natively;
- add your LAN IP or a public name to `ALLOWED_HOSTS` without `AUTH_MODE=api_key` and a
  random `API_KEY` of at least 32 characters (`openssl rand -hex 32`). Even then the
  frontend has no way to send the key: the app is not designed for remote use.

Application automation stays in **approval mode**: nothing is submitted without your
explicit confirmation, and the database refuses anything else (ADR-014, ADR-016).

## 5. Health and troubleshooting

| Check | Command |
|---|---|
| Liveness | `curl -s http://127.0.0.1:8000/health` |
| Readiness (database, migrations, scheduler) | `curl -s http://127.0.0.1:8000/health/ready` |
| App info and version | `curl -s http://127.0.0.1:8000/api/v1/system/info` |
| Scheduled jobs, background tasks | `/api/v1/system/jobs`, `/api/v1/system/tasks` |
| Agent activity | the **Activity** page, or `/api/v1/agent-runs` |
| Stored files | `/api/v1/system/storage` |

| Symptom | Cause and fix |
|---|---|
| `{"error":{"code":"host_not_allowed"}}` | You opened the app by a name other than `localhost`/`127.0.0.1`. Use those, or add the name to `ALLOWED_HOSTS` (see section 4 first). |
| `{"error":{"code":"cross_site_request"}}` from the app's own pages | The frontend's origin is not in `CORS_ORIGINS` (for example after changing `FRONTEND_PORT` natively). Add `http://localhost:<port>`. |
| Frontend shows "Cannot reach the backend" | Backend not running or not healthy (`docker compose ps`), or the frontend was built for another `BACKEND_PORT` (rebuild it). |
| Backend restarts in a loop | `docker compose logs backend`: usually a wrong `POSTGRES_PASSWORD` after the database volume was created with another one. |
| `docker compose` says `POSTGRES_PASSWORD` is missing | `.env` is missing or does not set it. |
| Automation runs fail to start a browser | Image built with `INSTALL_BROWSER=false`, or natively `playwright install chromium` was not run. |
| A CAPTCHA blocks a submission | Run natively with `AUTOMATION_HEADLESS=false`, retry the run, solve it in the window, then submit. |

## 6. Optional: Supabase instead of local storage and Postgres

See [docs/SUPABASE_SETUP.md](docs/SUPABASE_SETUP.md). Local Postgres and local files remain
the default and the only setup the backup scripts cover completely.

## 7. What this deployment is not

- Not multi-user, not authenticated for remote access, not rate-limited.
- Not horizontally scalable: one backend process (in-process scheduler and background
  tasks, open review forms in memory).
- Not a hosted service. A public or shared deployment needs a new ADR: real
  authentication, per-user data, rate limiting and a review of what the API exposes.
