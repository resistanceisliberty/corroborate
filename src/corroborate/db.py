"""DuckDB connection + schema. Runnable: `init_db()` creates the file + tables."""

from __future__ import annotations

import duckdb

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id            UUID PRIMARY KEY,
    source_id           TEXT,
    source_type         TEXT,
    external_id         TEXT,
    ingested_at         TIMESTAMP,
    event_time          TIMESTAMP,
    time_uncertainty_s  DOUBLE,
    lat                 DOUBLE,
    lon                 DOUBLE,
    loc_uncertainty_km  DOUBLE,
    magnitude           DOUBLE,
    raw_text            TEXT,
    raw_json            JSON
);

-- Authoritative catalog (USGS) used later as calibration labels.
CREATE TABLE IF NOT EXISTS ground_truth (
    gt_id               TEXT PRIMARY KEY,
    event_time          TIMESTAMP,
    lat                 DOUBLE,
    lon                 DOUBLE,
    magnitude           DOUBLE,
    raw_json            JSON
);

-- Candidate events = clusters of claims.
CREATE TABLE IF NOT EXISTS events (
    event_id            UUID PRIMARY KEY,
    centroid_lat        DOUBLE,
    centroid_lon        DOUBLE,
    est_time            TIMESTAMP,
    first_seen          TIMESTAMP,
    last_updated        TIMESTAMP,
    n_claims            INTEGER,
    n_independent       DOUBLE,
    n_source_types      INTEGER,
    score               DOUBLE,
    refutation_flag     BOOLEAN,
    status              TEXT
);

CREATE TABLE IF NOT EXISTS event_claims (
    event_id            UUID,
    claim_id            UUID,
    weight              DOUBLE
);
"""


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(config.DB_PATH), read_only=read_only)


def init_db() -> None:
    """Create the database file and all tables (idempotent)."""
    con = connect()
    try:
        con.execute(_SCHEMA)
        print(f"initialized schema at {config.DB_PATH}")
    finally:
        con.close()


if __name__ == "__main__":
    init_db()
