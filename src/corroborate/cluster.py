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
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.cluster import DBSCAN

from . import config
from .dedup import independence_weights
from .models import Claim, Event
from .util import haversine_km

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


def _refutation(members: list[Claim], weights: list[float]) -> bool:
    """True when claims point to contradictory locations (docs/BUILD.md §4.7).

    Find the farthest-apart pair; if it exceeds REFUTE_DIST_KM, assign every claim
    to its nearer extreme and require both ends to carry >= REFUTE_MIN_MASS of the
    independence-weighted mass — so a single stray outlier does not trip the flag.
    """
    n = len(members)
    if n < 3:
        return False  # pairs are always within eps_space; nothing to contradict
    far = 0.0
    a = b = 0
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_km(members[i].lat, members[i].lon, members[j].lat, members[j].lon)
            if d > far:
                far, a, b = d, i, j
    if far <= config.REFUTE_DIST_KM:
        return False
    mass_a = mass_b = 0.0
    for k in range(n):
        da = haversine_km(members[k].lat, members[k].lon, members[a].lat, members[a].lon)
        db = haversine_km(members[k].lat, members[k].lon, members[b].lat, members[b].lon)
        if da <= db:
            mass_a += weights[k]
        else:
            mass_b += weights[k]
    total = mass_a + mass_b or 1.0
    return min(mass_a, mass_b) / total >= config.REFUTE_MIN_MASS


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
        refutation_flag=_refutation(members, weights),
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


# --------------------------------------------------------------------------- #
# DB orchestration for the live loop (caller passes a DuckDB connection)
# --------------------------------------------------------------------------- #
# Clustering is O(n²), so cluster only a rolling window of recent claims (a full
# recompute over all history would OOM a never-ending feed) and prune the rest.

_CLAIM_COLS = [
    "claim_id", "source_id", "source_type", "external_id", "ingested_at",
    "event_time", "time_uncertainty_s", "lat", "lon", "loc_uncertainty_km",
    "magnitude", "raw_text",
]


def _gt_filter() -> tuple[str, list[str]]:
    """SQL predicate + params excluding held-out ground-truth sources (config §2)."""
    gt = list(config.GROUND_TRUTH_SOURCES)
    placeholders = ", ".join("?" for _ in gt) or "''"
    return f"source_id NOT IN ({placeholders})", gt


def window_cutoff(con, window_hours: float) -> datetime | None:
    """Oldest event_time to cluster: most recent clustered claim minus the window.

    Anchoring on the latest claim rather than wall-clock makes the window behave
    identically on a live feed and on a replayed historical dump. Returns None when
    there are no clusterable claims yet.
    """
    where, params = _gt_filter()
    anchor = con.execute(
        f"SELECT max(event_time) FROM claims WHERE {where}", params
    ).fetchone()[0]
    if anchor is None:
        return None
    return anchor - timedelta(hours=window_hours)


def _load_window(con, cutoff: datetime | None) -> list[Claim]:
    """Load clusterable claims (ground truth held out) at/after the window cutoff."""
    where, params = _gt_filter()
    if cutoff is not None:
        where += " AND event_time >= ?"
        params = [*params, cutoff]
    rows = con.execute(
        f"SELECT {', '.join(_CLAIM_COLS)} FROM claims WHERE {where}", params
    ).fetchall()
    claims = []
    for row in rows:
        data = dict(zip(_CLAIM_COLS, row))
        data["claim_id"] = str(data["claim_id"])  # DuckDB returns UUID objects
        claims.append(Claim(**data))
    return claims


def _persist(con, cutoff: datetime | None, clustered: list[ClusteredEvent]) -> None:
    """Replace the events inside the window; leave older (retained) events untouched."""
    if cutoff is None:
        con.execute("DELETE FROM event_claims")
        con.execute("DELETE FROM events")
    else:
        con.execute(
            "DELETE FROM event_claims WHERE event_id IN "
            "(SELECT event_id FROM events WHERE est_time >= ?)",
            [cutoff],
        )
        con.execute("DELETE FROM events WHERE est_time >= ?", [cutoff])
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


def prune(con, retention_hours: float) -> int:
    """Drop claims / events / ground truth older than the retention horizon.

    Anchored on the most recent claim, like the cluster window. Returns the number
    of claims pruned.
    """
    anchor = con.execute("SELECT max(event_time) FROM claims").fetchone()[0]
    if anchor is None:
        return 0
    cutoff = anchor - timedelta(hours=retention_hours)
    con.execute(
        "DELETE FROM event_claims WHERE event_id IN "
        "(SELECT event_id FROM events WHERE est_time < ?)",
        [cutoff],
    )
    con.execute("DELETE FROM events WHERE est_time < ?", [cutoff])
    n = con.execute("SELECT count(*) FROM claims WHERE event_time < ?", [cutoff]).fetchone()[0]
    con.execute("DELETE FROM claims WHERE event_time < ?", [cutoff])
    con.execute("DELETE FROM ground_truth WHERE event_time < ?", [cutoff])
    return int(n)


def cluster_window(
    con, window_hours: float | None = None, retention_hours: float | None = None
) -> dict:
    """Cluster the rolling window, persist its events, prune past retention.

    The one entry point the live loop calls each cycle. Returns a summary dict so
    callers can log it.
    """
    if window_hours is None:
        window_hours = config.CLUSTER_WINDOW_HOURS
    if retention_hours is None:
        retention_hours = config.CLAIM_RETENTION_HOURS

    cutoff = window_cutoff(con, window_hours)
    claims = _load_window(con, cutoff)
    clustered = cluster_claims(claims)
    _persist(con, cutoff, clustered)
    pruned = prune(con, retention_hours)
    return {
        "n_claims": len(claims),
        "n_events": len(clustered),
        "multi": sum(1 for ce in clustered if ce.event.n_claims > 1),
        "corroborated": sum(1 for ce in clustered if ce.event.n_independent > 1),
        "pruned": pruned,
        "cutoff": cutoff,
    }
