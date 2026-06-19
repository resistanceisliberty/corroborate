"""Tests for ST-DBSCAN candidate-event clustering (docs/BUILD.md §4.4)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from corroborate.cluster import cluster_claims, cluster_window
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


def test_refutation_flag_on_overextended_cluster():
    # A density-chained line of claims spanning ~480 km (80 km steps) -> one
    # cluster, but mass at both far ends => contradictory locations.
    claims = [
        _claim(f"c{i}", "emsc", 0.0, i * 0.72, dt_min=i, text=f"quake report number {i} here")
        for i in range(7)
    ]
    events = cluster_claims(claims)
    assert len(events) == 1
    assert events[0].event.refutation_flag is True


def test_no_refutation_on_tight_cluster():
    claims = [
        _claim("a", "usgs", 34.00, -118.00, text="quake near los angeles area"),
        _claim("b", "emsc", 34.05, -118.02, dt_min=2, text="seismic event so cal"),
        _claim("c", "mastodon", 33.98, -118.01, dt_min=3, text="felt it in los angeles"),
    ]
    events = cluster_claims(claims)
    assert len(events) == 1
    assert events[0].event.refutation_flag is False


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


# --------------------------------------------------------------------------- #
# Windowed clustering + retention (live loop, docs/BUILD.md §6 follow-up)
# --------------------------------------------------------------------------- #
def _ins_claim(con, source_id, lat, lon, t, text="quake here right now today"):
    con.execute(
        "INSERT INTO claims (claim_id, source_id, source_type, external_id, ingested_at, "
        "event_time, time_uncertainty_s, lat, lon, loc_uncertainty_km, raw_text, raw_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [str(uuid.uuid4()), source_id, "seismic_network", None, t, t, 0.0, lat, lon, 0.0, text, "{}"],
    )


def _db(tmp_path, monkeypatch):
    import corroborate.config as cfg
    from corroborate import db

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "t.duckdb")
    db.init_db()
    return db.connect()


def test_window_clusters_recent_and_keeps_older_events(tmp_path, monkeypatch):
    con = _db(tmp_path, monkeypatch)
    try:
        # Two recent claims (within 48h) at one place -> one fresh event.
        _ins_claim(con, "emsc", 34.0, -118.0, T0)
        _ins_claim(con, "mastodon", 34.05, -118.0, T0 - timedelta(minutes=5))
        # A claim 5 days old: outside the window, must not be re-clustered.
        _ins_claim(con, "emsc", 10.0, 10.0, T0 - timedelta(days=5))
        # An event retained from a prior run, older than the window but within
        # retention: cluster_window must leave it untouched.
        old_eid = str(uuid.uuid4())
        old_t = T0 - timedelta(days=5)
        con.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [old_eid, 10.0, 10.0, old_t, old_t, old_t, 1, 1.0, 1, 0.4, False, "scored"],
        )

        s = cluster_window(con, window_hours=48.0, retention_hours=24.0 * 30)

        assert s["n_claims"] == 2  # only the recent pair entered clustering
        assert s["n_events"] == 1
        assert s["pruned"] == 0  # nothing past the 30-day retention horizon
        # Retained old event survived alongside the freshly built one.
        assert con.execute("SELECT count(*) FROM events").fetchone()[0] == 2
        assert con.execute(
            "SELECT count(*) FROM events WHERE event_id = ?", [old_eid]
        ).fetchone()[0] == 1
        # The fresh in-window event carries both recent claims.
        new = con.execute(
            "SELECT n_claims FROM events WHERE event_id != ?", [old_eid]
        ).fetchone()
        assert new[0] == 2
        assert con.execute("SELECT count(*) FROM claims").fetchone()[0] == 3
    finally:
        con.close()


def test_prune_drops_claims_and_ground_truth_past_retention(tmp_path, monkeypatch):
    con = _db(tmp_path, monkeypatch)
    try:
        _ins_claim(con, "emsc", 34.0, -118.0, T0)  # recent
        _ins_claim(con, "emsc", 34.0, -118.0, T0 - timedelta(days=40))  # stale
        for gid, t in (("recent", T0), ("stale", T0 - timedelta(days=40))):
            con.execute(
                "INSERT INTO ground_truth VALUES (?,?,?,?,?,?)",
                [gid, t, 34.0, -118.0, 4.5, "{}"],
            )

        s = cluster_window(con, window_hours=48.0, retention_hours=24.0 * 14)

        assert s["pruned"] == 1
        assert con.execute("SELECT count(*) FROM claims").fetchone()[0] == 1
        # ground truth past retention is dropped too; the recent label remains.
        gt = con.execute("SELECT gt_id FROM ground_truth").fetchall()
        assert [r[0] for r in gt] == ["recent"]
    finally:
        con.close()
