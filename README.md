# Corroborate

Early work in progress.

An experiment in scoring how much we should trust that a reported event actually
happened — by checking whether multiple *independent* sources corroborate it in
space and time, instead of taking any single report at face value.

Starting with earthquakes, because USGS publishes free, exact ground truth to
check a confidence score against before pointing this at messier domains.

## Status

Ingest authoritative seismic networks (USGS + EMSC) **and social posts** (Mastodon
live; Bluesky/X behind credentials), geoparse the social text, cluster everything in
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
uv run python scripts/run_cluster.py   # cluster claims into candidate events
uv run python scripts/train.py         # label vs USGS, calibrate, write scores
uv run uvicorn corroborate.api:app     # serve map + API at http://127.0.0.1:8000/
```

Optional social credentials (env vars): `BLUESKY_IDENTIFIER` + `BLUESKY_APP_PASSWORD`, `X_BEARER_TOKEN`.

## Layout

- `src/corroborate/` — library: `config`, `models`, `db`, `ingest/`, `api`
- `scripts/` — operational entry points
- `web/` — MapLibre frontend
- `docs/BUILD.md` — design document
