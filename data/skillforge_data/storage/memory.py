"""In-memory object storage for tests. Same rules as S3: put never overwrites, last_modified is the first upload."""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime

from .base import ObjectNotFound, StoredObject


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MemoryStorage:
    def __init__(self, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock
        self._objects: dict[tuple[str, str], tuple[bytes, datetime, dict[str, str], str | None]] = {}
        self.put_calls = 0            # how many times put() was called, to check that nothing is written twice

    def put(self, bucket: str, key: str, data: bytes, *, content_type: str | None = None,
            metadata: Mapping[str, str] | None = None) -> bool:
        self.put_calls += 1
        if (bucket, key) in self._objects:
            return False
        self._objects[(bucket, key)] = (bytes(data), self._clock(), dict(metadata or {}), content_type)
        return True

    def get(self, bucket: str, key: str) -> bytes:
        try:
            return self._objects[(bucket, key)][0]
        except KeyError:
            raise ObjectNotFound(f"{bucket}/{key}") from None

    def exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self._objects

    def head(self, bucket: str, key: str) -> StoredObject | None:
        item = self._objects.get((bucket, key))
        return None if item is None else StoredObject(key, len(item[0]), item[1])

    def delete(self, bucket: str, key: str) -> None:
        self._objects.pop((bucket, key), None)

    def list(self, bucket: str, prefix: str = "") -> Iterator[StoredObject]:
        for (b, key), (data, modified, _meta, _content_type) in sorted(self._objects.items()):
            if b == bucket and key.startswith(prefix):
                yield StoredObject(key, len(data), modified)

    # --- test helpers -----------------------------------------------------------------------------------------
    def metadata(self, bucket: str, key: str) -> dict[str, str]:
        return dict(self._objects[(bucket, key)][2])

    def set_last_modified(self, bucket: str, key: str, when: datetime) -> None:
        data, _old, meta, content_type = self._objects[(bucket, key)]
        self._objects[(bucket, key)] = (data, when, meta, content_type)
