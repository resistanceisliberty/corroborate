"""Tests for independence weighting (docs/BUILD.md §4.3).

Dedup runs *within a cluster*, so near-duplicate text means "same wire, reposted."
"""

from __future__ import annotations

from datetime import datetime, timezone

from corroborate.dedup import independence_weights
from corroborate.models import Claim


def _claim(source_id: str, text: str, cid: str | None = None) -> Claim:
    return Claim(
        claim_id=cid or f"id-{source_id}-{text}",
        source_id=source_id,
        source_type="social",
        ingested_at=datetime.now(tz=timezone.utc),
        event_time=datetime.now(tz=timezone.utc),
        lat=0.0,
        lon=0.0,
        raw_text=text,
    )


def test_distinct_text_counts_independently():
    claims = [
        _claim("a", "magnitude five quake hits the northern coast tonight"),
        _claim("b", "felt strong shaking downtown buildings swayed for seconds"),
        _claim("c", "reports of a tremor near the harbour just now scary"),
    ]
    weights, n_ind = independence_weights(claims)
    assert n_ind == 3.0
    assert weights == [1.0, 1.0, 1.0]


def test_reposts_of_one_wire_collapse():
    # Same wire reposted across three different accounts -> one unit of evidence.
    wire = "BREAKING magnitude six earthquake strikes off the southern coast"
    claims = [_claim("x", wire, "t1"), _claim("x", wire, "t2"), _claim("bluesky", wire, "t3")]
    weights, n_ind = independence_weights(claims)
    assert n_ind == 1.0
    assert weights == [1.0 / 3, 1.0 / 3, 1.0 / 3]


def test_empty_text_does_not_collapse():
    # Bare/empty text must not all hash to the same empty signature.
    claims = [_claim("a", "", "e1"), _claim("b", "", "e2")]
    weights, n_ind = independence_weights(claims)
    assert n_ind == 2.0
    assert weights == [1.0, 1.0]


def test_empty_input():
    assert independence_weights([]) == ([], 0.0)
