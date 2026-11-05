"""DE-03: object storage (raw pages, clean text). See docs/object-storage.md.

The S3 adapter (`.s3`) and the daily job (`.jobs`) are imported from their modules, so this package stays light.
"""
from .base import BUCKET_CLEAN, BUCKET_RAW, ObjectNotFound, ObjectStorage, StoredObject
from .keys import clean_key, raw_key
from .memory import MemoryStorage

__all__ = [
    "BUCKET_CLEAN", "BUCKET_RAW", "MemoryStorage", "ObjectNotFound", "ObjectStorage", "StoredObject",
    "clean_key", "raw_key",
]
