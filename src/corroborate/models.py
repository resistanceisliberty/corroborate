"""Normalized records shared across the pipeline."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class Claim(BaseModel):
    """A single assertion that an event happened somewhere at some time."""

    claim_id: str
    source_id: str          # 'usgs' | 'emsc' | ...
    source_type: str        # 'seismic_network' | 'social' | 'news'
    external_id: str | None = None
    ingested_at: datetime
    event_time: datetime
    time_uncertainty_s: float = 0.0
    lat: float
    lon: float
    loc_uncertainty_km: float = 0.0
    magnitude: float | None = None
    raw_text: str = ""
    raw_json: dict | None = None
    content_hash: str | None = None


class Event(BaseModel):
    """A candidate event: a cluster of claims with aggregate corroboration stats."""

    event_id: str
    centroid_lat: float
    centroid_lon: float
    est_time: datetime
    first_seen: datetime
    last_updated: datetime
    n_claims: int
    n_independent: float
    n_source_types: int
    score: float | None = None        # calibrated P(real), filled by the scorer
    refutation_flag: bool = False
    status: str = "candidate"         # 'candidate' | 'scored'
