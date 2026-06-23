"""GDACS RSS poller parsing test with a mocked HTTP response (docs/BUILD.md §4.1)."""

from __future__ import annotations

from corroborate.ingest import rss

_FAKE_XML = """<?xml version="1.0"?>
<rss xmlns:georss="http://www.georss.org/georss" xmlns:gdacs="http://www.gdacs.org">
<channel>
  <item>
    <title>Green earthquake (Magnitude 5.5M, Depth:10km) in St. Helena</title>
    <pubDate>Sat, 20 Jun 2026 07:03:56 GMT</pubDate>
    <guid>EQ1547584</guid>
    <georss:point>-7.0346 -13.2711</georss:point>
    <gdacs:eventtype>EQ</gdacs:eventtype>
    <gdacs:fromdate>Sat, 20 Jun 2026 07:00:00 GMT</gdacs:fromdate>
    <gdacs:severity>Magnitude 5.5M, Depth:10km</gdacs:severity>
  </item>
  <item>
    <title>Green flood alert in Turkiye</title>
    <guid>FL1103920</guid>
    <georss:point>37.24 36.45</georss:point>
    <gdacs:eventtype>FL</gdacs:eventtype>
  </item>
</channel>
</rss>"""


class _Resp:
    text = _FAKE_XML

    def raise_for_status(self):
        pass


def test_rss_keeps_only_earthquakes(monkeypatch):
    monkeypatch.setattr(rss.httpx, "get", lambda *a, **k: _Resp())
    claims = list(rss.RSSPoller().fetch())
    assert len(claims) == 1  # the flood item is skipped
    c = claims[0]
    assert c.source_id == "rss:gdacs"
    assert c.source_type == "news"
    assert c.external_id == "EQ1547584"
    assert (round(c.lat, 4), round(c.lon, 4)) == (-7.0346, -13.2711)
    assert c.magnitude == 5.5
    assert (c.event_time.year, c.event_time.month, c.event_time.day) == (2026, 6, 20)
