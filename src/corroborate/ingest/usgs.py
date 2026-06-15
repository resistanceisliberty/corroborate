"""USGS earthquake feed — our authoritative ground truth.

Real implementation: USGS GeoJSON needs no API key. Emits Claims (so USGS also
participates as a source) and the runner separately mirrors these into the
ground_truth table for calibration labels.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

from .. import config
from ..models import Claim
from .base import Poller


def _ts(epoch_ms: int) -> datetime:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)


class USGSPoller(Poller):
    source_id = "usgs"
    source_type = "seismic_network"

    def __init__(self, feed: str = config.USGS_FEED) -> None:
        self.feed = feed

    def fetch(self) -> Iterable[Claim]:
        resp = httpx.get(self.feed, timeout=30)
        resp.raise_for_status()
        now = datetime.now(tz=timezone.utc)
        for feat in resp.json().get("features", []):
            props = feat.get("properties", {})
            lon, lat, _depth = feat["geometry"]["coordinates"]
            yield Claim(
                claim_id=str(uuid.uuid4()),
                source_id=self.source_id,
                source_type=self.source_type,
                external_id=feat.get("id"),
                ingested_at=now,
                event_time=_ts(props["time"]),
                time_uncertainty_s=1.0,
                lat=lat,
                lon=lon,
                loc_uncertainty_km=5.0,
                magnitude=props.get("mag"),
                raw_text=props.get("title", ""),
                raw_json=props,
                content_hash=feat.get("id"),
            )
