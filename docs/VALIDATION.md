# Real-world validation: job discovery

CI never calls the real job boards. This is how you check, on your own machine, that
the app discovers real jobs end to end:

1. start the application
2. trigger discovery
3. retrieve real jobs
4. verify they are stored
5. view them in the UI

Needs internet access (to `boards-api.greenhouse.io`, `api.lever.co` /
`api.eu.lever.co` and `api.ashbyhq.com`).

## 1. Start the application

```bash
cp .env.example .env        # first time only: set POSTGRES_PASSWORD (and in DATABASE_URL)
./scripts/dev.sh            # database, migrations, backend :8000, frontend :3000
```

Check: `curl http://127.0.0.1:8000/health/ready` returns `"status":"ready"` with
`"migrations":{"ok":true,"detail":"0003"}`.

## 2–4. Scripted check (one command)

In a second terminal:

```bash
./scripts/validate_discovery.sh
```

It tracks three sample boards (Figma on Greenhouse, Spotify on Lever, Ramp on Ashby),
starts a discovery run, waits for it, prints per-company results, then checks through
the API that jobs are stored and that a job's detail and raw payload are readable. With
`DATABASE_URL` set and `psql` installed it also counts the rows in the database. Pick
other boards with `BOARDS`:

```bash
BOARDS="greenhouse:stripe lever:palantir ashby:linear" ./scripts/validate_discovery.sh
```

Expected output (numbers change daily):

```
==> 4. waiting for the run
    status succeeded in 9.8s: 421 found, 421 new, 0 updated, 0 unchanged, 0 skipped, 0 expired
      ok        greenhouse/figma: 141 found, 141 new
      ok        lever/spotify: 97 found, 97 new
      ok        ashby/ramp: 183 found, 183 new
==> 5. verifying stored jobs
    API: 421 active jobs
    ...
validation passed
```

Run it again: the second run reports the same jobs as **unchanged** and inserts
nothing (deduplication), and `last_seen_at` moves forward while `first_seen_at` stays.

## The same steps by hand

```bash
API=http://127.0.0.1:8000/api/v1
curl -X POST $API/companies -H 'content-type: application/json' -d '{"source":"greenhouse","slug":"figma"}'
curl -X POST $API/discovery/runs                         # -> {"run_id": ..., "task_id": ...}
curl $API/discovery/runs/<run_id>                        # repeat until status != running
curl "$API/jobs?q=engineer&remote_type=remote&limit=5"  # search stored jobs
curl $API/jobs/<job_id>                                  # normalized job
curl $API/jobs/<job_id>/raw                              # exactly what the board returned
curl "$API/discovery/health?probe=true"                  # connector health, live probe
```

Directly in the database:

```bash
docker compose exec db psql -U jobhunter -c \
  "SELECT c.name, count(*), min(j.first_seen_at), max(j.last_seen_at)
   FROM jobs j JOIN companies c ON c.id = j.company_id
   WHERE j.status <> 'expired' GROUP BY c.name ORDER BY 2 DESC"
```

## 5. View them in the UI

- http://localhost:3000/discovery: run discovery, follow the run, run history with
  per-company results, connector health ("Check live"), add/pause/remove companies,
  suggestions.
- http://localhost:3000/jobs: search and filter; open a job for its description,
  requirements, salary, first/last seen, links to the posting, and "Show raw JSON".

## Connector check without the app

```bash
cd backend && source .venv/bin/activate
pytest -m live tests/live      # Figma (Greenhouse), Spotify (Lever), Ramp (Ashby)
```

## If something fails

| Symptom | Cause / fix |
|---|---|
| Adding a board says "No ... job board named" | Wrong board name; copy it from the board's URL. |
| Company shows `not_found` after a crawl | The company moved or closed its board; pause or remove it. |
| Company shows `error` | Network or platform problem; it is retried next run (`consecutive_failures` counts). |
| `409 discovery_in_progress` | A run is already going; wait for it (one at a time). |
| Nothing happens on schedule | `SCHEDULER_ENABLED=false`, or `discovery_enabled` is false (`GET /api/v1/settings`), or no company is due yet. |
