"""EMSC (seismicportal.eu) — an INDEPENDENT authoritative network.

Independence from USGS is what makes source-weighting demonstrable. The FDSN
event service (`format=json`) returns a GeoJSON FeatureCollection; each feature's
`properties` carry `time` (ISO8601), `lat`, `lon`, `depth`, `mag`, `magtype`,
`unid`, `flynn_region`, ... Geometry is `[lon, lat, depth]`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

import httpx

from .. import config
from ..models import Claim
from .base import Poller


def _parse_time(value: str) -> datetime:
    """Parse EMSC ISO8601 (e.g. '2024-06-13T12:34:56.7Z') as UTC-aware."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class EMSCPoller(Poller):
    source_id = "emsc"
    source_type = "seismic_network"

    def __init__(self, feed: str = config.EMSC_FEED) -> None:
        self.feed = feed

    def fetch(self) -> Iterable[Claim]:
        resp = httpx.get(self.feed, timeout=30)
        resp.raise_for_status()
        now = datetime.now(tz=timezone.utc)
        for feat in resp.json().get("features", []):
            props = feat.get("properties", {})
            # Prefer explicit properties; fall back to geometry coordinates.
            lon = props.get("lon")
            lat = props.get("lat")
            if lat is None or lon is None:
                coords = feat.get("geometry", {}).get("coordinates", [None, None])
                lon, lat = coords[0], coords[1]
            external_id = feat.get("id") or props.get("unid")
            yield Claim(
                claim_id=str(uuid.uuid4()),
                source_id=self.source_id,
                source_type=self.source_type,
                external_id=external_id,
                ingested_at=now,
                event_time=_parse_time(props["time"]),
                time_uncertainty_s=2.0,
                lat=lat,
                lon=lon,
                loc_uncertainty_km=10.0,
                magnitude=props.get("mag"),
                raw_text=props.get("flynn_region", ""),
                raw_json=props,
            )
