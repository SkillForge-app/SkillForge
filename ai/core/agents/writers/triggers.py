"""Trigger description writer (AI-14): the description an agent reads to decide when to load
the skill, within each target platform's limit.

    descriptions = await write_descriptions(spec)        # {target: description}

One model call (prompt writers/triggers v1) writes the description from the spec's summary and
triggers. The code checks it for every target: not empty, no XML-like tag, at most
PLATFORM_LIMITS[target].description characters. A failing description gets one repair call;
still failing, that target falls back to core.spec.draft_description, which a valid spec always
fits. AI-14's done-when ("trigger accuracy measured in AI-17") is measured by AI-17 on these
descriptions and the seed benchmark's trigger prompts.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import Field, StringConstraints

from core.agents.writers.references import WriterRefused, WriterUnavailable
from core.llm import LLMOutputInvalid, LLMRefused, LLMUnavailable, complete
from core.spec import PLATFORM_LIMITS, Issue, SkillSpec, draft_description
from core.spec.models import SpecModel
from core.spec.validator import _XML_TAG

PROMPT = "writers/triggers"
MAX_CALLS = 2  # one write, one repair


class DescriptionDraft(SpecModel):
    # Longer than any limit on purpose: the code, not the schema, reports "too long".
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=4000)] = Field(
        description="When an agent should load the skill, and when not."
    )


@dataclass(frozen=True)
class Descriptions:
    by_target: dict[str, str]
    fallback: tuple[str, ...]  # targets that got draft_description
    calls: int
    issues: tuple[Issue, ...]  # the last checked draft's problems (empty when it passed)


def limit_for(targets: Sequence[str]) -> int:
    return min(PLATFORM_LIMITS[t].description for t in targets)


def description_issues(text: str, targets: Sequence[str]) -> list[Issue]:
    """Problems for one description, per target. Messages never include the description."""
    issues = []
    if not text.strip():
        issues.append(Issue("/description", "empty", "the description is empty"))
    if _XML_TAG.search(text):
        issues.append(Issue("/description", "xml_tag", "XML-like tags are not allowed"))
    for target in targets:
        limit = PLATFORM_LIMITS[target].description
        if len(text) > limit:
            issues.append(
                Issue(
                    f"/description/{target}",
                    "too_long",
                    f"{len(text)} characters; {target} allows at most {limit}",
                )
            )
    return issues


def _inputs(spec: SkillSpec, previous: str = "", issues: Sequence[Issue] = ()) -> dict[str, Any]:
    return {
        "skill_name": spec.skill.name,
        "skill_title": spec.skill.title,
        "summary": spec.skill.summary,
        "use_when": list(spec.triggers.use_when),
        "avoid_when": list(spec.triggers.avoid_when),
        "limit": limit_for(spec.targets),
        "previous": json.dumps({"description": previous}) if previous else "",
        "issues": [str(i) for i in issues],
    }


async def _call(inputs: dict[str, Any]) -> str | None:
    try:
        return (await complete(PROMPT, inputs, DescriptionDraft)).description
    except LLMRefused as exc:  # a subclass of LLMOutputInvalid: check it first
        raise WriterRefused("the model refused to write a description") from exc
    except LLMOutputInvalid:
        return None
    except LLMUnavailable as exc:
        raise WriterUnavailable(f"model unavailable: {type(exc).__name__}") from exc


async def describe(spec: SkillSpec) -> Descriptions:
    """The description for every target of the spec, with which targets fell back."""
    targets: list[str] = list(spec.targets)
    text = await _call(_inputs(spec))
    calls = 1
    issues = description_issues(text, targets) if text is not None else _invalid()
    if issues:
        repaired = await _call(_inputs(spec, text or "", issues))
        calls = 2
        if repaired is not None:
            text, issues = repaired, description_issues(repaired, targets)
    fallback_text = draft_description(spec)
    by_target: dict[str, str] = {}
    fallback: list[str] = []
    for target in targets:
        own = [i for i in issues if i.path in ("/description", f"/description/{target}")]
        if text is None or own:
            by_target[target] = fallback_text
            fallback.append(target)
        else:
            by_target[target] = text
    return Descriptions(by_target, tuple(fallback), calls, tuple(issues))


async def write_descriptions(spec: SkillSpec) -> dict[str, str]:
    """{target: description}, each within its platform's limit (see `describe`)."""
    return (await describe(spec)).by_target


def _invalid() -> list[Issue]:
    return [Issue("/description", "llm_output_invalid", "the reply did not match the schema")]


__all__ = [
    "DescriptionDraft",
    "Descriptions",
    "describe",
    "description_issues",
    "limit_for",
    "write_descriptions",
]
