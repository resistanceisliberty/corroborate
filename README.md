# Corroborate

Early work in progress.

An experiment in scoring how much we should trust that a reported event actually
happened — by checking whether multiple *independent* sources corroborate it in
space and time, instead of taking any single report at face value.

Starting with earthquakes, because USGS publishes free, exact ground truth to
check a confidence score against before pointing this at messier domains.

## Status

Ingesting two independent seismic networks (USGS + EMSC), then clustering the
claims in space and time into candidate events. Reposts of the same wire are
collapsed by MinHash so corroboration counts *independent* sources, not raw
report volume. Scoring against ground truth comes next — see
[docs/BUILD.md](docs/BUILD.md).

## Run

```bash
uv sync
uv run python scripts/run_ingest.py    # poll USGS + EMSC into claims
uv run python scripts/run_cluster.py   # cluster claims into candidate events
```

## Layout

- `src/corroborate/` — library: `config`, `models`, `db`, `ingest/`
- `scripts/` — operational entry points
- `docs/BUILD.md` — design document
