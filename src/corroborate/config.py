"""Central configuration. See docs/BUILD.md for rationale."""

from __future__ import annotations

from pathlib import Path

# --- paths ---
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "corroborate.duckdb"
