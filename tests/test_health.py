"""Source-health recording + /status.json endpoint (stage 6 — freshness/alerting)."""

from __future__ import annotations

from datetime import datetime, timezone


def test_record_source_health_keeps_last_success_on_failure(tmp_path, monkeypatch):
    import corroborate.config as cfg
    from corroborate import db

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "t.duckdb")
    db.init_db()
    con = db.connect()
    try:
        t1 = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 6, 22, 12, 10, tzinfo=timezone.utc)
        db.record_source_health(con, "emsc", True, 5, None, t1)
        db.record_source_health(con, "emsc", False, 0, "HTTPError: 503", t2)
        ok, n, ls, err = con.execute(
            "SELECT ok, n_claims, last_success, last_error FROM source_health "
            "WHERE source_id = 'emsc'"
        ).fetchone()
        assert ok is False and err == "HTTPError: 503"
        # last_success survives the failure (stays at t1 :00, not t2 :10).
        assert ls is not None and ls.minute == 0
    finally:
        con.close()


def test_status_endpoint(tmp_path, monkeypatch):
    import corroborate.config as cfg
    from fastapi.testclient import TestClient

    from corroborate import db
    from corroborate.api import app

    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "t.duckdb")
    db.init_db()
    con = db.connect()
    db.record_source_health(con, "mastodon", True, 3, None, datetime(2026, 6, 22, tzinfo=timezone.utc))
    con.close()

    body = TestClient(app).get("/status.json").json()
    assert "newest_event" in body
    assert any(s["source_id"] == "mastodon" and s["ok"] is True for s in body["sources"])
