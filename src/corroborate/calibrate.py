"""Train + calibrate the scorer against USGS ground truth (docs/BUILD.md §4.6).

Label each candidate event positive iff a held-out USGS ground_truth event lies
within config.GT_MATCH_DIST_KM and config.GT_MATCH_TIME_MIN. Split by time, fit a
StandardScaler+LogisticRegression pipeline wrapped in CalibratedClassifierCV, and
report the reliability diagram (the money plot), Brier score, and PR-AUC.

`evaluate_and_train(X, y, times)` is the pure core (used by tests with synthetic
data). `train_and_calibrate()` pulls live events from DuckDB and persists the
model + scores + reliability artifacts.
"""

from __future__ import annotations

import pickle

import numpy as np
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from . import config, db
from .models import Claim, Event
from .score import FEATURE_NAMES, feature_vector, load_model
from .util import haversine_km


# --------------------------------------------------------------------------- #
# DB assembly + labeling
# --------------------------------------------------------------------------- #
def load_events_with_claims(con) -> list[tuple[Event, list[Claim]]]:
    ccols = [
        "claim_id", "source_id", "source_type", "external_id", "ingested_at",
        "event_time", "time_uncertainty_s", "lat", "lon", "loc_uncertainty_km",
        "magnitude", "raw_text",
    ]
    claims: dict[str, Claim] = {}
    for row in con.execute(f"SELECT {', '.join(ccols)} FROM claims").fetchall():
        d = dict(zip(ccols, row))
        d["claim_id"] = str(d["claim_id"])
        claims[d["claim_id"]] = Claim(**d)

    members: dict[str, list[Claim]] = {}
    for eid, cid in con.execute("SELECT event_id, claim_id FROM event_claims").fetchall():
        c = claims.get(str(cid))
        if c is not None:
            members.setdefault(str(eid), []).append(c)

    ecols = [
        "event_id", "centroid_lat", "centroid_lon", "est_time", "first_seen",
        "last_updated", "n_claims", "n_independent", "n_source_types", "score",
        "refutation_flag", "status",
    ]
    out: list[tuple[Event, list[Claim]]] = []
    for row in con.execute(f"SELECT {', '.join(ecols)} FROM events").fetchall():
        d = dict(zip(ecols, row))
        d["event_id"] = str(d["event_id"])
        ev = Event(**d)
        out.append((ev, members.get(ev.event_id, [])))
    return out


def _ground_truth(con) -> list[tuple[float, float, float]]:
    rows = con.execute("SELECT lat, lon, event_time FROM ground_truth").fetchall()
    return [(lat, lon, t.timestamp()) for lat, lon, t in rows]


def _is_confirmed(ev: Event, gt: list[tuple[float, float, float]]) -> int:
    et = ev.est_time.timestamp()
    for lat, lon, t in gt:
        if abs(et - t) <= config.GT_MATCH_TIME_MIN * 60.0 and (
            haversine_km(ev.centroid_lat, ev.centroid_lon, lat, lon) <= config.GT_MATCH_DIST_KM
        ):
            return 1
    return 0


# --------------------------------------------------------------------------- #
# Pure training/eval core
# --------------------------------------------------------------------------- #
def _reliability(y_true: np.ndarray, prob: np.ndarray) -> list[tuple[float, float, int]]:
    """Return (mean_predicted, observed_fraction, count) per bin with data.

    Uses quantile edges so the diagram stays legible when predicted probabilities
    are compressed into a narrow range (common with low base rates).
    """
    edges = np.unique(np.quantile(prob, np.linspace(0.0, 1.0, config.RELIABILITY_BINS + 1)))
    if len(edges) < 2:
        return [(float(prob.mean()), float(y_true.mean()), len(prob))]
    idx = np.clip(np.digitize(prob, edges[1:-1]), 0, len(edges) - 2)
    out = []
    for b in range(len(edges) - 1):
        mask = idx == b
        n = int(mask.sum())
        if n:
            out.append((float(prob[mask].mean()), float(y_true[mask].mean()), n))
    return out


def evaluate_and_train(X: np.ndarray, y: np.ndarray, times: np.ndarray) -> dict:
    """Time-split, train a calibrated model, return metrics + a model fit on all data."""
    order = np.argsort(times)
    X, y = X[order], y[order]
    split = max(1, int(len(X) * 0.7))
    Xtr, Xte, ytr, yte = X[:split], X[split:], y[:split], y[split:]

    def _fit(Xf, yf):
        base = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        # sigmoid (Platt) is robust on small data; cv folds need both classes.
        folds = min(3, int(np.bincount(yf.astype(int)).min())) if len(np.unique(yf)) > 1 else 0
        if folds >= 2:
            model = CalibratedClassifierCV(base, method="sigmoid", cv=folds)
        else:
            model = base
        model.fit(Xf, yf)
        return model

    metrics: dict = {"n_total": int(len(X)), "n_positive": int(y.sum())}

    eval_model = _fit(Xtr, ytr) if len(np.unique(ytr)) > 1 else None
    if eval_model is not None and len(yte):
        prob = eval_model.predict_proba(Xte)[:, 1]
        metrics["brier"] = float(brier_score_loss(yte, prob))
        if len(np.unique(yte)) > 1:
            metrics["pr_auc"] = float(average_precision_score(yte, prob))
            ct, cp = calibration_curve(yte, prob, n_bins=config.RELIABILITY_BINS, strategy="uniform")
            metrics["calibration_curve"] = list(zip(cp.tolist(), ct.tolist()))
        metrics["reliability_bins"] = _reliability(yte, prob)

    # Final model for serving: trained on ALL labeled data.
    metrics["model"] = _fit(X, y) if len(np.unique(y)) > 1 else None
    return metrics


# --------------------------------------------------------------------------- #
# Live entry points
# --------------------------------------------------------------------------- #
def _write_scores(con, events: list[tuple[Event, list[Claim]]], model) -> None:
    """Write calibrated P(real) (and status 'scored') back to each event."""
    for ev, claims in events:
        p = float(model.predict_proba(np.array([feature_vector(ev, claims)]))[0, 1])
        con.execute(
            "UPDATE events SET score = ?, status = 'scored' WHERE event_id = ?",
            [p, ev.event_id],
        )


def score_current_events(con) -> int:
    """Score every current event with the *persisted* model — no retraining.

    Clustering rebuilds events as unscored candidates each cycle, but training is
    the expensive step and only runs occasionally. The live loop calls this between
    retrains to refresh P(real) cheaply. Returns the number of events scored.
    """
    events = load_events_with_claims(con)
    if not events:
        return 0
    _write_scores(con, events, load_model())
    return len(events)


def _write_artifacts(metrics: dict) -> None:
    bins = metrics.get("reliability_bins") or []
    lines = ["mean_predicted,observed_fraction,count"]
    lines += [f"{mp:.4f},{of:.4f},{n}" for mp, of, n in bins]
    config.RELIABILITY_PATH.write_text("\n".join(lines) + "\n")
    try:  # optional PNG if matplotlib is available (extra: viz)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if bins:
            mp = [b[0] for b in bins]
            of = [b[1] for b in bins]
            fig, ax = plt.subplots(figsize=(5, 5))
            ax.plot([0, 1], [0, 1], "--", color="gray", label="perfect")
            ax.plot(mp, of, "o-", label="model")
            ax.set_xlabel("mean predicted P(real)")
            ax.set_ylabel("observed fraction real")
            ax.set_title("Reliability diagram")
            ax.legend()
            fig.savefig(config.RELIABILITY_PNG, dpi=120, bbox_inches="tight")
            plt.close(fig)
    except ImportError:
        pass


def train_and_calibrate() -> dict:
    db.init_db()
    con = db.connect()
    try:
        events = load_events_with_claims(con)
        if not events:
            print("no events — run scripts/run_cluster.py first")
            return {}
        gt = _ground_truth(con)

        X = np.array([feature_vector(ev, claims) for ev, claims in events], dtype=float)
        y = np.array([_is_confirmed(ev, gt) for ev, _ in events], dtype=int)
        times = np.array([ev.est_time.timestamp() for ev, _ in events], dtype=float)

        print(f"labeled {len(y)} events; positives (USGS-confirmed): {int(y.sum())}")
        if int(y.sum()) < config.MIN_CALIBRATION_POSITIVES:
            print(
                f"WARNING: < {config.MIN_CALIBRATION_POSITIVES} positives — reliability "
                "curve will be noisy. (Needs the noisy social layer, M6, for a meaningful "
                "mix of true/false candidates.)"
            )
        if len(np.unique(y)) < 2:
            print("only one class present — cannot train a classifier. Aborting.")
            return {"n_total": int(len(y)), "n_positive": int(y.sum())}

        metrics = evaluate_and_train(X, y, times)
        model = metrics.pop("model", None)
        if model is None:
            print("training produced no model.")
            return metrics

        with open(config.MODEL_PATH, "wb") as fh:
            pickle.dump(model, fh)

        # Write calibrated scores back to events.
        _write_scores(con, events, model)

        _write_artifacts(metrics)

        print(f"features: {FEATURE_NAMES}")
        if "brier" in metrics:
            print(f"Brier score (test): {metrics['brier']:.4f}")
        if "pr_auc" in metrics:
            print(f"PR-AUC (test): {metrics['pr_auc']:.4f}")
        print(f"model saved -> {config.MODEL_PATH}")
        print(f"reliability -> {config.RELIABILITY_PATH}")
        return metrics
    finally:
        con.close()


if __name__ == "__main__":
    train_and_calibrate()
