"""AI-11 recall evaluation: embedding models x chunk sizes over the AI-10 fixture pages.

For each (model, chunk size) the labelled pages are ingested into a fresh in-memory index
(site boilerplate on, as in production) and every test question is asked with the real
retriever. A hit is a top-k passage from the question's page that contains its evidence
phrase. A word-overlap baseline (the fake retriever's ranking) runs over the same chunks.
"""

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from core.knowledge.chunking import ChunkSettings
from core.knowledge.extract import ExtractConfig
from core.knowledge.ingest import Page, ingest_pages
from core.knowledge.real import RealRetriever
from core.knowledge.retrieval import rank_by_overlap
from core.knowledge.store import LocalStore
from core.knowledge.types import Passage
from core.llm import set_gateway
from core.llm.litellm_gateway import LiteLLMGateway
from core.llm.local_embed import model_dir
from evaluation.retrieval.data import Candidate, Question, QuestionSet, indexed_pages

# The three chunk sizes AI-10 asked to compare. Overlap stays the same for all of them.
CHUNK_SIZES: dict[int, ChunkSettings] = {
    120: ChunkSettings(target_words=120, max_words=170, min_words=35, max_chars=1800),
    180: ChunkSettings(),  # the AI-10 default: 180 / 250 / 50, 1,800 characters
    250: ChunkSettings(target_words=250, max_words=300, min_words=70, max_chars=2000),
}
BASELINE = "word-overlap"
SIZE_MARGIN = 2  # questions: another chunk size must beat 180 by this many to replace it
MODEL_MARGIN = 1  # questions: a model this close to the best counts as tied


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def hit_rank(passages: list[Passage], page_url: str, evidence: str) -> int | None:
    """1-based rank of the first passage from the page that contains the evidence."""
    wanted = _norm(evidence)
    for rank, passage in enumerate(passages, 1):
        if str(passage.source_url) == page_url and wanted in _norm(passage.text):
            return rank
    return None


@dataclass
class RunResult:
    system: str  # a candidate name, or BASELINE
    chunk_words: int
    chunks: int
    ranks: dict[str, int | None]  # question id -> hit rank within k, None for a miss
    index_seconds: float = 0.0
    query_ms: float = 0.0
    dimensions: int | None = None

    def recall(self, at: int) -> float:
        hits = sum(1 for r in self.ranks.values() if r is not None and r <= at)
        return round(hits / len(self.ranks), 4) if self.ranks else 0.0

    def hits(self, at: int) -> int:
        return sum(1 for r in self.ranks.values() if r is not None and r <= at)

    @property
    def mrr(self) -> float:
        total = sum(1 / r for r in self.ranks.values() if r is not None)
        return round(total / len(self.ranks), 4) if self.ranks else 0.0


@dataclass
class Decision:
    model: str
    chunk_words: int
    reasons: list[str] = field(default_factory=list)
    rule_model: str = ""  # what the decision rule alone picked
    rule_chunk_words: int = 0
    chosen_by: str = "rule"  # "rule", or the person who chose instead of the rule
    why: str = ""  # their reason, when they did


@dataclass
class RecallReport:
    date: str
    k: int
    questions: int
    question_set_version: str
    candidates: dict[str, dict[str, Any]]
    results: list[RunResult]
    decision: Decision


async def run_candidate(
    name: str,
    candidate: Candidate,
    question_set: QuestionSet,
    pages: list[Page],
    url_of: dict[str, str],
    settings: ChunkSettings,
    k: int,
) -> tuple[RunResult, RunResult]:
    """Index the pages with one model and chunk size; ask every question. Also returns the
    word-overlap baseline over the same chunks."""
    model_config = candidate.model_config_for()
    previous = set_gateway(LiteLLMGateway(config=model_config))
    try:
        store = LocalStore()
        start = time.perf_counter()
        await ingest_pages(
            pages,
            store=store,
            extract_config=ExtractConfig(chunking=settings),
            model_config=model_config,
        )
        index_seconds = time.perf_counter() - start
        retriever = RealRetriever(store, model_config=model_config)
        ranks: dict[str, int | None] = {}
        start = time.perf_counter()
        for q in question_set.questions:
            found = await retriever.retrieve(q.question, q.domain, k)
            ranks[q.id] = hit_rank(found, url_of[q.page], q.evidence)
        query_ms = (time.perf_counter() - start) * 1000 / len(question_set.questions)
    finally:
        set_gateway(previous)
    records = store.records()
    model_result = RunResult(
        name,
        settings.target_words,
        len(records),
        ranks,
        round(index_seconds, 2),
        round(query_ms, 1),
        candidate.dimensions,
    )
    baseline: dict[str, int | None] = {}
    for q in question_set.questions:
        pool = [r.to_passage() for r in records if r.serves(q.domain)]
        baseline[q.id] = hit_rank(rank_by_overlap(q.question, pool)[:k], url_of[q.page], q.evidence)
    return model_result, RunResult(BASELINE, settings.target_words, len(records), baseline)


async def evaluate(
    question_set: QuestionSet,
    candidates: dict[str, Candidate],
    *,
    sizes: list[int],
    k: int = 5,
    today: date | None = None,
    choose: tuple[str, int] | None = None,
    chosen_by: str = "",
    why: str = "",
) -> RecallReport:
    """`choose` (model name, chunk words) records a person's decision instead of the rule's;
    the report then shows both, with `chosen_by` and `why`."""
    labels = indexed_pages(question_set)
    pages = [
        Page(
            label.path.read_bytes(), str(label.url), label.retrieved, question_set.pages[label.file]
        )
        for label in labels
    ]
    url_of = {label.file: str(label.url) for label in labels}
    results: list[RunResult] = []
    for size in sizes:
        baseline_done = False
        for name, candidate in candidates.items():
            model_result, baseline = await run_candidate(
                name, candidate, question_set, pages, url_of, CHUNK_SIZES[size], k
            )
            results.append(model_result)
            if not baseline_done:
                results.append(baseline)
                baseline_done = True
    return RecallReport(
        date=(today or date.today()).isoformat(),
        k=k,
        questions=len(question_set.questions),
        question_set_version=question_set.version,
        candidates={name: _describe(c) for name, c in candidates.items()},
        results=results,
        decision=_decision(results, candidates, k, choose, chosen_by, why),
    )


def _decision(
    results: list[RunResult],
    candidates: dict[str, Candidate],
    k: int,
    choose: tuple[str, int] | None,
    chosen_by: str,
    why: str,
) -> Decision:
    rule = decide(results, candidates, k)
    rule.rule_model, rule.rule_chunk_words = rule.model, rule.chunk_words
    if choose is None:
        return rule
    model, words = choose
    if not any(r.system == model and r.chunk_words == words for r in results):
        raise ValueError(f"{model} at {words} words was not part of this run")
    if not chosen_by or not why:
        raise ValueError("a decision that is not the rule's needs chosen_by and why")
    rule.model, rule.chunk_words, rule.chosen_by, rule.why = model, words, chosen_by, why
    return rule


def _describe(candidate: Candidate) -> dict[str, Any]:
    model_file = model_dir(candidate.local) / candidate.local.file
    size = round(model_file.stat().st_size / 1e6, 1) if model_file.is_file() else None
    return {
        "model": candidate.model,
        "dimensions": candidate.dimensions,
        "max_tokens": candidate.max_tokens,
        "licence": candidate.licence,
        "size_mb": size,
        "repo": f"{candidate.local.repo}@{candidate.local.revision[:8]}",
    }


def decide(results: list[RunResult], candidates: dict[str, Candidate], k: int) -> Decision:
    """The decision rule from the AI-11 plan:
    1. per model, keep 180 words unless another size beats it by SIZE_MARGIN questions;
    2. best recall@k wins; models within MODEL_MARGIN questions of it are tied, and a tie
       goes to fewer dimensions, then faster indexing."""
    reasons: list[str] = []
    picks: dict[str, RunResult] = {}
    for name in candidates:
        runs = {r.chunk_words: r for r in results if r.system == name}
        if not runs:
            continue  # a candidate this run did not include
        pick = runs.get(180) or max(runs.values(), key=lambda r: r.hits(k))
        best = max(runs.values(), key=lambda r: (r.hits(k), -abs(r.chunk_words - 180)))
        if best.hits(k) - pick.hits(k) >= SIZE_MARGIN:
            reasons.append(
                f"{name}: {best.chunk_words} words beats 180 by "
                f"{best.hits(k) - pick.hits(k)} questions, so it uses {best.chunk_words}"
            )
            pick = best
        picks[name] = pick
    top = max(r.hits(k) for r in picks.values())
    tied = [n for n, r in picks.items() if top - r.hits(k) <= MODEL_MARGIN]
    winner = min(tied, key=lambda n: (candidates[n].dimensions, picks[n].index_seconds))
    reasons.append(
        f"best recall@{k}: {top}/{len(picks[winner].ranks)} questions; within "
        f"{MODEL_MARGIN} of it: {', '.join(tied)}; the tie goes to fewer dimensions, then "
        f"faster indexing: {winner} ({candidates[winner].dimensions} dimensions)"
    )
    return Decision(winner, picks[winner].chunk_words, reasons)


def question_by_id(question_set: QuestionSet) -> dict[str, Question]:
    return {q.id: q for q in question_set.questions}
