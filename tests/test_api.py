"""Tests for the GeoJSON builder (docs/BUILD.md §4.8)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _seed(con, score: float, sources: list[str]) -> str:
    eid = str(uuid.uuid4())
    t = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
    con.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [eid, 34.0, -118.0, t, t, t, len(sources), float(len(sources)), 1, score, False, "scored"],
    )
    for src in sources:
        cid = str(uuid.uuid4())
        con.execute(
            "INSERT INTO claims (claim_id, source_id, source_type, ingested_at, event_time, "
            "lat, lon, magnitude, raw_text, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [cid, src, "seismic_network", t, t, 34.0, -118.0, 4.5, "quake", "{}"],
        )
        con.execute("INSERT INTO event_claims VALUES (?,?,?)", [eid, cid, 1.0])
    return eid


def test_feature_collection(tmp_path, monkeypatch):
    import corroborate.config as cfg
    from corroborate import db
    from corroborate.api import build_feature_collection

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "t.duckdb")
    db.init_db()
    con = db.connect()
    try:
        _seed(con, 0.8, ["emsc", "bluesky"])
        _seed(con, 0.1, ["emsc"])

        fc = build_feature_collection(con)
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 2
        # ordered by score desc
        top = fc["features"][0]["properties"]
        assert top["score"] == 0.8
        assert set(top["sources"]) == {"emsc", "bluesky"}
        assert top["max_magnitude"] == 4.5
        assert fc["features"][0]["geometry"]["coordinates"] == [-118.0, 34.0]

        # min_score filter drops the low one
        assert len(build_feature_collection(con, min_score=0.5)["features"]) == 1
    finally:
        con.close()


def test_endpoint_since_validation(tmp_path, monkeypatch):
    import corroborate.config as cfg
    from fastapi.testclient import TestClient

    from corroborate import db
    from corroborate.api import app

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "t.duckdb")
    db.init_db()

    client = TestClient(app)
    assert client.get("/events.geojson?since=not-a-date").status_code == 400
    assert client.get("/events.geojson?since=2026-06-13T00:00:00Z").status_code == 200
    assert client.get("/events.geojson").status_code == 200
