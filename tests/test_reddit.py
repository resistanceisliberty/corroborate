"""Reddit poller parsing test with a mocked HTTP response (docs/BUILD.md §4.1)."""

from __future__ import annotations

import pytest

from corroborate.geoparse import _gazetteer
from corroborate.ingest import reddit

pytestmark = pytest.mark.skipif(_gazetteer() is None, reason="geonamescache not installed")

_FAKE = {
    "data": {
        "children": [
            {"data": {"id": "a1", "title": "Earthquake in Tokyo!", "selftext": "", "created_utc": 1_750_000_000}},
            {"data": {"id": "a2", "title": "my coffee is shaking", "selftext": "", "created_utc": 1_750_000_001}},
            {"data": {"id": "a1", "title": "Earthquake in Tokyo!", "selftext": "", "created_utc": 1_750_000_000}},
        ]
    }
}


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_skips_without_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    assert list(reddit.RedditPoller().fetch()) == []


def test_reddit_geoparses_and_dedups(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return _Resp(_FAKE if calls["n"] == 1 else {"data": {"children": []}})

    def fake_post(url, **kwargs):
        return _Resp({"access_token": "tok"})

    monkeypatch.setattr(reddit.httpx, "get", fake_get)
    monkeypatch.setattr(reddit.httpx, "post", fake_post)

    poller = reddit.RedditPoller(client_id="id", client_secret="sec")
    claims = list(poller.fetch())
    # 'coffee is shaking' has no location -> dropped; duplicate id -> deduped.
    assert len(claims) == 1
    c = claims[0]
    assert c.source_id == "reddit"
    assert c.external_id == "a1"
    assert abs(c.lat - 35.69) < 2 and abs(c.lon - 139.69) < 2
