"""Bluesky poller parsing test with a mocked HTTP response (docs/BUILD.md §4.1)."""

from __future__ import annotations

import pytest

from corroborate.geoparse import _gazetteer
from corroborate.ingest import bluesky

pytestmark = pytest.mark.skipif(_gazetteer() is None, reason="geonamescache not installed")

_FAKE = {
    "posts": [
        {"uri": "at://1", "record": {"text": "earthquake in Tokyo!", "createdAt": "2026-06-13T12:00:00Z"}},
        {"uri": "at://2", "record": {"text": "my coffee is shaking", "createdAt": "2026-06-13T12:01:00Z"}},
        {"uri": "at://1", "record": {"text": "earthquake in Tokyo!", "createdAt": "2026-06-13T12:00:00Z"}},
    ]
}


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_skips_without_credentials(monkeypatch):
    monkeypatch.delenv("BLUESKY_IDENTIFIER", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    assert list(bluesky.BlueskyPoller().fetch()) == []


def test_bluesky_geoparses_and_dedups(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return _Resp(_FAKE if calls["n"] == 1 else {"posts": []})

    def fake_post(url, **kwargs):
        return _Resp({"accessJwt": "tok"})

    monkeypatch.setattr(bluesky.httpx, "get", fake_get)
    monkeypatch.setattr(bluesky.httpx, "post", fake_post)

    poller = bluesky.BlueskyPoller(identifier="me", app_password="pw")
    claims = list(poller.fetch())
    # 'coffee is shaking' has no location -> dropped; duplicate uri -> deduped.
    assert len(claims) == 1
    c = claims[0]
    assert c.source_id == "bluesky"
    assert c.external_id == "at://1"
    assert abs(c.lat - 35.69) < 2 and abs(c.lon - 139.69) < 2
