"""Mastodon poller parsing test with a mocked HTTP response (docs/BUILD.md §4.1)."""

from __future__ import annotations

import pytest

from corroborate.geoparse import _gazetteer
from corroborate.ingest import mastodon

pytestmark = pytest.mark.skipif(_gazetteer() is None, reason="geonamescache not installed")

_FAKE = [
    {"id": "1", "content": "<p>Strong <b>earthquake</b> just hit Tokyo!</p>", "created_at": "2026-06-13T12:00:00.000Z"},
    {"id": "2", "content": "<p>everything is shaking &amp; scary</p>", "created_at": "2026-06-13T12:01:00.000Z"},
]


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_mastodon_strips_html_and_geoparses(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return _Resp(_FAKE if calls["n"] == 1 else [])

    monkeypatch.setattr(mastodon.httpx, "get", fake_get)

    claims = list(mastodon.MastodonPoller().fetch())
    assert len(claims) == 1  # the location-less post is dropped
    c = claims[0]
    assert c.source_id == "mastodon"
    assert "<" not in c.raw_text  # HTML stripped
    assert abs(c.lat - 35.69) < 2 and abs(c.lon - 139.69) < 2
