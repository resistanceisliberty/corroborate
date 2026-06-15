"""Poll USGS and write claims (+ ground_truth) to DuckDB.

Usage: uv run python scripts/run_ingest.py

USGS is both a claim source and our authoritative catalog, so each event is
written to `claims` and mirrored into `ground_truth`. Dedup-on-write by
(source_id, external_id).
"""

from __future__ import annotations

import json

from corroborate import db
from corroborate.ingest.usgs import USGSPoller


def _insert_claim(con, c) -> bool:
    if c.external_id:
        exists = con.execute(
            "SELECT 1 FROM claims WHERE source_id = ? AND external_id = ?",
            [c.source_id, c.external_id],
        ).fetchone()
        if exists:
            return False
    con.execute(
        """INSERT INTO claims (claim_id, source_id, source_type, external_id,
               ingested_at, event_time, time_uncertainty_s, lat, lon,
               loc_uncertainty_km, magnitude, raw_text, raw_json, content_hash)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            c.claim_id, c.source_id, c.source_type, c.external_id,
            c.ingested_at, c.event_time, c.time_uncertainty_s, c.lat, c.lon,
            c.loc_uncertainty_km, c.magnitude, c.raw_text,
            json.dumps(c.raw_json), c.content_hash,
        ],
    )
    return True


def _mirror_ground_truth(con, c) -> None:
    con.execute(
        """INSERT INTO ground_truth (gt_id, event_time, lat, lon, magnitude, raw_json)
           VALUES (?,?,?,?,?,?) ON CONFLICT (gt_id) DO NOTHING""",
        [c.external_id, c.event_time, c.lat, c.lon, c.magnitude,
         json.dumps(c.raw_json)],
    )


def main() -> None:
    db.init_db()
    con = db.connect()
    try:
        inserted = 0
        for claim in USGSPoller().fetch():
            if _insert_claim(con, claim):
                inserted += 1
            _mirror_ground_truth(con, claim)
        print(f"usgs: inserted {inserted} new claims")
    finally:
        con.close()


if __name__ == "__main__":
    main()
