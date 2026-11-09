"""Pipeline settings. Chunking and embedding settings are configurable so AI can tune them (AI-10, AI-11)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

EMBEDDING_MODEL = "local/BAAI/bge-small-en-v1.5"
EMBEDDING_DIMENSIONS = 384


@dataclass(frozen=True)
class PipelineConfig:
    pipeline_version: str                      # fetch/clean/chunk code version; inside chunk_config
    embedding_version: str                     # pinned model revision (the long hash)
    chunk_size: int = 500                      # AI-owned values, recorded in chunk_config
    chunk_overlap: int = 50
    splitter: str = "sentence"
    embedding_model: str = EMBEDDING_MODEL
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    # ExtractConfig.fingerprint() from AI. Optional until AI finishes it; then it becomes required.
    extract_fingerprint: str | None = None

    def chunk_config(self) -> dict[str, object]:
        """The jsonb stored in chunks.chunk_config (keys checked by the database)."""
        config: dict[str, object] = {
            "size": self.chunk_size,
            "overlap": self.chunk_overlap,
            "splitter": self.splitter,
            "pipeline_version": self.pipeline_version,
        }
        if self.extract_fingerprint is not None:
            config["extract_fingerprint"] = self.extract_fingerprint
        return config

    def chunk_config_hash(self) -> str:
        """sha256 hex of chunk_config as canonical JSON (sorted keys, no spaces)."""
        text = json.dumps(self.chunk_config(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def clean_key_fingerprint(self) -> str:
        """The part of the clean-text key that separates extraction versions (`v0` until AI's fingerprint exists)."""
        return self.extract_fingerprint or "v0"
