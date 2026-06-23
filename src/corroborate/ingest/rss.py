"""News / disaster RSS (GDACS) — a news-class probabilistic source.

GDACS publishes a global disaster feed; we keep its earthquake items, reading the
georss coordinates and the magnitude from the severity field, and emit Claims with
source_type='news'. Parsed with the stdlib — no feed-parser dependency.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

from .. import config
from ..models import Claim
from .base import Poller

_NS = {
    "georss": "http://www.georss.org/georss",
    "gdacs": "http://www.gdacs.org",
}
_MAG = re.compile(r"Magnitude\s+([\d.]+)")


class RSSPoller(Poller):
    source_id = "rss:gdacs"
    source_type = "news"

    def __init__(self, feed: str = config.GDACS_RSS) -> None:
        self.feed = feed

    def fetch(self) -> Iterable[Claim]:
        resp = httpx.get(self.feed, timeout=30)
        resp.raise_for_status()
        now = datetime.now(tz=timezone.utc)
        for item in ET.fromstring(resp.text).iterfind(".//item"):
            if item.findtext("gdacs:eventtype", namespaces=_NS) != "EQ":
                continue  # earthquakes only — the calibrated domain
            point = (item.findtext("georss:point", namespaces=_NS) or "").split()
            if len(point) != 2:
                continue  # no usable location
            date = item.findtext("gdacs:fromdate", namespaces=_NS) or item.findtext("pubDate")
            try:
                event_time = parsedate_to_datetime(date) if date else now
            except (TypeError, ValueError):
                event_time = now
            mag = _MAG.search(item.findtext("gdacs:severity", namespaces=_NS) or "")
            yield Claim(
                claim_id=str(uuid.uuid4()),
                source_id=self.source_id,
                source_type=self.source_type,
                external_id=item.findtext("guid") or item.findtext("link"),
                ingested_at=now,
                event_time=event_time,
                time_uncertainty_s=3600.0,
                lat=float(point[0]),
                lon=float(point[1]),
                loc_uncertainty_km=50.0,
                magnitude=float(mag.group(1)) if mag else None,
                raw_text=(item.findtext("title") or "").strip(),
            )
