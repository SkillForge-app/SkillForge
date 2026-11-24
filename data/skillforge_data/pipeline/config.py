"""Pipeline settings. The extraction/chunking settings are AI's: they come from the injected `ExtractConfig`, not from numbers here."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from ..interfaces import ExtractConfigLike

EMBEDDING_MODEL = "local/BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSIONS = 384
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PipelineConfig:
    pipeline_version: str                      # fetch/clean/chunk code version; inside chunk_config
    embedding_version: str                     # long form: repo@revision#file:sha256=... (AI's retrieval.md)
    extract_config: ExtractConfigLike          # AI's ExtractConfig: chunking settings and fingerprint()
    splitter: str = "sentence"                 # AI's chunker splits on sentences; ChunkSettings has no name for it
    embedding_model: str = EMBEDDING_MODEL
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    extract_fingerprint: str = field(init=False, repr=True)   # = extract_config.fingerprint(), read once

    def __post_init__(self) -> None:
        fingerprint = self.extract_config.fingerprint()
        if not isinstance(fingerprint, str) or not _FINGERPRINT.match(fingerprint):
            raise ValueError("ExtractConfig.fingerprint() must be 64 lower-case hex characters")
        object.__setattr__(self, "extract_fingerprint", fingerprint)

    def chunk_config(self) -> dict[str, object]:
        """The jsonb stored in chunks.chunk_config (the five keys the database requires).

        `size` and `overlap` are AI's chunking settings (`target_words`, `overlap_words`); AI notes they repeat part of the
        fingerprint and that keeping them is harmless.
        """
        chunking = self.extract_config.chunking
        return {
            "size": chunking.target_words,
            "overlap": chunking.overlap_words,
            "splitter": self.splitter,
            "pipeline_version": self.pipeline_version,
            "extract_fingerprint": self.extract_fingerprint,
        }

    def chunk_config_hash(self) -> str:
        """sha256 hex of chunk_config as canonical JSON (sorted keys, no spaces)."""
        text = json.dumps(self.chunk_config(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def clean_key_fingerprint(self) -> str:
        """The part of the clean-text key that separates extraction versions."""
        return self.extract_fingerprint
