"""Cluster all claims into candidate events and persist them.

Usage: uv run python scripts/run_cluster.py

Rebuilds the `events` / `event_claims` tables from the current `claims` (a batch
recompute; an incremental version can come later). Prints a summary of the
candidate events by corroboration level.
"""

from __future__ import annotations

from corroborate import db
from corroborate.cluster import cluster_claims
from corroborate.models import Claim


def _load_claims(con) -> list[Claim]:
    cols = [
        "claim_id", "source_id", "source_type", "external_id", "ingested_at",
        "event_time", "time_uncertainty_s", "lat", "lon", "loc_uncertainty_km",
        "magnitude", "raw_text", "content_hash",
    ]
    rows = con.execute(f"SELECT {', '.join(cols)} FROM claims").fetchall()
    claims = []
    for row in rows:
        data = dict(zip(cols, row))
        data["claim_id"] = str(data["claim_id"])  # DuckDB returns UUID objects
        claims.append(Claim(**data))
    return claims


def main() -> None:
    db.init_db()
    con = db.connect()
    try:
        claims = _load_claims(con)
        clustered = cluster_claims(claims)

        con.execute("DELETE FROM event_claims")
        con.execute("DELETE FROM events")
        for ce in clustered:
            e = ce.event
            con.execute(
                """INSERT INTO events (event_id, centroid_lat, centroid_lon, est_time,
                       first_seen, last_updated, n_claims, n_independent,
                       n_source_types, score, refutation_flag, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    e.event_id, e.centroid_lat, e.centroid_lon, e.est_time,
                    e.first_seen, e.last_updated, e.n_claims, e.n_independent,
                    e.n_source_types, e.score, e.refutation_flag, e.status,
                ],
            )
            for claim_id, weight in zip(ce.claim_ids, ce.weights):
                con.execute(
                    "INSERT INTO event_claims (event_id, claim_id, weight) VALUES (?,?,?)",
                    [e.event_id, claim_id, weight],
                )

        total = len(clustered)
        multi = sum(1 for ce in clustered if ce.event.n_claims > 1)
        corr = sum(1 for ce in clustered if ce.event.n_independent > 1)
        print(f"{len(claims)} claims -> {total} candidate events")
        print(f"  multi-claim clusters: {multi}")
        print(f"  multi-independent-source (corroborated): {corr}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
