"""Mastodon social source — unauthenticated public hashtag timeline.

Unlike Bluesky/X, a Mastodon instance's public tag timeline needs no auth, so
this is the social source that runs live out of the box. Status `content` is HTML;
we strip tags, geoparse the text, and drop posts with no confident location.
"""

from __future__ import annotations

import html
import re
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

from .. import config
from ..geoparse import geoparse
from ..models import Claim
from .base import Poller

TAGS = ["earthquake", "terremoto", "sismo", "temblor"]
_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_html(content: str) -> str:
    return html.unescape(_HTML_TAG.sub(" ", content)).strip()


class MastodonPoller(Poller):
    source_id = "mastodon"
    source_type = "social"

    def __init__(self, instance: str = config.MASTODON_INSTANCE, limit: int = 40) -> None:
        self.instance = instance.rstrip("/")
        self.limit = limit

    def fetch(self) -> Iterable[Claim]:
        now = datetime.now(tz=timezone.utc)
        seen: set[str] = set()
        for tag in TAGS:
            url = f"{self.instance}/api/v1/timelines/tag/{tag}"
            try:
                resp = httpx.get(url, params={"limit": self.limit}, timeout=30)
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
            for status in resp.json():
                sid = status.get("id")
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                text = _strip_html(status.get("content", ""))
                geo = geoparse(text)
                if geo is None:
                    continue
                lat, lon, unc = geo
                created = status.get("created_at", "")
                try:
                    event_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    event_time = now
                yield Claim(
                    claim_id=str(uuid.uuid4()),
                    source_id=self.source_id,
                    source_type=self.source_type,
                    external_id=str(sid),
                    ingested_at=now,
                    event_time=event_time,
                    time_uncertainty_s=600.0,
                    lat=lat,
                    lon=lon,
                    loc_uncertainty_km=unc,
                    magnitude=None,
                    raw_text=text,
                    raw_json=status,
                )
