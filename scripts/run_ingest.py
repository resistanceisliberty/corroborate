"""Poll sources once and write Claims (+ USGS ground_truth) to DuckDB.

Usage: uv run python scripts/run_ingest.py

M1 status: USGS (ground truth) and EMSC (independent network) are real. Social/
news pollers remain stubs (M6). Each source runs independently — one failing does
not abort the others. Dedup-on-write by (source_id, external_id).
"""

from __future__ import annotations

import json

from corroborate import db
from corroborate.ingest.base import Poller
from corroborate.ingest.bluesky import BlueskyPoller
from corroborate.ingest.emsc import EMSCPoller
from corroborate.ingest.mastodon import MastodonPoller
from corroborate.ingest.usgs import USGSPoller
from corroborate.ingest.x import XPoller


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
               loc_uncertainty_km, magnitude, raw_text, raw_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            c.claim_id, c.source_id, c.source_type, c.external_id,
            c.ingested_at, c.event_time, c.time_uncertainty_s, c.lat, c.lon,
            c.loc_uncertainty_km, c.magnitude, c.raw_text,
            json.dumps(c.raw_json),
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


def _run_poller(con, poller: Poller, *, ground_truth: bool) -> None:
    """Fetch from one source and write claims; isolate failures per source."""
    try:
        inserted = 0
        for claim in poller.fetch():
            if _insert_claim(con, claim):
                inserted += 1
            if ground_truth:
                _mirror_ground_truth(con, claim)
        label = "ground truth" if ground_truth else "probabilistic"
        print(f"{poller.source_id}: inserted {inserted} new claims ({label})")
    except NotImplementedError:
        print(f"{poller.source_id}: skipped (stub)")
    except Exception as exc:  # noqa: BLE001 — one bad source must not abort the run
        print(f"{poller.source_id}: ERROR {type(exc).__name__}: {exc}")


def main() -> None:
    db.init_db()
    con = db.connect()
    try:
        _run_poller(con, USGSPoller(), ground_truth=True)
        _run_poller(con, EMSCPoller(), ground_truth=False)
        _run_poller(con, MastodonPoller(), ground_truth=False)  # unauthenticated
        _run_poller(con, BlueskyPoller(), ground_truth=False)   # needs BLUESKY_* env
        _run_poller(con, XPoller(), ground_truth=False)         # needs X_BEARER_TOKEN
        # TODO M6: RSSPoller (news/disaster)
    finally:
        con.close()


if __name__ == "__main__":
    main()
