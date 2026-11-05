"""Object keys, as in docs/object-storage.md section 2.

raw:   <host>/<hash[0:2]>/<hash>.<ext>          content-addressed (sha256 of the fetched bytes)
clean: <document_id>/<extract_fingerprint>.txt  one owner per document, one object per extraction version
"""
from __future__ import annotations

import uuid

_EXTENSIONS = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/markdown": "md",
    "text/plain": "txt",
    "application/pdf": "pdf",
}


def extension_for(content_type: str | None) -> str:
    """File extension for a Content-Type header value ('bin' when unknown)."""
    if not content_type:
        return "bin"
    return _EXTENSIONS.get(content_type.split(";")[0].strip().lower(), "bin")


def raw_key(host: str, content_hash: str, content_type: str | None = None) -> str:
    if len(content_hash) != 64:
        raise ValueError("content_hash must be a sha256 hex string")
    return f"{host.lower()}/{content_hash[:2]}/{content_hash}.{extension_for(content_type)}"


def clean_key(document_id: uuid.UUID | str, fingerprint: str | None) -> str:
    """`v0` stands for the fingerprint until AI finishes ExtractConfig.fingerprint()."""
    return f"{document_id}/{fingerprint or 'v0'}.txt"
