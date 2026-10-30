"""SkillForge knowledge (Track A): source discovery (AI-09), page extraction (AI-10),
retrieval (contract A4, AI-11) and prompt-injection defence (AI-19).

Track B (AI-12 Architect v1, AI-13 reference writer) imports `retrieve`, `wrap_passages`,
`UNTRUSTED_DATA_RULE` and `check_spec` from here; DE-05 imports `extract_page`. See
docs/ai/retrieval.md, docs/ai/extraction.md and docs/ai/injection-defence.md.
"""

from core.knowledge.chunking import ChunkSettings
from core.knowledge.extract import (
    Chunk,
    ExtractConfig,
    ExtractedPage,
    ExtractionInputError,
    QualityReport,
    extract_page,
    find_site_boilerplate,
)
from core.knowledge.injection_guard import (
    UNTRUSTED_DATA_RULE,
    Finding,
    ScreeningReport,
    check_spec,
    screen_passages_llm,
    screen_text,
    wrap_passages,
)
from core.knowledge.retrieval import (
    DEFAULT_K,
    MAX_K,
    FakeRetriever,
    RetrievalCall,
    RetrievalInputError,
    Retriever,
    get_retriever,
    retrieve,
    retrieve_sync,
    set_retriever,
)
from core.knowledge.search import (
    RankedSource,
    SourceList,
    discover_sources,
    discover_sources_sync,
)
from core.knowledge.types import Passage, to_source

__all__ = [
    "DEFAULT_K",
    "MAX_K",
    "Chunk",
    "ChunkSettings",
    "ExtractConfig",
    "ExtractedPage",
    "ExtractionInputError",
    "FakeRetriever",
    "Passage",
    "QualityReport",
    "RankedSource",
    "RetrievalCall",
    "RetrievalInputError",
    "Retriever",
    "SourceList",
    "ScreeningReport",
    "UNTRUSTED_DATA_RULE",
    "Finding",
    "check_spec",
    "screen_passages_llm",
    "screen_text",
    "wrap_passages",
    "discover_sources",
    "discover_sources_sync",
    "extract_page",
    "find_site_boilerplate",
    "get_retriever",
    "retrieve",
    "retrieve_sync",
    "set_retriever",
    "to_source",
]
