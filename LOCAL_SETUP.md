# Local setup

Exact steps to run AI Job Hunter on your own computer for development and real use. Every
command below was run against this repository from a fresh clone (version 0.10.0).

The quickest path is steps 1–3 and 9: `./scripts/dev.sh` does steps 4–8 for you. Steps 4–8
explain each piece and how to run it by hand.

For a Docker-only setup without Python or Node on your machine, see
[DEPLOYMENT.md](DEPLOYMENT.md) (section 2). That setup cannot show the browser window,
which you need to solve CAPTCHAs, so use this guide for your first real application.

Supported: macOS and Linux. On Windows, use WSL 2 (Ubuntu) with Docker Desktop's WSL
integration, and run everything inside WSL.

## 1. Clone the repository

```bash
git clone https://github.com/vsomisetty1/AI-Job-Hunter.git
```

```bash
cd AI-Job-Hunter
```

Version 0.10.0 (the version these guides describe) is on the branch
`claude/amazing-brahmagupta-evi6wd` until it is merged into `main`. Check which version you
have:

```bash
grep '^version' backend/pyproject.toml
```

If it prints anything older than `version = "0.10.0"`, switch to the branch:

```bash
git checkout claude/amazing-brahmagupta-evi6wd
```

## 2. Required software

| Software | Version | Check | Install |
|---|---|---|---|
| Git | any recent | `git --version` | macOS: `xcode-select --install`; Linux: your package manager |
| Docker | Docker Desktop, or Docker Engine with the Compose plugin **v2.24+** | `docker compose version` | https://docs.docker.com/get-docker/ |
| Python | **3.14**, available as `python3.14` | `python3.14 --version` | macOS: `brew install python@3.14`; any OS: `uv python install 3.14` (puts `python3.14` in `~/.local/bin`) |
| Node.js | **26 or newer** (npm 11) | `node --version` | `nvm install 26`, or https://nodejs.org |
| curl, openssl | any | `curl --version` | preinstalled on macOS and most Linux |

PostgreSQL itself is **not** installed on your machine: it runs in Docker (`postgres:19-alpine`).
Chromium is downloaded by Playwright in step 8.

Docker must be running (Docker Desktop started, or `sudo systemctl start docker`) before
step 4.

## 3. Environment variables

Create your `.env` from the documented example:

```bash
cp .env.example .env
```

Set a database password. This command puts a random password into both `POSTGRES_PASSWORD`
and `DATABASE_URL` (it works with both macOS and Linux `sed`):

```bash
PW=$(openssl rand -hex 16) && sed -i.bak "s/change_me/$PW/g" .env && rm .env.bak
```

Check that the two lines match:

```bash
grep -E '^(POSTGRES_PASSWORD|DATABASE_URL)=' .env
```

`.env` is git-ignored; never commit it. Every setting is explained in `.env.example`. The ones
you are most likely to change:

| Variable | Default | When to change it |
|---|---|---|
| `POSTGRES_PASSWORD` | `change_me` | Always (done above). The same password must appear in `DATABASE_URL`. |
| `DATABASE_URL` | `postgresql+asyncpg://jobhunter:<password>@localhost:5432/jobhunter` | Only if you change the user, the database name or `POSTGRES_PORT` |
| `POSTGRES_PORT` | 5432 | If another PostgreSQL already uses port 5432 on your machine (then use the same port in `DATABASE_URL`) |
| `ANTHROPIC_API_KEY` | empty | Optional. Without it everything is rule-based and free. With it, set a spend cap in the Anthropic Console. |
| `AUTOMATION_HEADLESS` | `true` | Set `false` to see the browser fill application forms (needed to solve a CAPTCHA) |
| `AUTOMATION_BROWSER_PATH` | unset | Only to use a Chromium or Chrome you already have instead of Playwright's |
| `DISCOVERY_INTERVAL_MINUTES` | 360 | How often scheduled discovery re-crawls your boards |

Leave `AUTH_MODE=none`, `BACKEND_HOST=127.0.0.1`, `ALLOWED_HOSTS` and `CORS_ORIGINS` as they
are: the app has no login and must only be reachable from your own machine (DEPLOYMENT.md,
section 4).

The backend reads `.env` when it starts: restart it after changing anything.

## 4. Start PostgreSQL

```bash
docker compose up -d --wait db
```

This starts PostgreSQL 19 on `127.0.0.1:5432` with its data in the Docker volume
`ai-job-hunter_pgdata19`. Check it:

```bash
docker compose ps db
```

The status should say `Up ... (healthy)` and the port `127.0.0.1:5432->5432/tcp`. Stop it with `docker compose stop db`. The data is kept;
only `docker compose down -v` deletes it.

## 5. Run migrations

The migration tool lives in the backend's virtual environment, so create it first (this is
also part of step 6):

```bash
python3.14 -m venv backend/.venv
```

```bash
backend/.venv/bin/pip install -r backend/requirements-dev.txt
```

Then apply every migration:

```bash
source backend/.venv/bin/activate
```

```bash
./scripts/init_db.sh
```

Check the result. It should print `0008 (head)`:

```bash
./scripts/init_db.sh current
```

`init_db.sh` reads `DATABASE_URL` from `.env`; with no arguments it runs `alembic upgrade head`,
and any arguments are passed to `alembic`.

## 6. Start the backend

In a terminal, from the repository root, with the virtual environment from step 5:

```bash
cd backend && source .venv/bin/activate && python -m app
```

It listens on http://127.0.0.1:8000, always with one worker (the scheduler runs inside
it) and auto-reloads Python changes. Stop it with Ctrl+C. API docs:
http://127.0.0.1:8000/api/v1/docs.

## 7. Start the frontend

In a second terminal, from the repository root:

```bash
cd frontend && npm ci
```

```bash
npm run dev
```

Open http://localhost:3000. `npm ci` is needed only the first time and after
`package-lock.json` changes.

## 8. Install Playwright's Chromium (for application automation)

The Playwright Python package is installed with the backend requirements (step 5). Its
browser is a separate, one-time download:

```bash
backend/.venv/bin/python -m playwright install chromium
```

On **Linux** only, also install Chromium's system libraries (asks for your password):

```bash
sudo backend/.venv/bin/python -m playwright install-deps chromium
```

Check that the browser starts:

```bash
backend/.venv/bin/python -c "
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        print('Chromium', b.version, 'OK')
        await b.close()
asyncio.run(main())"
```

Without Chromium everything works except filling application forms.

## 9. First-time setup in one command

After steps 1–3, with Docker running:

```bash
./scripts/dev.sh
```

It checks Docker, `python3.14` and Node 26, starts PostgreSQL (step 4), creates the virtual
environment and installs the backend requirements, downloads Chromium (step 8; a failed
download prints a warning and the app starts anyway), runs the migrations (step 5), installs
the frontend packages, and starts the backend (step 6) and the frontend (step 7). The first
run takes a few minutes; later runs take seconds and reinstall only what changed. If the
first run is interrupted, run it again: it picks up where it stopped.

When it prints `Ctrl+C to stop.`, open http://localhost:3000. Ctrl+C stops the backend and
the frontend; PostgreSQL keeps running (`docker compose stop db`).

Then:
1. Fill in **Settings** (http://localhost:3000/settings): locations, salary, work
   authorization, sponsorship, relocation. Answers that need these are otherwise marked
   "needs your input".
2. Make your first backup and schedule daily ones: [BACKUP_AND_RECOVERY.md](BACKUP_AND_RECOVERY.md).
3. Follow [LOCAL_VALIDATION_CHECKLIST.md](LOCAL_VALIDATION_CHECKLIST.md).

## 10. Verify everything is working

With the app running (step 9), in another terminal:

| Check | Command | Expected |
|---|---|---|
| Backend alive | `curl -s http://127.0.0.1:8000/health` | `{"status":"ok","version":"0.10.0",...}` |
| Database, migrations, scheduler | `curl -s http://127.0.0.1:8000/health/ready` | `"status":"ready"`, `"migrations":{"ok":true,"detail":"0008"}`, `"scheduler":{"ok":true,"detail":"running"}` |
| Mode and auth | `curl -s http://127.0.0.1:8000/api/v1/system/info` | `"auth_mode":"none"`, `"scheduler_running":true` |
| Automation | `curl -s http://127.0.0.1:8000/api/v1/automation/status` | `"enabled":true`, `"mode":"APPROVAL_MODE"`, `"autonomous_available":false` |
| Frontend | `curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/` | `200` |
| Local-only guard | `curl -s -H "Host: example.com" http://127.0.0.1:8000/health` | `{"error": {"code": "host_not_allowed", ...}}` |
| Chromium | the check in step 8 | `Chromium <version> OK` |

In the browser, http://localhost:3000 shows the Analytics dashboard with "0 submitted
application(s) so far", and the Activity page lists agent runs once you start using the app.

Optional, the full test suite (needs a throwaway database; the tests drop tables). Create
it once:

```bash
docker compose exec db createdb -U jobhunter jobhunter_test
```

Then, from `backend/` with the virtual environment active, replacing `<password>` with your
`POSTGRES_PASSWORD`:

```bash
TEST_DATABASE_URL=postgresql+psycopg2://jobhunter:<password>@localhost:5432/jobhunter_test pytest
```

Never point `TEST_DATABASE_URL` at your real database. More in [docs/TESTING.md](docs/TESTING.md).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `dev.sh`: `python3.14 not found on PATH` | Install Python 3.14 (step 2). With `uv`, add `~/.local/bin` to your `PATH`. |
| `dev.sh`: `Node NN found; Node 26 or newer is required` | `nvm install 26 && nvm use 26` |
| `dev.sh`: `Docker is not running` | Start Docker Desktop (or `sudo systemctl start docker`) |
| `port is already allocated` for 5432 | Another PostgreSQL is running. Stop it, or set `POSTGRES_PORT=5433` in `.env` and use `:5433` in `DATABASE_URL`. |
| Port 8000 or 3000 already in use | Stop the other process (`lsof -i :8000`), or an old `dev.sh` still running |
| Backend fails with `password authentication failed` | The database volume was created with another password. Put the old password back in `.env`, or (losing the data) `docker compose down -v` and start again. |
| `warning: Chromium download failed` | Network or proxy blocked the download. Run the command in step 8 again when online; the rest of the app works meanwhile. |
| Linux: Chromium fails with missing `.so` libraries | Run the `install-deps` command in step 8. |
| Browser shows "Cannot reach the backend" | The backend is not running or not ready: check `curl -s http://127.0.0.1:8000/health/ready` and the backend's terminal output. |
| `{"error":{"code":"host_not_allowed"}}` in the browser | Open the app as http://localhost:3000, not by IP or another name. |
| A change to `.env` has no effect | Restart the backend (Ctrl+C, then `./scripts/dev.sh`). |
