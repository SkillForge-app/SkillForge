"""Skill Architect v1 (AI-07, AI-12): screened AnalyzedRequest -> valid SkillSpec, with sources.

    result = await build_spec(analyzed, existing_names=registry_names)
    if result.ok:
        spec = result.spec          # result.passages, result.evidence: for AI-13

A LangGraph flow:  research -> write -> enforce -> check -> (valid: done | errors: write again),
at most MAX_ATTEMPTS model calls.
- `research` retrieves passages for the request (contract A4) and numbers their pages src-1,
  src-2, ... It makes no model call.
- `write` asks the model for a SkillSpec (architect/generate, then architect/repair with the
  issues), with the passages wrapped as untrusted data (AI-19 layer 3).
- `enforce` applies the rules that must never depend on the model: identity from the analysis,
  one `must` guardrail per safety condition, and `sources[]` built from the passages the spec
  cites (the model only cites ids; it never writes a URL or a source).
- `check` runs core.spec.validate_spec, then AI-19's check_spec (layer 4) and `copied_text`
  (summarise, never paste).
"""

import copy
import os
import re
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict

from core.analysis import AnalyzedRequest
from core.analysis.safety import CONDITION_DESCRIPTIONS
from core.analysis.types import SafetyCondition
from core.knowledge import (
    UNTRUSTED_DATA_RULE,
    Passage,
    RetrievalInputError,
    check_spec,
    licence_for_url,
    retrieve,
    to_source,
    wrap_passages,
)
from core.knowledge.real import EmptyIndexError
from core.llm import (
    DeadlineExceeded,
    LLMOutputInvalid,
    LLMRefused,
    LLMUnavailable,
    complete,
    load_prompt,
    step_deadline,
)
from core.llm.errors import ConfigError
from core.spec import (
    CAPABILITIES,
    GUARDRAIL_CATEGORIES,
    HIGH_RISK_AREAS,
    PLATFORM_LIMITS,
    SEVERITIES,
    SPEC_VERSION,
    TARGETS,
    Issue,
    SkillSpec,
    validate_spec,
)
from core.spec.models import Source

# LangGraph ships with LangSmith tracing support. Keep it off unless someone turns it on on
# purpose: traces would contain users' requests.
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

from langgraph.graph import END, START, StateGraph  # noqa: E402

GENERATE = "architect/generate"
REPAIR = "architect/repair"
MAX_ATTEMPTS = 3
DEFAULT_TARGETS = ["claude", "codex"]

# Research (AI-12): up to MAX_QUERIES queries, RESEARCH_K passages each, MAX_PASSAGES kept.
MAX_QUERIES = 3
RESEARCH_K = 5
MAX_PASSAGES = 8
# "Summarise, never paste" (review F15): a free-text field may not share this many consecutive
# words with a passage.
COPY_RUN_WORDS = 12

Progress = Callable[[str, int], None]  # (stage, attempt): stage is attempt|repairing|done|failed

# One `must` guardrail per safety condition (AI-06): fixed id, category and wording.
CONDITION_GUARDRAILS: dict[SafetyCondition, tuple[str, str]] = {
    "authorized_use_only": (
        "scope",
        "Only help with security work on systems the user owns or is explicitly allowed to "
        "test; ask for confirmation when this is unclear.",
    ),
    "no_operational_harm": (
        "safety",
        "Explain threats so people can defend against them; never provide working attack "
        "tools, recipes or step-by-step instructions for causing harm.",
    ),
    "professional_disclaimer": (
        "disclaimer",
        "State that this is general information, not professional advice, and recommend a "
        "qualified professional for important decisions.",
    ),
    "crisis_resources": (
        "safety",
        "If the user shows distress or mentions self-harm, respond with care and point them to "
        "local crisis services or emergency help.",
    ),
    "privacy_protection": (
        "privacy",
        "Use only the personal data that is needed, with consent; never collect or track "
        "people covertly.",
    ),
    "age_appropriate": ("safety", "Keep all content suitable for children of the intended age."),
}
HUMAN_REVIEW_RULE = (
    "Recommend review by a qualified professional before the user acts on important outputs."
)
assert set(CONDITION_GUARDRAILS) == set(CONDITION_DESCRIPTIONS)


class ArchitectError(Exception):
    """Base class: the Architect could not or would not build a spec."""


class NotScreened(ArchitectError):
    """The request has no safety clearance. Run core.analysis.screen_and_analyze first."""


class NotReady(ArchitectError):
    """The request still has open clarifying questions."""


class ArchitectUnavailable(ArchitectError):
    """The model provider failed; retry the job later."""


class ArchitectRefused(ArchitectError):
    """The model refused to design this skill."""


@dataclass(frozen=True)
class Research:
    """What `research` found: the passages, and one numbered source per page they come from."""

    queries: tuple[str, ...] = ()
    index_empty: bool = False  # the knowledge index has no chunks yet: designed without them
    passages: tuple[Passage, ...] = ()
    sources: tuple[Source, ...] = ()  # src-1, src-2, ...: one per page, with its licence
    chunks: dict[str, tuple[str, ...]] = field(default_factory=dict)  # source id -> chunk ids


@dataclass(frozen=True)
class ArchitectResult:
    ok: bool
    spec: SkillSpec | None
    attempts: int
    issues: tuple[Issue, ...]  # the last attempt's errors when not ok, its warnings when ok
    prompt_versions: dict[str, int] = field(default_factory=dict)
    # For AI-13 (reference writer): the passages the Architect was given, and for each of the
    # spec's references the chunk ids of the pages it cites.
    passages: tuple[Passage, ...] = ()
    evidence: dict[str, tuple[str, ...]] = field(default_factory=dict)


class _State(TypedDict, total=False):
    analyzed: AnalyzedRequest
    existing_names: tuple[str, ...]
    progress: Progress | None
    knowledge: bool  # retrieve passages (AI-12); False: design without web knowledge
    research: Research
    attempt: int
    draft: dict[str, Any] | None  # the model's last SkillSpec, before enforce
    candidate: dict[str, Any] | None  # after enforce
    spec: SkillSpec | None
    issues: list[Issue]


# ------------------------------------------------------------------ research (AI-12)


def research_queries(analyzed: AnalyzedRequest) -> list[str]:
    """Up to MAX_QUERIES retrieval queries, from the request alone (no model call): its summary,
    its domain as words, and its expected outputs. Duplicates (ignoring case) are dropped."""
    area, _, sub = analyzed.domain.partition("/")
    topic = f"{sub.replace('-', ' ').replace('/', ' ')} {area}" if sub else area
    candidates = [analyzed.summary, topic, "; ".join(analyzed.expected_outputs[:3])]
    queries: list[str] = []
    for query in candidates:
        query = " ".join(query.split())
        if query and query.casefold() not in {q.casefold() for q in queries}:
            queries.append(query)
    return queries[:MAX_QUERIES]


def number_sources(passages: Sequence[Passage]) -> tuple[list[Source], dict[str, list[str]]]:
    """One source per page, numbered src-1, src-2, ... in passage order, with the host's
    licence (core.knowledge.licence_for_url); and each source's chunk ids."""
    sources: list[Source] = []
    by_url: dict[str, str] = {}
    chunks: dict[str, list[str]] = {}
    for passage in passages:
        url = str(passage.source_url)
        if url not in by_url:
            source_id = f"src-{len(sources) + 1}"
            by_url[url] = source_id
            source = to_source(passage, source_id)
            sources.append(source.model_copy(update={"licence": licence_for_url(url)}))
            chunks[source_id] = []
        chunks[by_url[url]].append(passage.chunk_id)
    return sources, chunks


async def research(analyzed: AnalyzedRequest) -> Research:
    """Retrieve passages for the request: each query in turn, k=RESEARCH_K, the first
    MAX_PASSAGES distinct chunks kept in order. No passages is not an error: the Architect then
    designs without web knowledge (no references, no sources)."""
    queries = research_queries(analyzed)
    passages: list[Passage] = []
    seen: set[str] = set()
    for query in queries:
        try:
            found = await retrieve(query, analyzed.domain, RESEARCH_K)
        except EmptyIndexError:
            return Research(queries=tuple(queries), index_empty=True)
        except (ConfigError, RetrievalInputError):
            raise  # a deployment or input mistake: retrying the job will not help
        except Exception as exc:  # the store or the embedding model failed: retry the job later
            raise ArchitectUnavailable(f"knowledge retrieval failed: {type(exc).__name__}") from exc
        for passage in found:
            if passage.chunk_id not in seen:
                seen.add(passage.chunk_id)
                passages.append(passage)
    kept = tuple(passages[:MAX_PASSAGES])
    sources, chunks = number_sources(kept)
    return Research(
        queries=tuple(queries),
        passages=kept,
        sources=tuple(sources),
        chunks={k: tuple(v) for k, v in chunks.items()},
    )


def evidence_for(spec: SkillSpec, found: Research) -> dict[str, tuple[str, ...]]:
    """For each reference, the chunk ids of the pages it cites (in passage order)."""
    return {
        ref.id: tuple(c for s in ref.sources for c in found.chunks.get(s, ()))
        for ref in spec.knowledge.references
    }


# ------------------------------------------------------------------ summarise, never paste

_WORD = re.compile(r"[^\W_]+")
# Fields that are not free text: ids, file paths, enums, dates, URLs and id lists.
_NOT_TEXT = frozenset(
    {
        "id",
        "file",
        "template",
        "url",
        "retrieved",
        "licence",
        "sources",
        "uses",
        "produces",
        "kind",
        "domain",
        "severity",
        "category",
        "spec_version",
        "version",
        "name",
        "targets",
        "required",
        "optional",
    }
)


def _words(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(text)]


def _text_fields(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """(JSON Pointer, text) for every free-text string in a spec dump."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in _NOT_TEXT:
                yield from _text_fields(item, f"{path}/{key}")
    elif isinstance(value, list):
        for n, item in enumerate(value):
            yield from _text_fields(item, f"{path}/{n}")


def copied_text(
    spec: SkillSpec, passages: Sequence[Passage], *, run: int = COPY_RUN_WORDS
) -> list[Issue]:
    """Errors for free-text fields that copy `run` or more consecutive words of a passage
    (case and punctuation ignored). The message never includes the text."""
    if not passages:
        return []
    shingles: set[tuple[str, ...]] = set()
    for passage in passages:
        words = _words(passage.text)
        shingles.update(tuple(words[i : i + run]) for i in range(len(words) - run + 1))
    issues = []
    for path, text in _text_fields(spec.model_dump(mode="json")):
        words = _words(text)
        if any(tuple(words[i : i + run]) in shingles for i in range(len(words) - run + 1)):
            issues.append(
                Issue(
                    path,
                    "copied_text",
                    f"copies {run} or more consecutive words from a passage; summarise it in "
                    "your own words",
                )
            )
    return issues


# ------------------------------------------------------------------ deterministic rules


def required_guardrails(analyzed: AnalyzedRequest) -> list[dict[str, str]]:
    """The `must` guardrails this request requires, independent of the model."""
    conditions = list(analyzed.safety.conditions) if analyzed.safety else []
    high_risk = analyzed.domain_area in HIGH_RISK_AREAS
    if high_risk and "professional_disclaimer" not in conditions:
        conditions.append("professional_disclaimer")
    guardrails = []
    for condition in conditions:
        category, rule = CONDITION_GUARDRAILS[condition]
        guardrails.append(
            {
                "id": "safety-" + condition.replace("_", "-"),
                "rule": rule,
                "severity": "must",
                "category": category,
            }
        )
    if high_risk:
        guardrails.append(
            {
                "id": "safety-human-review",
                "rule": HUMAN_REVIEW_RULE,
                "severity": "must",
                "category": "human_review",
            }
        )
    return guardrails


def enforce(
    analyzed: AnalyzedRequest,
    draft: Mapping[str, Any],
    existing_names: Collection[str] = (),
    *,
    sources: Sequence[Source] | None = None,
) -> dict[str, Any]:
    """Apply the rules that must not depend on the model. Idempotent.

    `sources`: the numbered sources `research` found (build_spec always passes them). The
    spec's `sources[]` becomes the ones its references cite; an id the model made up stays in
    the reference, so validation reports `unknown_source` and the spec is repaired. With no
    sources (no passages), references, sources and `uses` are emptied: never an invented
    source. None (direct callers) leaves knowledge as it is.
    """
    spec = copy.deepcopy(dict(draft))
    spec["spec_version"] = SPEC_VERSION
    skill = spec.setdefault("skill", {})
    skill["kind"] = analyzed.kind
    skill["domain"] = analyzed.domain
    if analyzed.skill_name and analyzed.skill_name not in existing_names:
        skill["name"] = analyzed.skill_name
    spec["targets"] = list(analyzed.targets) or list(DEFAULT_TARGETS)
    required = required_guardrails(analyzed)
    ours = {g["id"] for g in required}
    theirs = [g for g in spec.get("guardrails", []) if g.get("id") not in ours]
    spec["guardrails"] = theirs + required
    if sources is not None:
        knowledge = spec.get("knowledge")
        if not isinstance(knowledge, dict):
            knowledge = spec["knowledge"] = {}
        references = knowledge.get("references") or []
        if sources:
            cited = {
                s for ref in references if isinstance(ref, dict) for s in ref.get("sources") or []
            }
            spec["sources"] = [
                s.model_dump(mode="json", exclude_none=True) for s in sources if s.id in cited
            ]
        else:
            knowledge["references"] = []
            spec["sources"] = []
            for procedure in spec.get("procedures") or []:
                if isinstance(procedure, dict):
                    procedure["uses"] = []
    return spec


# ------------------------------------------------------------------ prompt inputs


def _knowledge_inputs(found: Research) -> dict[str, Any]:
    """The passages as untrusted data (AI-19 layer 3) and the source ids the model may cite.
    Page titles stay inside the wrapped block; the id list names chunk ids only."""
    if not found.passages:
        return {"knowledge": "", "knowledge_rule": "", "source_ids": []}
    return {
        "knowledge": wrap_passages(found.passages),
        "knowledge_rule": UNTRUSTED_DATA_RULE,
        "source_ids": [
            {"id": s.id, "chunk_ids": list(found.chunks.get(s.id, ()))} for s in found.sources
        ],
    }


def _generate_inputs(
    analyzed: AnalyzedRequest, existing_names: Collection[str], found: Research | None = None
) -> dict[str, Any]:
    name_hint = ""
    if analyzed.skill_name and analyzed.skill_name in existing_names:
        name_hint = f'The name "{analyzed.skill_name}" is already taken; choose a different one.'
    return {
        "analyzed_request": analyzed.model_dump_json(indent=1),
        "capabilities": list(CAPABILITIES),
        "targets": list(TARGETS),
        "severities": list(SEVERITIES),
        "guardrail_categories": list(GUARDRAIL_CATEGORIES),
        "description_limit": min(PLATFORM_LIMITS[t].description for t in TARGETS),
        "required_guardrails": required_guardrails(analyzed),
        "name_hint": name_hint,
        **_knowledge_inputs(found or Research()),
    }


def _repair_inputs(
    analyzed: AnalyzedRequest,
    previous: Mapping[str, Any],
    issues: list[Issue],
    attempt: int,
    found: Research | None = None,
) -> dict[str, Any]:
    import json

    return {
        "analyzed_request": analyzed.model_dump_json(indent=1),
        "previous_spec": json.dumps(previous, indent=1, ensure_ascii=False),
        "issues": [str(i) for i in issues],
        "attempt": attempt,
        "max_attempts": MAX_ATTEMPTS,
        **_knowledge_inputs(found or Research()),
    }


# ------------------------------------------------------------------ graph nodes


async def _research(state: _State) -> _State:
    if not state.get("knowledge", True):
        return {"research": Research()}
    return {"research": await research(state["analyzed"])}


async def _write(state: _State) -> _State:
    attempt = state.get("attempt", 0) + 1
    progress = state.get("progress")
    previous = state.get("candidate")
    repairing = attempt > 1 and previous is not None
    if progress:
        progress("repairing" if repairing else "attempt", attempt)
    analyzed = state["analyzed"]
    found = state.get("research") or Research()
    try:
        if repairing:
            assert previous is not None
            inputs = _repair_inputs(analyzed, previous, state.get("issues", []), attempt, found)
            spec = await complete(REPAIR, inputs, SkillSpec)
        else:
            inputs = _generate_inputs(analyzed, state.get("existing_names", ()), found)
            spec = await complete(GENERATE, inputs, SkillSpec)
    except LLMRefused as exc:  # LLMRefused is a subclass of LLMOutputInvalid: check it first
        raise ArchitectRefused("the model refused to design this skill") from exc
    except LLMOutputInvalid:
        return {"attempt": attempt, "draft": None}
    except LLMUnavailable as exc:
        raise ArchitectUnavailable(f"model unavailable: {type(exc).__name__}") from exc
    return {"attempt": attempt, "draft": spec.model_dump(mode="json")}


async def _enforce(state: _State) -> _State:
    draft = state.get("draft")
    if draft is None:
        return {"candidate": state.get("candidate")}  # keep the last good candidate to repair
    found = state.get("research") or Research()
    candidate = enforce(
        state["analyzed"], draft, state.get("existing_names", ()), sources=found.sources
    )
    return {"candidate": candidate}


def knowledge_issues(spec: SkillSpec, analyzed: AnalyzedRequest, found: Research) -> list[Issue]:
    """After validate_spec: AI-19's check_spec (layer 4) and copied_text (errors), plus a
    `knowledge_unused` warning when passages were found but no reference cites them."""
    issues = check_spec(spec, request=analyzed, passages=found.passages)
    issues += copied_text(spec, found.passages)
    if found.index_empty:
        issues.append(
            Issue(
                "/sources",
                "knowledge_unavailable",
                "the knowledge index is empty; designed without web knowledge",
                "warning",
            )
        )
    if found.passages and not spec.knowledge.references:
        issues.append(
            Issue(
                "/knowledge/references",
                "knowledge_unused",
                "passages were found, but no reference cites them",
                "warning",
            )
        )
    return issues


async def _check(state: _State) -> _State:
    if state.get("draft") is None:
        issue = Issue("", "llm_output_invalid", "the reply did not match the SkillSpec schema")
        return {"spec": None, "issues": [issue]}
    result = validate_spec(state["candidate"] or {}, existing_names=state.get("existing_names", ()))
    if not result.ok or result.spec is None:
        return {"spec": None, "issues": list(result.errors)}
    found = state.get("research") or Research()
    extra = knowledge_issues(result.spec, state["analyzed"], found)
    errors = [i for i in extra if i.severity == "error"]
    if errors:
        return {"spec": None, "issues": errors}
    return {"spec": result.spec, "issues": list(result.warnings) + extra}


def _route(state: _State) -> str:
    if state.get("spec") is not None or state.get("attempt", 0) >= MAX_ATTEMPTS:
        return "done"
    return "retry"


def build_graph() -> Any:
    graph = StateGraph(_State)
    graph.add_node("research", _research)
    graph.add_node("write", _write)
    graph.add_node("enforce", _enforce)
    graph.add_node("check", _check)
    graph.add_edge(START, "research")
    graph.add_edge("research", "write")
    graph.add_edge("write", "enforce")
    graph.add_edge("enforce", "check")
    graph.add_conditional_edges("check", _route, {"done": END, "retry": "write"})
    return graph.compile()


_GRAPH = build_graph()


async def build_spec(
    analyzed: AnalyzedRequest,
    *,
    existing_names: Collection[str] = (),
    on_progress: Progress | None = None,
    knowledge: bool = True,
) -> ArchitectResult:
    """Design a SkillSpec for a screened request. At most MAX_ATTEMPTS model calls.

    `knowledge`: retrieve passages first (AI-12) and cite them. False designs without web
    knowledge: the spec then has no references and no sources.
    """
    if analyzed.safety is None:
        raise NotScreened("this request was not safety-screened; use screen_and_analyze")
    if analyzed.needs_clarification:
        raise NotReady("this request still has open clarifying questions")
    try:
        async with step_deadline("design"):
            final: _State = await _GRAPH.ainvoke(
                {
                    "analyzed": analyzed,
                    "existing_names": tuple(existing_names),
                    "progress": on_progress,
                    "knowledge": knowledge,
                }
            )
    except DeadlineExceeded as exc:
        raise ArchitectUnavailable(str(exc)) from exc
    spec = final.get("spec")
    found = final.get("research") or Research()
    if on_progress:
        on_progress("done" if spec is not None else "failed", final.get("attempt", 0))
    return ArchitectResult(
        ok=spec is not None,
        spec=spec,
        attempts=final.get("attempt", 0),
        issues=tuple(final.get("issues", [])),
        prompt_versions={p: load_prompt(p).version for p in (GENERATE, REPAIR)},
        passages=found.passages,
        evidence=evidence_for(spec, found) if spec is not None else {},
    )
