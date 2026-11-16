"""AI-06 flag-only pre-check: Llama Guard's verdict becomes a flag for the reviewer, never a
decision. Placeholder texts only; the fake gateway stands in for the classifier."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from core.llm import ConfigError, FakeGateway, LLMRefused, load_config
from evaluation.safety import data
from evaluation.safety.__main__ import main
from evaluation.safety.generate import GENERATOR_PROMPTS, Candidate, GeneratedQA, write_candidates
from evaluation.safety.precheck import (
    GUARD_PROMPT,
    conversation,
    flags_for,
    guard_config,
    parse_reply,
    precheck,
    read_results,
)
from evaluation.safety.review import review

GUARD = "openrouter/meta-llama/llama-guard-4-12b"


@pytest.fixture(autouse=True)
def _own_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for split in ("redteam", "dev"):
        copy = tmp_path / data.FILES[split].name
        copy.write_bytes(data.FILES[split].read_bytes())
        monkeypatch.setitem(data.FILES, split, copy)
    load_config.cache_clear()
    yield
    load_config.cache_clear()


def candidate(cid: str, slot: str, category: str, **fields: object) -> Candidate:
    base: dict[str, object] = {
        "cid": cid,
        "split": "redteam",
        "slot": slot,
        "category": category,
        "attack": "direct",
        "origin": "generated",
        "generator": "openrouter/qwen/qwen3.8-flash",
        "text": f"placeholder request {cid} alpha bravo charlie",
        "created": "2026-11-16T00:00:00+00:00",
    }
    return Candidate.model_validate({**base, **fields})


def guard() -> FakeGateway:
    return FakeGateway(prompts_root=GENERATOR_PROMPTS, config=guard_config())


# ---------------------------------------------------------------- the classifier's family


def test_the_classifier_is_llama_guard_and_neither_claude_nor_qwen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert guard_config().role("redteam_guard").model == GUARD
    for banned in ("openrouter/qwen/qwen3.8-flash", "anthropic/claude-haiku-5-5"):
        monkeypatch.setenv("SKILLFORGE_MODEL_REDTEAM_GUARD", banned)
        load_config.cache_clear()
        with pytest.raises(ConfigError, match="must not be Claude or Qwen"):
            guard_config()


# ---------------------------------------------------------------- reading the answer


@pytest.mark.parametrize(
    ("reply", "parsed"),
    [
        ("safe", ("safe", [])),
        ("  safe\n", ("safe", [])),
        ("unsafe\nS2", ("unsafe", ["S2"])),
        ("unsafe\nS2,S14", ("unsafe", ["S2", "S14"])),
        ("unsafe\nS99", ("unsafe", [])),  # not a known code
        ("", None),
        ("I can't help with that.", None),
    ],
)
def test_parse_reply(reply: str, parsed: object) -> None:
    assert parse_reply(reply) == parsed


def test_flags_only_point_at_problems() -> None:
    [safe] = flags_for("safe", [], "weapons", GUARD)
    assert "llama-guard-4-12b) says SAFE: the item may not be harmful enough" in safe
    [differs] = flags_for("unsafe", ["S2"], "weapons", GUARD)
    assert "category S2 (Non-Violent Crimes) differs from slot category weapons" in differs
    assert flags_for("unsafe", ["S9"], "weapons", GUARD) == []  # a match: nothing to show
    assert flags_for("unsafe", ["S2", "S14"], "cyber_attack", GUARD) == []
    for flags in (safe, differs):
        assert "accept" not in flags.lower()


def test_two_turn_answers_are_part_of_what_is_classified() -> None:
    c = candidate(
        "t1", "r-07", "fraud_scams", attack="two_turn",
        answers=[GeneratedQA(question="What is it for?", answer="placeholder answer")],
    )  # fmt: skip
    text = conversation(c)
    assert c.text in text and "What is it for?" in text and "placeholder answer" in text


# ---------------------------------------------------------------- the run


async def test_precheck_records_flags_and_never_sends_child_safety(tmp_path: Path) -> None:
    candidates, results = tmp_path / "c.jsonl", tmp_path / "p.jsonl"
    write_candidates(
        [
            candidate("w1", "r-13", "weapons"),
            candidate("k1", "r-31", "child_safety", origin="adapted"),
            candidate("x1", "r-01", "cyber_attack", status="rejected"),
        ],
        candidates,
    )
    fake = guard()
    fake.register_text(GUARD_PROMPT, "unsafe\nS2")
    run = await precheck(fake, candidates_path=candidates, results_path=results)

    sent = [c.inputs or {} for c in fake.calls]
    assert run.calls == 1 and len(sent) == 1  # child_safety and non-pending never sent
    assert "placeholder request w1" in sent[0]["conversation"]
    [result] = run.checked
    assert (result.cid, result.verdict, result.hazards) == ("w1", "unsafe", ["S2"])
    assert result.classifier == "fake" and "differs from slot category weapons" in result.flags[0]
    assert read_results(results) == {"w1": result}

    again = await precheck(fake, candidates_path=candidates, results_path=results)
    assert again.calls == 0  # only unchecked candidates


@pytest.mark.parametrize(
    ("reply", "error", "note"),
    [
        ("", None, "an empty answer"),
        ("no idea", None, "an unreadable answer"),
        (None, LLMRefused("refused"), "LLMRefused"),
    ],
)
async def test_empty_unreadable_or_refused_answers_are_skipped(
    tmp_path: Path, reply: str | None, error: Exception | None, note: str
) -> None:
    candidates, results = tmp_path / "c.jsonl", tmp_path / "p.jsonl"
    write_candidates([candidate("w1", "r-13", "weapons")], candidates)
    fake = guard()
    if reply is not None:
        fake.register_text(GUARD_PROMPT, reply)
    if error is not None:
        fake.register_error(GUARD_PROMPT, error)
    run = await precheck(fake, candidates_path=candidates, results_path=results)
    assert run.checked == [] and len(run.skipped) == 1 and note in run.skipped[0]
    assert not results.exists()  # still unchecked: a later run tries again


def test_the_cli_refuses_to_precheck_without_live(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["precheck"]) == 2
    assert f"refusing to call {GUARD} without --live" in capsys.readouterr().out


# ---------------------------------------------------------------- review shows the flag only


def test_review_shows_a_flag_under_the_candidate_and_nothing_when_clean(tmp_path: Path) -> None:
    candidates, results = tmp_path / "c.jsonl", tmp_path / "p.jsonl"
    write_candidates(
        [candidate("w1", "r-04", "cyber_attack", attack="education_wrapper"),
         candidate("w2", "r-05", "cyber_attack", attack="authority_claim")],
        candidates,
    )  # fmt: skip
    results.write_text(
        '{"cid": "w1", "verdict": "safe", "hazards": [], "classifier": "' + GUARD + '", '
        '"flags": ["classifier (llama-guard-4-12b) says SAFE: the item may not be harmful '
        'enough"], "checked_at": "2026-11-16T00:00:00+00:00"}\n'
        '{"cid": "w2", "verdict": "unsafe", "hazards": ["S2"], "classifier": "' + GUARD + '", '
        '"flags": [], "checked_at": "2026-11-16T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    shown: list[str] = []
    answers = iter(["s", "s"])  # skip both: the flag decides nothing
    review(
        "redteam", "ziad", ask=lambda _: next(answers), say=shown.append,
        today=date(2026, 11, 16), candidates_path=candidates, precheck_path=results,
    )  # fmt: skip
    flags = [line for line in shown if "⚑" in line]
    assert flags == [
        "  ⚑ classifier (llama-guard-4-12b) says SAFE: the item may not be harmful enough"
    ]
    w2 = shown.index(next(line for line in shown if line.startswith("r-05")))
    assert not any("⚑" in line for line in shown[w2:])
