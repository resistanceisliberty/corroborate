"""Reddit social source — keyword search over public posts (credential-gated).

Reddit needs OAuth even for public reads. Set REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET
(from a registered app at reddit.com/prefs/apps) to enable it; otherwise it
contributes nothing. Uses application-only OAuth — no user account or password —
searches the keyword set, geoparses each post, and drops the unlocatable.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

from ..geoparse import geoparse
from ..models import Claim
from .base import Poller

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
SEARCH_URL = "https://oauth.reddit.com/search"
KEYWORDS = ["earthquake", "terremoto", "temblor", "quake"]
# Reddit blocks requests without a descriptive, unique User-Agent.
_UA = "corroborate/0.1 (event corroboration research)"


class RedditPoller(Poller):
    source_id = "reddit"
    source_type = "social"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        limit: int = 50,
    ) -> None:
        self.client_id = client_id or os.environ.get("REDDIT_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("REDDIT_CLIENT_SECRET")
        self.limit = limit

    def _access_token(self) -> str:
        resp = httpx.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self.client_id, self.client_secret),
            headers={"User-Agent": _UA},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def fetch(self) -> Iterable[Claim]:
        if not (self.client_id and self.client_secret):
            return  # no credentials -> contribute nothing
        headers = {"Authorization": f"Bearer {self._access_token()}", "User-Agent": _UA}
        now = datetime.now(tz=timezone.utc)
        seen: set[str] = set()
        for keyword in KEYWORDS:
            try:
                resp = httpx.get(
                    SEARCH_URL,
                    params={"q": keyword, "sort": "new", "limit": self.limit, "type": "link"},
                    headers=headers,
                    timeout=30,
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
            for child in resp.json().get("data", {}).get("children", []):
                post = child.get("data", {})
                pid = post.get("id")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                text = f"{post.get('title', '')} {post.get('selftext', '')}".strip()
                geo = geoparse(text)
                if geo is None:
                    continue
                lat, lon, unc = geo
                created = post.get("created_utc")
                event_time = (
                    datetime.fromtimestamp(created, tz=timezone.utc)
                    if isinstance(created, (int, float))
                    else now
                )
                yield Claim(
                    claim_id=str(uuid.uuid4()),
                    source_id=self.source_id,
                    source_type=self.source_type,
                    external_id=pid,
                    ingested_at=now,
                    event_time=event_time,
                    time_uncertainty_s=600.0,
                    lat=lat,
                    lon=lon,
                    loc_uncertainty_km=unc,
                    magnitude=None,
                    raw_text=text,
                    raw_json=post,
                )
