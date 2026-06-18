"""Tests for offline geoparsing (docs/BUILD.md §4.2)."""

from __future__ import annotations

import pytest

from corroborate.geoparse import _gazetteer, geoparse

pytestmark = pytest.mark.skipif(_gazetteer() is None, reason="geonamescache not installed")


def _near(got, lat, lon, tol=2.0):
    return got is not None and abs(got[0] - lat) < tol and abs(got[1] - lon) < tol


def test_city_match():
    assert _near(geoparse("Big earthquake just hit Tokyo right now!"), 35.69, 139.69)


def test_region_supplement():
    assert _near(geoparse("strong shaking felt across California today"), 36.78, -119.42, tol=5)


def test_country_via_capital():
    got = geoparse("reports of a major quake in Chile")
    assert got is not None  # resolves to Santiago-ish
    assert -40 < got[0] < -20


def test_no_location_returns_none():
    assert geoparse("the ground was shaking so much i was scared") is None


def test_stopwords_not_matched():
    # 'felt'/'near'/'quake' are suppressed even if present in the gazetteer.
    assert geoparse("felt that quake near me") is None
