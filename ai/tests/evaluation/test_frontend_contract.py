"""The frontend contract's generated files (docs/ai/frontend-contract/) match the code."""

import json

from evaluation.contract.build import OUT_DIR, build, check_ai16, check_gap_files, stale


def _example(name: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((OUT_DIR / "examples" / name).read_text(encoding="utf-8"))
    return data


async def test_generated_files_are_current() -> None:
    files = await build()
    assert stale(files) == [], "run: python -m evaluation.contract export"
    assert check_ai16(files) == []


def test_gap_examples_are_valid_gap_checks() -> None:
    assert check_gap_files() == []


def test_needs_input_has_questions_only_from_analyze() -> None:
    """The rule the contract states for FE: analyze's needs_input carries the questions;
    design's needs_input carries none (value null, error_code open_questions)."""
    analyzed = _example("analyze-needs-input.result.json")
    assert analyzed["status"] == "needs_input" and analyzed["error_code"] is None
    value = analyzed["value"]
    assert isinstance(value, dict) and 3 <= len(value["questions"]) <= 5
    assert value["needs_clarification"] is True and value["answers"] == []

    designed = _example("design-needs-input-no-value.result.json")
    assert designed["status"] == "needs_input" and designed["error_code"] == "open_questions"
    assert designed["value"] is None


def test_clarify_never_asks_again() -> None:
    for name in ("clarify-answered.result.json", "clarify-all-skipped.result.json"):
        result = _example(name)
        value = result["value"]
        assert result["status"] == "ok" and isinstance(value, dict)
        assert value["needs_clarification"] is False
