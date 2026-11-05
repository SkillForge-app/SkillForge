"""Skill Architect v0 (AI-07): screened AnalyzedRequest -> valid SkillSpec. No web knowledge yet.

    result = await build_spec(analyzed, existing_names=registry_names)
    if result.ok:
        spec = result.spec

A LangGraph flow:  write -> enforce -> check  -> (valid: done | errors: write again), at most
MAX_ATTEMPTS model calls. `write` asks the model for a SkillSpec (architect/generate, then
architect/repair with the validation issues). `enforce` applies the rules that must never depend
on the model: identity from the analysis, and one `must` guardrail per safety condition.
`check` runs core.spec.validate_spec.
"""

import copy
import os
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import Any, TypedDict

from core.analysis import AnalyzedRequest
from core.analysis.safety import CONDITION_DESCRIPTIONS
from core.analysis.types import SafetyCondition
from core.llm import LLMOutputInvalid, LLMRefused, LLMUnavailable, complete, load_prompt
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

# LangGraph ships with LangSmith tracing support. Keep it off unless someone turns it on on
# purpose: traces would contain users' requests.
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

from langgraph.graph import END, START, StateGraph  # noqa: E402

GENERATE = "architect/generate"
REPAIR = "architect/repair"
MAX_ATTEMPTS = 3
DEFAULT_TARGETS = ["claude", "codex"]

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
class ArchitectResult:
    ok: bool
    spec: SkillSpec | None
    attempts: int
    issues: tuple[Issue, ...]  # the last attempt's errors when not ok, its warnings when ok
    prompt_versions: dict[str, int] = field(default_factory=dict)


class _State(TypedDict, total=False):
    analyzed: AnalyzedRequest
    existing_names: tuple[str, ...]
    progress: Progress | None
    attempt: int
    draft: dict[str, Any] | None  # the model's last SkillSpec, before enforce
    candidate: dict[str, Any] | None  # after enforce
    spec: SkillSpec | None
    issues: list[Issue]


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
    analyzed: AnalyzedRequest, draft: Mapping[str, Any], existing_names: Collection[str] = ()
) -> dict[str, Any]:
    """Apply the rules that must not depend on the model. Idempotent."""
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
    return spec


# ------------------------------------------------------------------ prompt inputs


def _generate_inputs(analyzed: AnalyzedRequest, existing_names: Collection[str]) -> dict[str, Any]:
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
    }


def _repair_inputs(
    analyzed: AnalyzedRequest, previous: Mapping[str, Any], issues: list[Issue], attempt: int
) -> dict[str, Any]:
    import json

    return {
        "analyzed_request": analyzed.model_dump_json(indent=1),
        "previous_spec": json.dumps(previous, indent=1, ensure_ascii=False),
        "issues": [str(i) for i in issues],
        "attempt": attempt,
        "max_attempts": MAX_ATTEMPTS,
    }


# ------------------------------------------------------------------ graph nodes


async def _write(state: _State) -> _State:
    attempt = state.get("attempt", 0) + 1
    progress = state.get("progress")
    previous = state.get("candidate")
    repairing = attempt > 1 and previous is not None
    if progress:
        progress("repairing" if repairing else "attempt", attempt)
    analyzed = state["analyzed"]
    try:
        if repairing:
            assert previous is not None
            inputs = _repair_inputs(analyzed, previous, state.get("issues", []), attempt)
            spec = await complete(REPAIR, inputs, SkillSpec)
        else:
            inputs = _generate_inputs(analyzed, state.get("existing_names", ()))
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
    return {"candidate": enforce(state["analyzed"], draft, state.get("existing_names", ()))}


async def _check(state: _State) -> _State:
    if state.get("draft") is None:
        issue = Issue("", "llm_output_invalid", "the reply did not match the SkillSpec schema")
        return {"spec": None, "issues": [issue]}
    result = validate_spec(state["candidate"] or {}, existing_names=state.get("existing_names", ()))
    if result.ok:
        return {"spec": result.spec, "issues": list(result.warnings)}
    return {"spec": None, "issues": list(result.errors)}


def _route(state: _State) -> str:
    if state.get("spec") is not None or state.get("attempt", 0) >= MAX_ATTEMPTS:
        return "done"
    return "retry"


def build_graph() -> Any:
    graph = StateGraph(_State)
    graph.add_node("write", _write)
    graph.add_node("enforce", _enforce)
    graph.add_node("check", _check)
    graph.add_edge(START, "write")
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
) -> ArchitectResult:
    """Design a SkillSpec for a screened request. At most MAX_ATTEMPTS model calls."""
    if analyzed.safety is None:
        raise NotScreened("this request was not safety-screened; use screen_and_analyze")
    if analyzed.needs_clarification:
        raise NotReady("this request still has open clarifying questions")
    final: _State = await _GRAPH.ainvoke(
        {"analyzed": analyzed, "existing_names": tuple(existing_names), "progress": on_progress}
    )
    spec = final.get("spec")
    if on_progress:
        on_progress("done" if spec is not None else "failed", final.get("attempt", 0))
    return ArchitectResult(
        ok=spec is not None,
        spec=spec,
        attempts=final.get("attempt", 0),
        issues=tuple(final.get("issues", [])),
        prompt_versions={p: load_prompt(p).version for p in (GENERATE, REPAIR)},
    )
