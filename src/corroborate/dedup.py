"""Dedup + independence weighting — the core novelty (docs/BUILD.md §4.3).

Run *within a candidate cluster* (claims already close in space-time), so
near-duplicate text reliably means "the same wire, reposted" rather than a
coincidence. Pipeline:

- near-dup grouping: MinHash over word-shingled `raw_text`; pairs with estimated
  Jaccard >= config.NEAR_DUP_JACCARD are unioned into one group.
- per-claim weight: each near-dup group sums to 1, split evenly (w_i = 1/|group|),
  so 12 reposts of one wire contribute 1 unit of evidence, not 12.
- n_independent: the number of distinct near-dup groups in the cluster.

Claims with too little text to shingle (e.g. a bare region name) each form their
own singleton group rather than colliding on an empty signature.
"""

from __future__ import annotations

from datasketch import MinHash, MinHashLSH

from . import config
from .models import Claim


def _shingles(text: str) -> set[str]:
    tokens = text.lower().split()
    k = config.SHINGLE_SIZE
    if not tokens:
        return set()
    if len(tokens) < k:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def _minhash(text: str) -> MinHash | None:
    shingles = _shingles(text)
    if not shingles:
        return None
    m = MinHash(num_perm=config.MINHASH_PERMS)
    for sh in shingles:
        m.update(sh.encode("utf-8"))
    return m


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def near_dup_groups(claims: list[Claim]) -> list[list[int]]:
    """Group claim indices by near-duplicate text. Returns a list of index lists."""
    n = len(claims)
    uf = _UnionFind(n)
    lsh = MinHashLSH(threshold=config.NEAR_DUP_JACCARD, num_perm=config.MINHASH_PERMS)
    hashes: dict[int, MinHash] = {}

    for i, claim in enumerate(claims):
        m = _minhash(claim.raw_text or "")
        if m is None:
            continue  # no shingles -> remains its own singleton group
        hashes[i] = m
        lsh.insert(str(i), m)

    for i, m in hashes.items():
        for key in lsh.query(m):
            j = int(key)
            if j != i:
                uf.union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    return list(groups.values())


def independence_weights(claims: list[Claim]) -> tuple[list[float], float]:
    """Return per-claim weights in [0,1] and the effective independent-source count.

    Reposts of one wire (near-duplicate text) collapse into a single group worth
    1 unit of evidence; each member gets weight 1/|group|.
    """
    if not claims:
        return [], 0.0
    weights = [0.0] * len(claims)
    groups = near_dup_groups(claims)
    for group in groups:
        w = 1.0 / len(group)
        for idx in group:
            weights[idx] = w
    return weights, float(len(groups))
