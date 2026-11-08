"""DE-07: near-duplicate detection with MinHash, and the rule that duplicates must not make content disappear.

Why our own MinHash and not the `datasketch` classes: the signature is stored in `documents.minhash` and must stay readable for
years. datasketch 2.0 changed how its signatures are stored (a new `scheme` argument, 32-bit values), so a signature written by one
version cannot be read by another. This implementation is small, fixed and deterministic: the same text gives the same bytes on
every machine and Python version (`blake2b` hashes, a fixed seed). Changing `DedupConfig.seed`, `num_perm` or `shingle_words`
invalidates stored signatures; they would have to be recomputed.

How it works:
1. The clean text is cut into overlapping shingles of `shingle_words` words (lower case).
2. The signature is the minimum of `num_perm` random hash permutations over the shingles (1 KB with 128 permutations).
3. Two signatures agree on a share of positions equal (on average) to the Jaccard similarity of the shingle sets.
4. `DuplicateFinder` keeps an in-memory banded index (16 bands of 8 rows) of the signatures of canonical documents, proposes
   candidates, and the database decides which are valid: current, not themselves duplicates, readable, from another source.

Rules (docs/data-architecture.md, "Note for DE-07"):
- A document is a duplicate when another source has a current, canonical document with an estimated Jaccard of at least
  `threshold`. Old versions of the same source are never "duplicates": a page that changed a little is a new version, not a copy.
- The canonical document is the earliest one by `fetched_at`. Duplicates keep their chunks and embeddings; the views hide them.
- When a canonical document stops being current, a current duplicate is promoted in the same transaction (`promote_duplicates`).
"""
from __future__ import annotations

import hashlib
import random
import re
import struct
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import psycopg

_PRIME = (1 << 61) - 1          # Mersenne prime; permutations are (a * x + b) mod _PRIME
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class DedupConfig:
    shingle_words: int = 5
    num_perm: int = 128
    threshold: float = 0.85      # estimated Jaccard at which two documents count as copies
    bands: int = 16              # 16 bands x 8 rows = 128 permutations; a candidate shares at least one band
    seed: int = 20261108         # part of the stored signature: do not change without recomputing

    def __post_init__(self) -> None:
        if self.num_perm % self.bands:
            raise ValueError("num_perm must be a multiple of bands")


def shingles(text: str, size: int = 5) -> set[str]:
    """Overlapping groups of `size` words, lower case. A text shorter than `size` words is one shingle."""
    words = [w.lower() for w in _WORD.findall(text)]
    if not words:
        return set()
    if len(words) <= size:
        return {" ".join(words)}
    return {" ".join(words[i:i + size]) for i in range(len(words) - size + 1)}


class MinHasher:
    def __init__(self, config: DedupConfig = DedupConfig()) -> None:  # noqa: B008 (frozen, shared on purpose)
        rng = random.Random(config.seed)
        self.config = config
        self._a = [rng.randrange(1, _PRIME) for _ in range(config.num_perm)]
        self._b = [rng.randrange(0, _PRIME) for _ in range(config.num_perm)]

    def signature(self, text: str) -> bytes | None:
        """The stored form of the signature (big-endian 64-bit values), or None for a text without words."""
        grams = shingles(text, self.config.shingle_words)
        if not grams:
            return None
        hashes = [int.from_bytes(hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest(), "big") % _PRIME
                  for g in grams]
        values = [min((a * h + b) % _PRIME for h in hashes) for a, b in zip(self._a, self._b, strict=True)]
        return struct.pack(f">{len(values)}Q", *values)


def unpack(signature: bytes) -> tuple[int, ...]:
    return struct.unpack(f">{len(signature) // 8}Q", signature)


def jaccard(sig_a: bytes, sig_b: bytes) -> float:
    """Estimated Jaccard similarity of the two shingle sets: the share of equal positions."""
    a, b = unpack(sig_a), unpack(sig_b)
    if len(a) != len(b):
        raise ValueError("signatures have different lengths")
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


class DuplicateFinder:
    """In-memory index of canonical documents' signatures. The database has the last word on every candidate."""

    def __init__(self, config: DedupConfig = DedupConfig()) -> None:  # noqa: B008
        self.config = config
        self.hasher = MinHasher(config)
        self._signatures: dict[str, bytes] = {}
        self._buckets: dict[tuple[int, bytes], set[str]] = defaultdict(set)

    @classmethod
    def load(cls, conn: psycopg.Connection, config: DedupConfig = DedupConfig()) -> DuplicateFinder:  # noqa: B008
        """Build the index from the signatures stored in the database (current, canonical, readable documents)."""
        finder = cls(config)
        for doc_id, signature in conn.execute(
            "SELECT id, minhash FROM knowledge.documents "
            "WHERE minhash IS NOT NULL AND is_current AND duplicate_of IS NULL AND quality_ok"
        ):
            finder.add(doc_id, bytes(signature))
        return finder

    def __len__(self) -> int:
        return len(self._signatures)

    def add(self, document_id: uuid.UUID | str, signature: bytes) -> None:
        key = str(document_id)
        if key in self._signatures:
            self.remove(key)
        self._signatures[key] = signature
        for band in self._band_keys(signature):
            self._buckets[band].add(key)

    def remove(self, document_id: uuid.UUID | str) -> None:
        key = str(document_id)
        signature = self._signatures.pop(key, None)
        if signature is None:
            return
        for band in self._band_keys(signature):
            self._buckets[band].discard(key)

    def candidates(self, signature: bytes) -> list[tuple[str, float]]:
        """(document id, estimated Jaccard) of the indexed documents that reach the threshold, best first."""
        seen: set[str] = set()
        for band in self._band_keys(signature):
            seen |= self._buckets.get(band, set())
        scored = [(k, jaccard(signature, self._signatures[k])) for k in seen]
        return sorted((c for c in scored if c[1] >= self.config.threshold), key=lambda c: -c[1])

    def find(self, conn: psycopg.Connection, signature: bytes, *, source_id: uuid.UUID) -> uuid.UUID | None:
        """The canonical document this page is a copy of, or None. Never a document of the same source."""
        ids = [uuid.UUID(k) for k, _ in self.candidates(signature)]
        if not ids:
            return None
        row = conn.execute(
            "SELECT id FROM knowledge.documents WHERE id = ANY(%s) AND source_id <> %s "
            "AND is_current AND duplicate_of IS NULL AND quality_ok "
            "ORDER BY fetched_at, created_at, id LIMIT 1",
            (ids, source_id),
        ).fetchone()
        return row[0] if row else None

    def _band_keys(self, signature: bytes) -> Iterable[tuple[int, bytes]]:
        rows = self.config.num_perm // self.config.bands
        size = rows * 8
        for band in range(self.config.bands):
            yield band, hashlib.blake2b(signature[band * size:(band + 1) * size], digest_size=8).digest()


def promote_duplicates(conn: psycopg.Connection, no_longer_current: Sequence[uuid.UUID]) -> list[tuple[uuid.UUID, bytes | None]]:
    """Keep the content visible when canonical documents stop being current. Run it in the transaction that does it.

    For every document in `no_longer_current` that other documents point to (`duplicate_of`): choose the earliest current,
    readable duplicate as the new canonical document (its `duplicate_of` becomes NULL) and re-point the others to it. If no
    duplicate is current, nothing is lost: the content is gone from every live page, and the pointers stay as they are.
    Returns (document id, signature) of the promoted documents, so the caller can add them to the finder after the commit.
    """
    promoted: list[tuple[uuid.UUID, bytes | None]] = []
    if not no_longer_current:
        return promoted
    pointed_at = [r[0] for r in conn.execute(
        "SELECT DISTINCT duplicate_of FROM knowledge.documents WHERE duplicate_of = ANY(%s)", (list(no_longer_current),)
    ).fetchall()]
    for old in pointed_at:
        row = conn.execute(
            "SELECT id, minhash FROM knowledge.documents WHERE duplicate_of = %s AND is_current AND quality_ok "
            "ORDER BY fetched_at, created_at, id LIMIT 1", (old,),
        ).fetchone()
        if row is None:
            continue
        new_canonical, minhash = row
        conn.execute("UPDATE knowledge.documents SET duplicate_of = NULL WHERE id = %s", (new_canonical,))
        conn.execute("UPDATE knowledge.documents SET duplicate_of = %s WHERE duplicate_of = %s AND id <> %s",
                     (new_canonical, old, new_canonical))
        promoted.append((new_canonical, bytes(minhash) if minhash is not None else None))
    return promoted


def duplicate_rate(conn: psycopg.Connection, run_id: uuid.UUID) -> float | None:
    """Share of the pages fetched by a crawl run that were duplicates (the DE-07 report). None if nothing was fetched."""
    row = conn.execute(
        "SELECT pages_duplicate, pages_fetched FROM knowledge.crawl_runs WHERE id = %s", (run_id,)
    ).fetchone()
    if row is None or not row[1]:
        return None
    return row[0] / row[1]
