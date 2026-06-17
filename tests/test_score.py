"""Tests for the restricted model unpickler (security hardening)."""

from __future__ import annotations

import io
import os
import pickle

import numpy as np
import pytest

from corroborate.score import _RestrictedUnpickler


def _restricted_load(obj):
    return _RestrictedUnpickler(io.BytesIO(pickle.dumps(obj))).load()


def test_blocks_dangerous_global():
    class Evil:
        def __reduce__(self):
            return (os.system, ("echo pwned",))

    with pytest.raises(pickle.UnpicklingError):
        _restricted_load(Evil())


def test_allows_numpy_roundtrip():
    # numpy globals must still load, or the hardening would break the model.
    out = _restricted_load(np.array([1.0, 2.0, 3.0]))
    assert list(out) == [1.0, 2.0, 3.0]
