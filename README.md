# Corroborate

Early work in progress.

An experiment in scoring how much we should trust that a reported event actually
happened — by checking whether multiple *independent* sources corroborate it in
space and time, instead of taking any single report at face value.

Starting with earthquakes, because USGS publishes free, exact ground truth to
check a confidence score against before pointing this at messier domains.

## Status

Ingest authoritative seismic networks (USGS + EMSC), **social posts** (Mastodon
live; Bluesky/X behind credentials), **and disaster news** (GDACS RSS), geoparse
the social text, cluster everything in
space and time (MinHash collapses reposts so corroboration counts *independent*
sources), score each candidate event with a **calibrated P(real)** — trained against
held-out USGS ground truth and validated with a reliability diagram, flag events
whose claims point to contradictory locations, and serve the scored events as
GeoJSON behind a MapLibre map. See [docs/BUILD.md](docs/BUILD.md).

## Run

```bash
git clone https://github.com/resistanceisliberty/corroborate
cd corroborate
uv sync --extra geoparse               # deps + offline gazetteer for social geoparsing

uv run python scripts/run_ingest.py    # poll USGS (truth) + EMSC + Mastodon into claims
uv run python scripts/run_cluster.py   # cluster recent claims (rolling window) into events
uv run python scripts/train.py         # label vs USGS, calibrate, save model + write scores
uv run uvicorn corroborate.api:app     # serve map + API at http://127.0.0.1:8000/
```

## Social credentials

Mastodon and GDACS need no setup. The other sources are gated on env vars —
unset, they simply contribute nothing:

| source | env vars | where to get them |
|---|---|---|
| Bluesky | `BLUESKY_IDENTIFIER`, `BLUESKY_APP_PASSWORD` | Settings → App Passwords (bsky.app) |
| Reddit | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | create an app at reddit.com/prefs/apps |
| X | `X_BEARER_TOKEN` | developer.x.com (paid tier for recent search) |

For a one-off run, `export` them in your shell. For the scheduled loop, put them in
`data/secrets.env` (gitignored), which `run_cycle.sh` sources:

```sh
BLUESKY_IDENTIFIER=you.bsky.social
BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
X_BEARER_TOKEN=...
```

## Run continuously

`scripts/run_cycle.sh` runs one `ingest → cluster → score` cycle under a lock so
runs never overlap (DuckDB is single-writer; lock + logs live in `data/`).
`run_cluster` keeps only a rolling `CLUSTER_WINDOW_HOURS` window and prunes past
`CLAIM_RETENTION_HOURS`, and `score_events` re-scores from the saved model without
retraining. Schedule with cron — a cycle every 10 min plus a daily recalibration —
using the absolute path to your checkout:

```cron
*/10 * * * * /path/to/corroborate/scripts/run_cycle.sh       >> /path/to/corroborate/data/cycle.log 2>&1
17 3 * * *   /path/to/corroborate/scripts/run_cycle.sh train >> /path/to/corroborate/data/train.log 2>&1
```

(systemd timers work too; cron is the lighter option.)

## Layout

- `src/corroborate/` — library: `config`, `models`, `db`, `ingest/`, `api`
- `scripts/` — operational entry points
- `web/` — MapLibre frontend
- `docs/BUILD.md` — design document
