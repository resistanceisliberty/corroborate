"""Central configuration. See docs/BUILD.md for rationale."""

from __future__ import annotations

from pathlib import Path

# --- paths ---
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "corroborate.duckdb"
MODEL_PATH = DATA_DIR / "model.pkl"

# --- spatio-temporal clustering (ST-DBSCAN) ---
EPS_SPACE_KM = 100.0
EPS_TIME_MIN = 30.0
MIN_SAMPLES = 2

# --- dedup / independence ---
NEAR_DUP_JACCARD = 0.80
MINHASH_PERMS = 128
SHINGLE_SIZE = 3

# --- ground-truth matching (USGS) for calibration labels ---
GT_MATCH_DIST_KM = 150.0
GT_MATCH_TIME_MIN = 60.0

# Sources held out as ground-truth labels only (NOT clustered/scored) — avoids
# leaking the label into the features. Everything else is the probabilistic pool.
GROUND_TRUTH_SOURCES: set[str] = {"usgs"}

# --- scoring / calibration ---
SOURCE_PRIOR_DEFAULT = 0.20
RELIABILITY_BINS = 10
MIN_CALIBRATION_POSITIVES = 5  # below this, a reliability curve isn't meaningful
RELIABILITY_PATH = DATA_DIR / "reliability.csv"
RELIABILITY_PNG = DATA_DIR / "reliability.png"

# --- sources ---
# all_day (global, last 24h) overlaps EMSC's window, giving a real mix of
# confirmed/unconfirmed candidates for calibration.
MASTODON_INSTANCE = "https://mastodon.social"  # public tag timeline needs no auth
USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
EMSC_FEED = "https://www.seismicportal.eu/fdsnws/event/1/query?format=json&limit=1000"
GDACS_RSS = "https://www.gdacs.org/xml/rss.xml"

# Per-source reliability priors (hand-set for now; learn from history later).
SOURCE_PRIORS: dict[str, float] = {
    "usgs": 0.99,
    "emsc": 0.97,
    "rss:gdacs": 0.75,
    "mastodon": 0.30,
    "bluesky": 0.30,
    "x": 0.25,  # higher volume than Bluesky, but noisier / more bots
}
