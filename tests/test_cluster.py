"""Tests for ST-DBSCAN candidate-event clustering (docs/BUILD.md §4.4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from corroborate.cluster import cluster_claims
from corroborate.models import Claim

T0 = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)


def _claim(cid, source_id, lat, lon, *, dt_min=0.0, text="quake", stype="seismic_network"):
    return Claim(
        claim_id=cid,
        source_id=source_id,
        source_type=stype,
        ingested_at=T0,
        event_time=T0 + timedelta(minutes=dt_min),
        lat=lat,
        lon=lon,
        raw_text=text,
    )


def test_close_in_spacetime_merge():
    # Two sources, ~10 km and 5 min apart -> one corroborated event.
    claims = [
        _claim("a", "usgs", 34.0, -118.0, dt_min=0, text="quake near los angeles area"),
        _claim("b", "emsc", 34.05, -118.0, dt_min=5, text="seismic event southern california"),
    ]
    events = cluster_claims(claims)
    assert len(events) == 1
    e = events[0].event
    assert e.n_claims == 2
    assert e.n_independent == 2.0
    assert e.n_source_types == 1


def test_far_apart_split():
    # Same time, opposite sides of the planet -> two separate events.
    claims = [
        _claim("a", "usgs", 34.0, -118.0, text="california quake"),
        _claim("b", "emsc", 35.0, 139.0, text="japan quake"),
    ]
    events = cluster_claims(claims)
    assert len(events) == 2


def test_time_gap_splits_same_place():
    # Same location, but 2 hours apart (> eps_time) -> two events.
    claims = [
        _claim("a", "usgs", 34.0, -118.0, dt_min=0, text="california quake one"),
        _claim("b", "emsc", 34.0, -118.0, dt_min=120, text="california quake two later"),
    ]
    events = cluster_claims(claims)
    assert len(events) == 2


def test_singleton_kept_as_candidate():
    claims = [_claim("a", "usgs", 10.0, 10.0, text="lone quake")]
    events = cluster_claims(claims)
    assert len(events) == 1
    assert events[0].event.n_claims == 1
    assert events[0].event.n_independent == 1.0


def test_reposts_dont_inflate_independence():
    # Three near-identical reposts at one place/time -> 1 event, n_independent ~ 1.
    wire = "BREAKING magnitude six earthquake strikes off the coast right now"
    claims = [
        _claim("x", "x", 34.0, -118.0, dt_min=1, text=wire),
        _claim("y", "x", 34.0, -118.0, dt_min=2, text=wire),
        _claim("z", "bluesky", 34.0, -118.0, dt_min=3, text=wire),
    ]
    events = cluster_claims(claims)
    assert len(events) == 1
    assert events[0].event.n_claims == 3
    assert events[0].event.n_independent == 1.0
