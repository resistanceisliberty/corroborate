#!/usr/bin/env bash
# Run pipeline steps under a lock so runs never overlap (DuckDB is single-writer).
# No args = one ingest -> cluster -> score cycle; pass step names (e.g. `train`) to
# run those instead. Schedule with cron — see the README.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"   # cron's PATH usually lacks uv's dir
cd "$(dirname "$0")/.."
mkdir -p data

steps=("$@")
[ ${#steps[@]} -eq 0 ] && steps=(run_ingest run_cluster score_events)

exec 9>data/pipeline.lock
flock -n 9 || { echo "$(date -Is) busy, skipping ${steps[*]}"; exit 0; }

for step in "${steps[@]}"; do
  echo "$(date -Is) $step"
  uv run python "scripts/$step.py"
done
