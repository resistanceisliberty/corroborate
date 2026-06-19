"""Cluster recent claims into candidate events and persist them.

Usage: uv run python scripts/run_cluster.py

Windowed + self-pruning (see corroborate.cluster.cluster_window); prints a summary
by corroboration level.
"""

from __future__ import annotations

from corroborate import config, db
from corroborate.cluster import cluster_window


def main() -> None:
    db.init_db()
    con = db.connect()
    try:
        s = cluster_window(con)
        win = "all claims" if s["cutoff"] is None else f"since {s['cutoff'].isoformat()}"
        print(f"{s['n_claims']} claims ({win}) -> {s['n_events']} candidate events")
        print(f"  multi-claim clusters: {s['multi']}")
        print(f"  multi-independent-source (corroborated): {s['corroborated']}")
        if s["pruned"]:
            print(f"  pruned {s['pruned']} claims older than {config.CLAIM_RETENTION_HOURS:.0f}h")
    finally:
        con.close()


if __name__ == "__main__":
    main()
