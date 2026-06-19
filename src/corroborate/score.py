"""Feature extraction + calibrated scorer (docs/BUILD.md §4.5).

Features per candidate event:
  n_independent, n_source_types, spatial_dispersion_km, temporal_spread_s,
  consolidation_lag_s, max_source_prior, max_magnitude

The model (a StandardScaler + LogisticRegression pipeline wrapped in
CalibratedClassifierCV) is trained in calibrate.py and persisted to
config.MODEL_PATH; loaded here for serving.
"""

from __future__ import annotations

import builtins
import pickle

import numpy as np

from . import config
from .models import Claim, Event
from .util import haversine_km

FEATURE_NAMES = [
    "n_independent",
    "n_source_types",
    "spatial_dispersion_km",
    "temporal_spread_s",
    "consolidation_lag_s",
    "max_source_prior",
    "max_magnitude",
]


def feature_row(event: Event, claims: list[Claim]) -> dict[str, float]:
    """Compute the named feature vector for one candidate event."""
    mags = [c.magnitude for c in claims if c.magnitude is not None]
    dists = [haversine_km(event.centroid_lat, event.centroid_lon, c.lat, c.lon) for c in claims]
    times = sorted(c.event_time.timestamp() for c in claims)
    ingest = sorted(c.ingested_at.timestamp() for c in claims)
    k = min(config.MIN_SAMPLES, len(ingest))

    return {
        "n_independent": float(event.n_independent),
        "n_source_types": float(event.n_source_types),
        "spatial_dispersion_km": float(np.std(dists)) if len(dists) > 1 else 0.0,
        "temporal_spread_s": (times[-1] - times[0]) if len(times) > 1 else 0.0,
        "consolidation_lag_s": (ingest[k - 1] - ingest[0]) if k >= 1 else 0.0,
        "max_source_prior": max(
            (config.SOURCE_PRIORS.get(c.source_id, config.SOURCE_PRIOR_DEFAULT) for c in claims),
            default=config.SOURCE_PRIOR_DEFAULT,
        ),
        "max_magnitude": max(mags) if mags else 0.0,
    }


def feature_vector(event: Event, claims: list[Claim]) -> list[float]:
    row = feature_row(event, claims)
    return [row[name] for name in FEATURE_NAMES]


# pickle.load() executes arbitrary code embedded in the file. The model is trained
# locally by train.py, but we still load it through a restricted unpickler that only
# permits numpy / scipy / sklearn classes (plus a few safe builtins), so a tampered
# model.pkl cannot smuggle in os.system-style payloads.
_SAFE_MODULES = ("numpy", "scipy", "sklearn")
_SAFE_BUILTINS = frozenset(
    {"range", "slice", "complex", "set", "frozenset", "list", "tuple", "dict", "bytearray", "bytes"}
)


class _RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if module.split(".", 1)[0] in _SAFE_MODULES:
            return super().find_class(module, name)
        if module == "copyreg" and name in {"_reconstructor", "__newobj__"}:
            return super().find_class(module, name)
        if module == "builtins" and name in _SAFE_BUILTINS:
            return getattr(builtins, name)
        raise pickle.UnpicklingError(f"blocked unpickling of {module}.{name}")


_MODEL = None


def load_model():
    """Load (and cache) the trained calibrated model via a restricted unpickler.

    Refuses to load from outside the data dir, and only permits numpy/scipy/sklearn
    globals — pickle otherwise executes arbitrary code from the file.
    """
    global _MODEL
    if _MODEL is None:
        path = config.MODEL_PATH.resolve()
        if config.DATA_DIR.resolve() not in path.parents:
            raise ValueError(f"refusing to load model outside the data dir: {path}")
        with open(path, "rb") as fh:
            _MODEL = _RestrictedUnpickler(fh).load()
    return _MODEL
