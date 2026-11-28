"""architect/generate v3 states the rules validate_spec enforces, with the code's own values.

Every number and string the prompt gives the model is a template input computed from the code
(core/spec). These tests read the same values by another route and compare them with the
rendered prompt, so a later schema or validator change fails here instead of the prompt
silently drifting from what is enforced.
"""

import re
from itertools import combinations
from typing import Any, get_args

import pytest
from pydantic import StringConstraints

from core.agents.architect import (
    GENERATE,
    _generate_inputs,
    enforce,
    length_limits,
    max_length,
)
from core.llm import load_prompt
from core.spec import (
    PLATFORM_LIMITS,
    RESERVED_NAME_WORDS,
    TARGETS,
    draft_description,
    load_spec,
    validate_spec,
)
from core.spec.models import (
    Evaluation,
    Id,
    Line,
    Output,
    Procedure,
    SkillMeta,
    SkillName,
    Text,
    Title,
    Triggers,
)
from evaluation.architect.data import load_items
from evaluation.common import AI_ROOT

SPEC = load_spec(AI_ROOT / "examples" / "skillspec" / "ai-engineer.yaml")


def rendered(targets: list[str] | None = None) -> str:
    """The system prompt for one request; `targets`: the request's targets (None: as labelled)."""
    analyzed = load_items("all")[3].analyzed
    if targets is not None:
        analyzed = analyzed.model_copy(update={"targets": targets})
    return load_prompt(GENERATE).render(_generate_inputs(analyzed, ()))[0]["content"]


def alias_max(alias: Any) -> int:
    (constraint,) = [m for m in get_args(alias)[1:] if isinstance(m, StringConstraints)]
    assert constraint.max_length is not None
    return constraint.max_length


def test_version_3() -> None:
    assert load_prompt(GENERATE).version == 3


def test_length_limits_are_the_models_limits() -> None:
    summary = SkillMeta.model_fields["summary"].metadata
    expected = {
        "skill.name": alias_max(SkillName),
        "every id": alias_max(Id),
        "skill.title, procedure and output titles": alias_max(Title),
        "skill.summary": next(m.max_length for m in summary if isinstance(m, StringConstraints)),
        "each triggers.use_when / avoid_when item": alias_max(Line),
        "each expertise principle": alias_max(Text),
        "each procedure step": alias_max(Text),
        "each output section heading": alias_max(Line),
        "each guardrail rule": alias_max(Text),
        "each evaluation test_prompt and should_not_trigger prompt": alias_max(Text),
        "each evaluation rubric item": alias_max(Line),
    }
    text = rendered()
    for field, limit in expected.items():
        assert f"  - {field}: at most {limit}\n" in text, field
    assert {f["field"]: f["max"] for f in length_limits()} == expected


def test_grouped_labels_share_one_limit() -> None:
    """A label naming several fields is true only while they have the same limit."""
    assert max_length(Procedure, "title") == max_length(Output, "title") == alias_max(Title)
    assert max_length(Triggers, "avoid_when") == max_length(Triggers, "use_when")
    assert max_length(Evaluation, "should_not_trigger") == max_length(Evaluation, "test_prompts")
    assert max_length(Output, "id") == max_length(Procedure, "id")


def test_max_length_refuses_a_field_without_one() -> None:
    with pytest.raises(ValueError, match="no max_length"):
        max_length(SkillMeta, "version")


DESCRIPTION_RULE = re.compile(
    r'skill\.summary, then\s+"(?P<use>[^"]*)", then the use_when items joined by '
    r'"(?P<join>[^"]*)", then "(?P<end>[^"]*)"; and only if\s+there are avoid_when items: '
    r'"(?P<not>[^"]*)", then the '
    r'avoid_when items joined by "(?P<join2>[^"]*)", then "(?P<end2>[^"]*)"\.\s+'
    r"That whole description must be at most (?P<limit>\d+) characters"
)


@pytest.mark.parametrize("avoid", [True, False])
def test_description_rule_builds_what_the_validator_measures(avoid: bool) -> None:
    m = DESCRIPTION_RULE.search(rendered())
    assert m is not None
    spec = SPEC if avoid else SPEC.model_copy(update={"triggers": Triggers(use_when=["a", "b"])})
    t = spec.triggers
    by_prompt = spec.skill.summary + m["use"] + m["join"].join(t.use_when) + m["end"]
    if t.avoid_when:
        by_prompt += m["not"] + m["join2"].join(t.avoid_when) + m["end2"]
    assert by_prompt == draft_description(spec)
    assert int(m["limit"]) == min(PLATFORM_LIMITS[x].description for x in TARGETS)


ALL_WORDS = sorted({w for ws in RESERVED_NAME_WORDS.values() for w in ws})


def name_rule_words(targets: list[str]) -> set[str]:
    """The words the rendered prompt forbids in skill.name (empty: no rule stated)."""
    text = rendered(targets)
    start = text.index("- skill.name:")
    rule = text[start : text.index("- skill.version", start)]
    return set(re.findall(r'"([a-z]+)"', rule)) if "must never contain" in rule else set()


def rejects(targets: list[str], word: str) -> bool:
    """Whether validate_spec rejects a name with `word`, for a spec built for a request with
    these targets (enforce gives the spec its final targets, as in the Architect)."""
    analyzed = load_items("all")[3].analyzed.model_copy(update={"targets": targets})
    data = SPEC.model_dump(mode="json")
    data["skill"]["name"] = f"{word}-helper"
    spec = enforce(analyzed, data)
    return "reserved_name" in {i.code for i in validate_spec(spec).errors}


def test_claude_target_states_the_rule_and_the_validator_rejects() -> None:
    assert name_rule_words(["claude"]) == set(ALL_WORDS) == {"claude", "anthropic"}
    assert all(rejects(["claude"], w) for w in ALL_WORDS)


def test_codex_only_states_no_rule_and_the_validator_accepts() -> None:
    assert name_rule_words(["codex"]) == set()
    assert "must never contain" not in rendered(["codex"])
    assert not any(rejects(["codex"], w) for w in ALL_WORDS)


SUBSETS = [list(c) for n in range(len(TARGETS) + 1) for c in combinations(TARGETS, n)]


@pytest.mark.parametrize("targets", SUBSETS, ids=lambda t: "+".join(t) or "default")
def test_the_prompt_states_the_rule_exactly_when_the_validator_applies_it(
    targets: list[str],
) -> None:
    """For every combination of targets (none = the defaults enforce gives): the prompt forbids
    a word in the name if and only if validate_spec rejects a name with that word. Fails as soon
    as the prompt's condition and the validator's condition diverge."""
    stated = name_rule_words(targets)
    for word in ALL_WORDS:
        assert (word in stated) is rejects(targets, word), (targets, word)


def test_comment_with_sources_never_reaches_the_model() -> None:
    text = rendered()
    assert "{#" not in text and "core/spec/models.py" not in text
    assert text.startswith("You are the Skill Architect")
    assert "\n\n- expertise.principles" not in text  # no stray blank line after the list
