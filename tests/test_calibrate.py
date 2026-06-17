"""Tests for the scoring/calibration core (docs/BUILD.md §4.5-4.6).

Live USGS+EMSC data lacks false candidates (both networks are authoritative), so
a meaningful reliability curve needs the noisy social layer (M6). These tests use
a synthetic labeled set to prove the machinery is correct."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from corroborate.calibrate import evaluate_and_train
from corroborate.cluster import cluster_claims
from corroborate.models import Claim
from corroborate.score import FEATURE_NAMES, feature_row

T0 = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


def _claim(cid, lat, lon, mag, dt_min=0.0, text="quake near here today"):
    return Claim(
        claim_id=cid, source_id="emsc", source_type="seismic_network",
        ingested_at=T0, event_time=T0 + timedelta(minutes=dt_min),
        lat=lat, lon=lon, magnitude=mag, raw_text=text,
    )


def test_feature_row_has_all_names():
    ce = cluster_claims([_claim("a", 10.0, 10.0, 4.2)])[0]
    row = feature_row(ce.event, [_claim("a", 10.0, 10.0, 4.2)])
    assert set(row) == set(FEATURE_NAMES)
    assert row["max_magnitude"] == 4.2
    assert row["n_independent"] == 1.0


def test_calibration_recovers_signal():
    # Build a separable synthetic set: high-magnitude => more likely "real".
    rng = np.random.RandomState(0)
    n = 400
    mag = rng.uniform(1.0, 6.0, n)
    p = 1.0 / (1.0 + np.exp(-(mag - 3.5)))  # logistic in magnitude
    y = (rng.uniform(size=n) < p).astype(int)
    # 7 features; only max_magnitude (index 6) carries signal, rest are noise.
    X = rng.normal(size=(n, len(FEATURE_NAMES)))
    X[:, 6] = mag
    times = np.arange(n, dtype=float)

    m = evaluate_and_train(X, y, times)
    assert m["model"] is not None
    assert 0.0 <= m["brier"] <= 0.25          # better than a coin flip (~0.25)
    assert m["pr_auc"] > 0.7                    # recovers the magnitude signal
    # calibrated probabilities stay in range
    probs = m["model"].predict_proba(X)[:, 1]
    assert probs.min() >= 0.0 and probs.max() <= 1.0


def test_single_class_returns_no_model():
    X = np.random.RandomState(1).normal(size=(20, len(FEATURE_NAMES)))
    y = np.zeros(20, dtype=int)
    m = evaluate_and_train(X, y, np.arange(20, dtype=float))
    assert m["model"] is None
