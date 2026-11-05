"""S3-compatible object storage on boto3 (AWS S3, Cloudflare R2, MinIO).

The boto3 client is passed in, so tests use a fake client and nothing here touches the network at import or in tests.
`S3Storage.from_env()` builds the real client from the variables listed in docs/object-storage.md section 6:
S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY (and optionally S3_REGION). boto3 is imported only there.

`put` checks for the key first and skips the write if it exists, so the object keeps its first upload time (the raw
retention counts from it). The check and the write are two requests, which is fine because one key has one content (content
hash) and the pipeline runs one worker per source.
"""
from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from typing import Any

from .base import ObjectNotFound, StoredObject

_MISSING_CODES = {"404", "NoSuchKey", "NotFound"}


def _error_code(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return str(response.get("Error", {}).get("Code", "")) or None
    return None


class S3Storage:
    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> S3Storage:
        env = os.environ if env is None else env
        missing = [name for name in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY") if not env.get(name)]
        if missing:
            raise RuntimeError(f"object storage is not configured, missing: {', '.join(missing)}")
        try:
            import boto3
        except ImportError as exc:                    # boto3 is a dependency; this only guards a broken install
            raise RuntimeError("boto3 is not installed") from exc
        client = boto3.client(
            "s3", endpoint_url=env["S3_ENDPOINT"], aws_access_key_id=env["S3_ACCESS_KEY"],
            aws_secret_access_key=env["S3_SECRET_KEY"], region_name=env.get("S3_REGION", "us-east-1"),
        )
        return cls(client)

    def put(self, bucket: str, key: str, data: bytes, *, content_type: str | None = None,
            metadata: Mapping[str, str] | None = None) -> bool:
        if self.head(bucket, key) is not None:
            return False
        extra: dict[str, Any] = {"Metadata": dict(metadata or {})}
        if content_type:
            extra["ContentType"] = content_type
        self._client.put_object(Bucket=bucket, Key=key, Body=data, **extra)
        return True

    def get(self, bucket: str, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as exc:
            if _error_code(exc) in _MISSING_CODES:
                raise ObjectNotFound(f"{bucket}/{key}") from exc
            raise

    def exists(self, bucket: str, key: str) -> bool:
        return self.head(bucket, key) is not None

    def head(self, bucket: str, key: str) -> StoredObject | None:
        try:
            info = self._client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:
            if _error_code(exc) in _MISSING_CODES:
                return None
            raise
        return StoredObject(key, int(info["ContentLength"]), info["LastModified"])

    def delete(self, bucket: str, key: str) -> None:
        self._client.delete_object(Bucket=bucket, Key=key)       # S3 does not fail for a missing key

    def list(self, bucket: str, prefix: str = "") -> Iterator[StoredObject]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                yield StoredObject(item["Key"], int(item["Size"]), item["LastModified"])
