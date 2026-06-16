"""Spatio-temporal matching (ST-DBSCAN) — claims -> candidate events.

A combined metric: two claims are neighbors only if within BOTH eps_space (km)
and eps_time (min). We encode that as a precomputed distance matrix (haversine
km, set to +inf when the time gap exceeds eps_time) and run DBSCAN with
eps=eps_space. Defaults in config: EPS_SPACE_KM, EPS_TIME_MIN, MIN_SAMPLES.

Singletons (DBSCAN noise) are kept as their own one-claim candidate events — an
uncorroborated claim is still a candidate; it just scores low. Each cluster's
independence weights come from dedup.independence_weights.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from sklearn.cluster import DBSCAN

from . import config
from .dedup import independence_weights
from .models import Claim, Event

_EARTH_R_KM = 6371.0088


@dataclass
class ClusteredEvent:
    """A candidate event plus the claims that compose it and their weights."""

    event: Event
    claim_ids: list[str]
    weights: list[float]


def _haversine_km(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    lat = np.radians(lats)
    lon = np.radians(lons)
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
    return 2 * _EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _labels(claims: list[Claim]) -> np.ndarray:
    """ST-DBSCAN labels; noise points (-1) are reassigned to unique singletons."""
    lats = np.array([c.lat for c in claims], dtype=float)
    lons = np.array([c.lon for c in claims], dtype=float)
    times = np.array([c.event_time.timestamp() for c in claims], dtype=float)

    dist = _haversine_km(lats, lons)
    tgap = np.abs(times[:, None] - times[None, :])
    dist[tgap > config.EPS_TIME_MIN * 60.0] = np.inf
    # DBSCAN needs finite distances; use a sentinel just above eps.
    sentinel = config.EPS_SPACE_KM * 10.0 + 1.0
    dist[~np.isfinite(dist)] = sentinel

    labels = DBSCAN(
        eps=config.EPS_SPACE_KM,
        min_samples=config.MIN_SAMPLES,
        metric="precomputed",
    ).fit_predict(dist)

    next_label = (labels.max() + 1) if labels.size and labels.max() >= 0 else 0
    for i in range(len(labels)):
        if labels[i] == -1:
            labels[i] = next_label
            next_label += 1
    return labels


def _build_event(members: list[Claim]) -> ClusteredEvent:
    weights, n_independent = independence_weights(members)
    w = np.array(weights, dtype=float)
    wsum = w.sum() or 1.0

    lats = np.array([c.lat for c in members], dtype=float)
    lons = np.array([c.lon for c in members], dtype=float)
    times = np.array([c.event_time.timestamp() for c in members], dtype=float)

    centroid_lat = float((w * lats).sum() / wsum)
    centroid_lon = float((w * lons).sum() / wsum)
    est_time = datetime.fromtimestamp(float((w * times).sum() / wsum), tz=timezone.utc)
    first_seen = min(c.ingested_at for c in members)
    last_updated = max(c.ingested_at for c in members)

    event = Event(
        event_id=str(uuid.uuid4()),
        centroid_lat=centroid_lat,
        centroid_lon=centroid_lon,
        est_time=est_time,
        first_seen=first_seen,
        last_updated=last_updated,
        n_claims=len(members),
        n_independent=n_independent,
        n_source_types=len({c.source_type for c in members}),
        refutation_flag=False,  # TODO: contradiction detection
        status="candidate",
    )
    return ClusteredEvent(event=event, claim_ids=[c.claim_id for c in members], weights=weights)


def cluster_claims(claims: list[Claim]) -> list[ClusteredEvent]:
    """Cluster claims in space-time into candidate events."""
    if not claims:
        return []
    labels = _labels(claims)
    by_label: dict[int, list[Claim]] = {}
    for claim, label in zip(claims, labels):
        by_label.setdefault(int(label), []).append(claim)
    return [_build_event(members) for members in by_label.values()]
