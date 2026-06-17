# Corroborate

Early work in progress.

An experiment in scoring how much we should trust that a reported event actually
happened — by checking whether multiple *independent* sources corroborate it in
space and time, instead of taking any single report at face value.

Starting with earthquakes, because USGS publishes free, exact ground truth to
check a confidence score against before pointing this at messier domains.

## Status

Ingest two independent seismic networks (USGS + EMSC), cluster claims in space and
time (MinHash collapses reposts so corroboration counts *independent* sources), and
score each candidate event with a **calibrated P(real)** — trained against held-out
USGS ground truth and validated with a reliability diagram. See
[docs/BUILD.md](docs/BUILD.md).

## Run

```bash
uv sync
uv run python scripts/run_ingest.py    # poll USGS (truth) + EMSC into claims
uv run python scripts/run_cluster.py   # cluster claims into candidate events
uv run python scripts/train.py         # label vs USGS, calibrate, write scores
```

## Layout

- `src/corroborate/` — library: `config`, `models`, `db`, `ingest/`
- `scripts/` — operational entry points
- `docs/BUILD.md` — design document
