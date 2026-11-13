"""Ingest (AI-11): pages -> AI-10 chunks -> embeddings -> the knowledge index.

    report = await ingest_pages([Page(html, url, retrieved, "marketing")], store=store)
    Page(html, url, retrieved, ["marketing/strategy", "legal/contracts"])  # several domains

For each page: extract_page (with the site boilerplate learned from the pages of the same host
in this batch), then embed the chunks with the `embedding` role and replace the page's chunks
in the index. A rejected page (paywall, wrong language, prompt injection, ...) gets no
chunks, and its old chunks are removed, so a page that turned into a login wall leaves the
index. Running ingest again on the same pages gives the same index.

Prompt injection (AI-19): extract_page already removes flagged sentences and rejects pages
with a high-confidence attack; `report.quarantined` records what was removed (rule codes,
positions, hashes; never text). With `llm_screen=True` each remaining chunk also goes to the
optional LLM check (a paid model call), and flagged chunks are dropped before embedding.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import HttpUrl

from core.knowledge.extract import ExtractConfig, ExtractedPage, extract_page, find_site_boilerplate
from core.knowledge.injection_guard import screen_passages_llm
from core.knowledge.retrieval import RetrievalInputError, check_domain
from core.knowledge.store import ChunkRecord, VectorStore
from core.llm import embed, load_config
from core.llm.config import ModelConfig
from core.llm.gateway import EMBEDDING_ROLE
from core.ops.events import IngestPageEvent, log_event


@dataclass(frozen=True)
class Page:
    html: str | bytes
    url: str
    retrieved: date
    # One or more SkillSpec domains or areas, e.g. "marketing" or ["technology/ai", "legal"];
    # stored as a tuple without repeats. Every chunk of the page serves all of them.
    domains: str | Sequence[str]

    def __post_init__(self) -> None:
        given = [self.domains] if isinstance(self.domains, str) else list(self.domains)
        object.__setattr__(self, "domains", tuple(dict.fromkeys(given)))


@dataclass(frozen=True)
class QuarantineEntry:
    """Text kept out of the index for prompt injection. Never holds the text itself."""

    layer: Literal["rules", "llm"]
    rules: tuple[str, ...]  # rule codes, or the LLM's category
    sha256: str | None  # of the removed sentence (rules) or chunk text (llm)
    block: int | None = None  # rules: block and sentence on the page
    sentence: int | None = None
    chunk_id: str | None = None  # llm: the dropped chunk


@dataclass
class IngestReport:
    chunks: dict[str, int] = field(default_factory=dict)  # url -> chunks indexed
    rejected: dict[str, tuple[str, ...]] = field(default_factory=dict)  # url -> reasons
    quarantined: dict[str, list[QuarantineEntry]] = field(default_factory=dict)  # url -> entries

    @property
    def total_chunks(self) -> int:
        return sum(self.chunks.values())


async def ingest_pages(
    pages: Sequence[Page],
    *,
    store: VectorStore,
    extract_config: ExtractConfig | None = None,
    model_role: str = EMBEDDING_ROLE,
    model_config: ModelConfig | None = None,
    site_boilerplate: bool = True,
    llm_screen: bool = False,
) -> IngestReport:
    for page in pages:
        if not page.domains:
            raise RetrievalInputError(f"page {page.url} has no domain")
        for domain in page.domains:
            check_domain(domain)
    extract_config = extract_config or ExtractConfig()
    model = (model_config or load_config()).role(model_role).model
    boilerplate = (
        find_site_boilerplate(((p.html, p.url) for p in pages), config=extract_config)
        if site_boilerplate
        else {}
    )
    report = IngestReport()
    for page in pages:
        host_hashes = boilerplate.get(HttpUrl(page.url).host or "", ())
        config = extract_config.model_copy(update={"site_boilerplate": host_hashes})
        extracted = extract_page(page.html, url=page.url, retrieved=page.retrieved, config=config)
        records = [ChunkRecord.from_chunk(c, page.domains) for c in extracted.chunks]
        entries = _rule_entries(extracted)
        if llm_screen and records:
            flagged = await screen_passages_llm([r.to_passage() for r in records])
            entries += [
                QuarantineEntry(
                    "llm", (flagged[r.chunk_id].category,), r.content_hash, chunk_id=r.chunk_id
                )
                for r in records
                if r.chunk_id in flagged
            ]
            records = [r for r in records if r.chunk_id not in flagged]
        if entries:
            report.quarantined[str(extracted.url)] = entries
        vectors = await embed([r.text for r in records], model_role=model_role) if records else []
        store.replace_source(str(extracted.url), records, vectors, model=model)
        if extracted.quality.ok:
            report.chunks[str(extracted.url)] = len(records)
        else:
            report.rejected[str(extracted.url)] = extracted.quality.reasons
        log_event(
            IngestPageEvent(
                host=extracted.url.host or "",
                reasons=list(extracted.quality.reasons),
                chunks=len(records),
                quarantined=len(entries),
            ),
            warning="injection" in extracted.quality.reasons,
        )
    return report


def _rule_entries(page: ExtractedPage) -> list[QuarantineEntry]:
    """One entry per removed sentence, with every rule that flagged it."""
    grouped: dict[tuple[int | None, int | None], list[str]] = {}
    hashes: dict[tuple[int | None, int | None], str | None] = {}
    for finding in page.screening.findings:
        key = (finding.block, finding.sentence)
        grouped.setdefault(key, []).append(finding.rule)
        hashes[key] = finding.sha256
    return [
        QuarantineEntry("rules", tuple(sorted(set(rules))), hashes[key], key[0], key[1])
        for key, rules in grouped.items()
    ]
