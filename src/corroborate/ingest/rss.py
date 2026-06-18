"""News / disaster RSS (e.g. GDACS) — probabilistic news-class source.

TODO (M6): fetch config.GDACS_RSS, parse items, geoparse where coords absent,
emit Claims with source_type='news'.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models import Claim
from .base import Poller


class RSSPoller(Poller):
    source_id = "rss:gdacs"
    source_type = "news"

    def fetch(self) -> Iterable[Claim]:  # TODO M6
        raise NotImplementedError("RSS ingest — see docs/BUILD.md §2, M6")
