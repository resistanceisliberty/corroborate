# Corroborate

Early work in progress.

An experiment in scoring how much we should trust that a reported event actually
happened — by checking whether multiple *independent* sources corroborate it in
space and time, instead of taking any single report at face value.

Starting with earthquakes, because USGS publishes free, exact ground truth to
check a confidence score against before pointing this at messier domains.

## Status

Ingesting two independent seismic networks — USGS (also mirrored into a
`ground_truth` catalog for later calibration) and EMSC. Each source runs in
isolation, so one feed failing doesn't abort the rest. Clustering and scoring
come next — see [docs/BUILD.md](docs/BUILD.md).

## Run

```bash
uv sync
uv run python scripts/run_ingest.py
```

## Layout

- `src/corroborate/` — library: `config`, `models`, `db`, `ingest/`
- `scripts/` — operational entry points
- `docs/BUILD.md` — design document
