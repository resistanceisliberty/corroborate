"""X.com (formerly Twitter) social source — high-volume probabilistic claims.

Highest volume of the social sources - retweets and quote-posts of a single wire
are exactly what independence weighting (§4.3) is for. Lowest openness, though —
recent search is a PAID API tier, so this poller is token-gated: with no
X_BEARER_TOKEN it contributes nothing rather than crashing the run.

Access:
  - API v2 GET /2/tweets/search/recent (Bearer token via env X_BEARER_TOKEN).
  - Geo expansions: tweet.fields=geo,created_at, expansions=geo.place_id,
    place.fields=geo,full_name. Use the place bbox centroid when present,
    otherwise fall back to geoparse() on the text.
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

X_SEARCH_URL = "https://api.x.com/2/tweets/search/recent"
X_QUERY = "(earthquake OR shaking OR terremoto OR temblor) -is:retweet"
X_PARAMS = {
    "query": X_QUERY,
    "max_results": "50",
    "tweet.fields": "geo,created_at",
    "expansions": "geo.place_id",
    "place.fields": "geo,full_name",
}


def _place_centroids(payload: dict) -> dict[str, tuple[float, float]]:
    """Map place_id -> (lat, lon) from the bbox centroid in `includes.places`."""
    out: dict[str, tuple[float, float]] = {}
    for place in payload.get("includes", {}).get("places", []):
        bbox = place.get("geo", {}).get("bbox")
        if bbox and len(bbox) == 4:
            west, south, east, north = bbox
            out[place["id"]] = ((south + north) / 2, (west + east) / 2)
    return out


class XPoller(Poller):
    source_id = "x"
    source_type = "social"

    def __init__(self, bearer_token: str | None = None) -> None:
        self.bearer_token = bearer_token or os.environ.get("X_BEARER_TOKEN")

    def fetch(self) -> Iterable[Claim]:
        if not self.bearer_token:
            return  # no credentials -> contribute nothing
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        resp = httpx.get(X_SEARCH_URL, params=X_PARAMS, headers=headers, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        places = _place_centroids(payload)
        now = datetime.now(tz=timezone.utc)

        for tweet in payload.get("data", []):
            text = tweet.get("text", "")
            lat = lon = None
            unc = 50.0
            place_id = (tweet.get("geo") or {}).get("place_id")
            if place_id and place_id in places:
                lat, lon = places[place_id]
            else:
                geo = geoparse(text)
                if geo is None:
                    continue
                lat, lon, unc = geo
            try:
                event_time = datetime.fromisoformat(tweet.get("created_at", "").replace("Z", "+00:00"))
            except ValueError:
                event_time = now
            yield Claim(
                claim_id=str(uuid.uuid4()),
                source_id=self.source_id,
                source_type=self.source_type,
                external_id=tweet.get("id"),
                ingested_at=now,
                event_time=event_time,
                time_uncertainty_s=600.0,
                lat=lat,
                lon=lon,
                loc_uncertainty_km=unc,
                magnitude=None,
                raw_text=text,
                raw_json=tweet,
                content_hash=tweet.get("id"),
            )
