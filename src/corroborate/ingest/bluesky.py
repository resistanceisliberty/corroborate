"""Bluesky social source — many weakly-independent claims (where dedup earns its keep).

The public AppView now requires auth, so this poller is credential-gated: set
BLUESKY_IDENTIFIER + BLUESKY_APP_PASSWORD (an app password, not your login) to
enable it; otherwise it contributes nothing. It creates a PDS session for an
access token, runs searchPosts, geoparses each post, and drops the unlocatable.
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

BSKY_PDS = "https://bsky.social"
CREATE_SESSION = f"{BSKY_PDS}/xrpc/com.atproto.server.createSession"
SEARCH = f"{BSKY_PDS}/xrpc/app.bsky.feed.searchPosts"
KEYWORDS = ["earthquake", "terremoto", "temblor", "quake"]


class BlueskyPoller(Poller):
    source_id = "bluesky"
    source_type = "social"

    def __init__(
        self,
        identifier: str | None = None,
        app_password: str | None = None,
        limit: int = 50,
    ) -> None:
        self.identifier = identifier or os.environ.get("BLUESKY_IDENTIFIER")
        self.app_password = app_password or os.environ.get("BLUESKY_APP_PASSWORD")
        self.limit = limit

    def _access_token(self) -> str:
        resp = httpx.post(
            CREATE_SESSION,
            json={"identifier": self.identifier, "password": self.app_password},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["accessJwt"]

    def fetch(self) -> Iterable[Claim]:
        if not (self.identifier and self.app_password):
            return  # no credentials -> contribute nothing
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        now = datetime.now(tz=timezone.utc)
        seen: set[str] = set()
        for keyword in KEYWORDS:
            try:
                resp = httpx.get(
                    SEARCH, params={"q": keyword, "limit": self.limit}, headers=headers, timeout=30
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
            for post in resp.json().get("posts", []):
                uri = post.get("uri")
                if not uri or uri in seen:
                    continue
                seen.add(uri)
                text = (post.get("record") or {}).get("text", "")
                geo = geoparse(text)
                if geo is None:
                    continue
                lat, lon, unc = geo
                created = (post.get("record") or {}).get("createdAt", "")
                try:
                    event_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    event_time = now
                yield Claim(
                    claim_id=str(uuid.uuid4()),
                    source_id=self.source_id,
                    source_type=self.source_type,
                    external_id=uri,
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
