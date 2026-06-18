"""Extract coordinates from unstructured claim text (docs/BUILD.md §4.2).

USGS/EMSC arrive geocoded; social/news need this. We use an OFFLINE gazetteer
(`geonamescache`: ~25k cities + country capitals, bundled — no downloads) plus a
small supplement of sub-national seismic regions that gazetteers miss (US states,
Honshu, Sumatra, ...). Matching prefers longer phrases, then more populous places.

Confidence floor: if nothing matches, return None — we DROP the claim rather than
guess a location (a wrong coordinate is worse than a missing one).
"""

from __future__ import annotations

import re
from functools import lru_cache

# Sub-national regions / common quake datelines absent from city/country lists.
# (name -> lat, lon, uncertainty_km)
_SUPPLEMENT: dict[str, tuple[float, float, float]] = {
    "california": (36.78, -119.42, 300.0),
    "alaska": (64.2, -149.5, 500.0),
    "nevada": (38.8, -116.4, 300.0),
    "oklahoma": (35.5, -97.5, 250.0),
    "hawaii": (19.6, -155.5, 150.0),
    "honshu": (36.2, 138.3, 300.0),
    "hokkaido": (43.2, 142.8, 200.0),
    "kyushu": (32.5, 131.0, 150.0),
    "sumatra": (-0.6, 101.3, 400.0),
    "java": (-7.5, 110.0, 300.0),
    "sulawesi": (-1.9, 120.3, 300.0),
    "mindanao": (7.5, 125.0, 200.0),
    "luzon": (16.0, 121.0, 200.0),
    "anatolia": (39.0, 35.0, 400.0),
    "kamchatka": (56.0, 159.0, 400.0),
    "tibet": (31.0, 88.0, 500.0),
    "kashmir": (34.0, 76.0, 200.0),
    "calabria": (39.0, 16.5, 100.0),
    "patagonia": (-45.0, -69.0, 500.0),
    "aegean": (38.5, 25.5, 200.0),
}

# Short-ish English words that are also gazetteer entries — suppress false hits.
_STOP = {
    "most", "same", "best", "page", "reading", "march", "split", "general",
    "national", "center", "union", "mobile", "many", "both", "long", "young",
    "white", "york", "of", "the", "and", "for", "are", "was", "from", "this",
    "that", "felt", "just", "near", "here", "quake", "shaking", "earthquake",
}

_WORD = re.compile(r"[A-Za-z]+")


@lru_cache(maxsize=1)
def _gazetteer() -> dict[str, tuple[float, float, float, int]] | None:
    """name(lower) -> (lat, lon, uncertainty_km, population_rank). None if unavailable."""
    try:
        import geonamescache
    except ImportError:
        return None

    gc = geonamescache.GeonamesCache()
    idx: dict[str, tuple[float, float, float, int]] = {}

    for city in gc.get_cities().values():
        name = city["name"].lower()
        pop = int(city.get("population") or 0)
        cur = idx.get(name)
        if cur is None or pop > cur[3]:
            idx[name] = (float(city["latitude"]), float(city["longitude"]), 25.0, pop)

    # Countries -> capital coordinates (country-level centroid proxy).
    for cc, info in gc.get_countries().items():
        cname = info["name"].lower()
        capital = info.get("capital")
        if not capital:
            continue
        for entry in gc.get_cities_by_name(capital):
            cd = next(iter(entry.values()))
            if cd.get("countrycode") == cc:
                # population rank kept high so a country beats a tiny same-named town
                idx.setdefault(cname, (float(cd["latitude"]), float(cd["longitude"]), 400.0, 10**8))
                break

    for name, (lat, lon, unc) in _SUPPLEMENT.items():
        idx[name] = (lat, lon, unc, 10**7)
    return idx


def geoparse(text: str) -> tuple[float, float, float] | None:
    """Return (lat, lon, loc_uncertainty_km) for the best place match, or None."""
    idx = _gazetteer()
    if not idx:
        return None
    tokens = _WORD.findall(text)
    best: tuple[int, float, float, float] | None = None  # (score, lat, lon, unc)
    for size in (3, 2, 1):
        for i in range(len(tokens) - size + 1):
            span = tokens[i : i + size]
            # Proper-noun heuristic: place names are capitalized; common words
            # ("much", "ground") are not. Kills most gazetteer false positives.
            if not all(w[0].isupper() for w in span):
                continue
            phrase = " ".join(span).lower()
            if len(phrase) < 4 or phrase in _STOP:
                continue
            hit = idx.get(phrase)
            if hit:
                lat, lon, unc, pop = hit
                score = size * 1_000_000_000 + pop  # longer phrase wins, then population
                if best is None or score > best[0]:
                    best = (score, lat, lon, unc)
    if best is None:
        return None
    return (best[1], best[2], best[3])
