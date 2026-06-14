# Corroborate

Early work in progress.

An experiment in scoring how much we should trust that a reported event actually
happened — by checking whether multiple *independent* sources corroborate it in
space and time, instead of taking any single report at face value.

Starting with earthquakes, because USGS publishes free, exact ground truth to
check a confidence score against before pointing this at messier domains.

## Status

Scaffolding: project structure, configuration, the `Claim` / `Event` data model,
and the DuckDB schema. Ingest and scoring come next — see [docs/BUILD.md](docs/BUILD.md)
for the full design.

## Layout

- `src/corroborate/` — library: `config`, `models`, `db`, `ingest/`
- `docs/BUILD.md` — design document
