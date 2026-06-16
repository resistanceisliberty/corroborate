"""Central configuration. See docs/BUILD.md for rationale."""

from __future__ import annotations

from pathlib import Path

# --- paths ---
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "corroborate.duckdb"

# --- spatio-temporal clustering (ST-DBSCAN) ---
EPS_SPACE_KM = 100.0
EPS_TIME_MIN = 30.0
MIN_SAMPLES = 2

# --- dedup / independence ---
NEAR_DUP_JACCARD = 0.80
MINHASH_PERMS = 128
SHINGLE_SIZE = 3

# --- sources ---
USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
EMSC_FEED = "https://www.seismicportal.eu/fdsnws/event/1/query?format=json&limit=200"
