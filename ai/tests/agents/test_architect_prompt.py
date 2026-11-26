"""architect/generate v2 states the rules validate_spec enforces, with the code's own values.

Every number and string the prompt gives the model is a template input computed from the code
(core/spec). These tests read the same values by another route and compare them with the
rendered prompt, so a later schema or validator change fails here instead of the prompt
silently drifting from what is enforced.
"""

import re
from typing import Any, get_args

import pytest
from pydantic import StringConstraints

from core.agents.architect import GENERATE, _generate_inputs, length_limits, max_length
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


def rendered() -> str:
    analyzed = load_items("all")[3].analyzed
    return load_prompt(GENERATE).render(_generate_inputs(analyzed, ()))[0]["content"]


def alias_max(alias: Any) -> int:
    (constraint,) = [m for m in get_args(alias)[1:] if isinstance(m, StringConstraints)]
    assert constraint.max_length is not None
    return constraint.max_length


def test_version_2() -> None:
    assert load_prompt(GENERATE).version == 2


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


def test_reserved_words_are_the_validators() -> None:
    text = rendered()
    words = {w for ws in RESERVED_NAME_WORDS.values() for w in ws}
    line = next(x for x in text.splitlines() if x.startswith("- skill.name:"))
    assert set(re.findall(r'"([a-z]+)"', line)) == words
    for word in words:  # and each one is what validate_spec rejects
        bad = SPEC.model_dump(mode="json")
        bad["skill"]["name"] = f"{word}-helper"
        bad["targets"] = ["claude"]
        codes = {i.code for i in validate_spec(bad).errors}
        assert "reserved_name" in codes


def test_comment_with_sources_never_reaches_the_model() -> None:
    text = rendered()
    assert "{#" not in text and "core/spec/models.py" not in text
    assert text.startswith("You are the Skill Architect")
    assert "\n\n- expertise.principles" not in text  # no stray blank line after the list
