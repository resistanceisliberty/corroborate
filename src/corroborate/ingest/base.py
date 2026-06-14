"""Base class for source pollers."""

from __future__ import annotations

import abc
from collections.abc import Iterable

from ..models import Claim


class Poller(abc.ABC):
    """Fetch from one source and yield normalized Claims.

    Subclasses implement `fetch()`. The runner handles cadence + dedup-on-write
    by external_id (see scripts/run_ingest.py). See docs/BUILD.md §4.1.
    """

    source_id: str
    source_type: str

    @abc.abstractmethod
    def fetch(self) -> Iterable[Claim]:
        """Return current claims from this source."""
        raise NotImplementedError
