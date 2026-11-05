"""Interface of the object storage (S3-compatible). Implementations: memory.py (tests), s3.py (boto3)."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

BUCKET_RAW = "skillforge-raw"
BUCKET_CLEAN = "skillforge-clean"
BUCKET_PACKAGES = "skillforge-packages"       # DevOps and Backend's; Data Engineering never uses it


class ObjectNotFound(KeyError):
    """The key does not exist in the bucket."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    last_modified: datetime     # time of the FIRST upload: skipping an upload must not change it


class ObjectStorage(Protocol):
    def put(
        self,
        bucket: str,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> bool:
        """Write the object unless the key already exists. Returns True if it was written, False if skipped."""
        ...

    def get(self, bucket: str, key: str) -> bytes:
        """Return the bytes, or raise ObjectNotFound."""
        ...

    def exists(self, bucket: str, key: str) -> bool: ...

    def head(self, bucket: str, key: str) -> StoredObject | None: ...

    def delete(self, bucket: str, key: str) -> None:
        """Delete the object. Deleting a key that does not exist is not an error."""
        ...

    def list(self, bucket: str, prefix: str = "") -> Iterator[StoredObject]: ...
