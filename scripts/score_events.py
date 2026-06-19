"""Score the current candidate events with the saved model — without retraining.

Usage: uv run python scripts/score_events.py

Cheap per-cycle scoring between (occasional) retrains; see
corroborate.calibrate.score_current_events.
"""

from __future__ import annotations

from corroborate import config, db
from corroborate.calibrate import score_current_events


def main() -> None:
    db.init_db()
    con = db.connect()
    try:
        if not config.MODEL_PATH.exists():
            print(f"no model at {config.MODEL_PATH} — run scripts/train.py first")
            return
        n = score_current_events(con)
        print(f"scored {n} events" if n else "no events — run scripts/run_cluster.py first")
    finally:
        con.close()


if __name__ == "__main__":
    main()
