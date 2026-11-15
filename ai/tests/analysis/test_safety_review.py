"""AI-06 review: only accepted items enter the YAML, with their provenance and the reviewer.
Placeholder texts only."""

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from evaluation.safety import data
from evaluation.safety.generate import Candidate, GeneratedQA, read_candidates, write_candidates
from evaluation.safety.review import review
from evaluation.safety.seeds import Seed, write_seeds

TODAY = date(2026, 11, 16)


@pytest.fixture(autouse=True)
def _own_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for split in ("redteam", "dev"):
        copy = tmp_path / data.FILES[split].name
        copy.write_bytes(data.FILES[split].read_bytes())
        monkeypatch.setitem(data.FILES, split, copy)


def script(*answers: str) -> Iterator[str]:
    return iter(answers)


def asker(answers: Iterator[str]) -> Callable[[str], str]:
    def ask(prompt: str) -> str:
        try:
            return next(answers)
        except StopIteration:
            raise AssertionError(f"unexpected question: {prompt}") from None

    return ask


def candidate(cid: str, slot: str, text: str, **fields: object) -> Candidate:
    base: dict[str, object] = {
        "cid": cid,
        "split": "redteam",
        "slot": slot,
        "category": "cyber_attack",
        "attack": "direct",
        "origin": "generated",
        "generator": "openrouter/qwen/qwen3.8-flash",
        "text": text,
        "created": "2026-11-16T00:00:00+00:00",
    }
    return Candidate.model_validate({**base, **fields})


def test_review_accepts_edits_and_rejects_one_by_one(tmp_path: Path) -> None:
    benign = data.load_set("benign")[0].text
    path = tmp_path / "candidates.jsonl"
    write_candidates(
        [
            # r-04 (education_wrapper, generated): two candidates; accepting one supersedes the
            # other
            candidate(
                "c1",
                "r-04",
                "placeholder one alpha bravo charlie delta",
                attack="education_wrapper",
            ),
            candidate(
                "c2", "r-04", "placeholder two echo foxtrot golf hotel", attack="education_wrapper"
            ),
            # r-01 (direct, adapted): edited, then accepted
            candidate(
                "c3",
                "r-01",
                "placeholder three india juliet kilo lima",
                origin="adapted",
                dataset="harmbench",
                dataset_ref="hb-1",
            ),
            # r-05 (authority_claim): rejected
            candidate(
                "c4", "r-05", "placeholder four mike november oscar papa", attack="authority_claim"
            ),
            # r-06 (prompt_injection): a copy of a benign item, so it can't be accepted
            candidate("c5", "r-06", benign, attack="prompt_injection"),
        ],
        path,
    )
    answers = script(
        "a",  # c1 accepted
        "e",
        "placeholder edited quebec romeo sierra tango",
        "a",  # c3 edited, accepted
        "r",
        "too vague",  # c4 rejected
        "a",
        "r",
        "",  # c5: accept refused, then rejected
    )
    shown: list[str] = []
    counts = review(
        "redteam", "ziad", ask=asker(answers), say=shown.append, today=TODAY, candidates_path=path
    )

    assert counts == {"accepted": 2, "rejected": 2}
    assert any("can't accept it" in line for line in shown)
    status = {c.cid: (c.status, c.reason) for c in read_candidates(path)}
    assert status == {
        "c1": ("accepted", None),
        "c2": ("superseded", None),
        "c3": ("accepted", None),
        "c4": ("rejected", "too vague"),
        "c5": ("rejected", None),
    }
    saved = data.load_file("redteam")
    assert saved.version == "0.0.3" and saved.status == "incomplete"
    by_id = {r.id: r for r in saved.requests}
    assert set(by_id) == {"r-04", "r-01"}
    r04, r01 = by_id["r-04"], by_id["r-01"]
    assert (r04.origin, r04.generator, r04.reviewer, r04.reviewed_on, r04.edited) == (
        "generated",
        "openrouter/qwen/qwen3.8-flash",
        "ziad",
        TODAY,
        False,
    )
    assert (r04.category, r04.attack) == ("cyber_attack", "education_wrapper")
    assert (r01.origin, r01.dataset, r01.dataset_ref, r01.edited) == (
        "adapted",
        "harmbench",
        "hb-1",
        True,
    )
    assert r01.text == "placeholder edited quebec romeo sierra tango"
    assert "harmbench (MIT)" in (saved.source or "") and "ziad" in (saved.source or "")
    header = data.FILES["redteam"].read_text(encoding="utf-8")
    assert header.startswith("# ====") and "Item format" in header  # comments kept
    assert {i.code for i in data.check_data() if i.severity == "error"} == set()


def test_manual_mode_writes_child_safety_from_a_seed(tmp_path: Path) -> None:
    seeds_path = tmp_path / "seeds.jsonl"
    # r-31 is the first child_safety slot (two_turn style)
    write_seeds(
        [
            Seed(
                "simplesafetytests",
                "sst-9",
                "CC BY 2.0",
                "child_safety",
                "placeholder seed",
                False,
                "r-31",
            )
        ],
        seeds_path,
    )
    answers = script(
        "placeholder manual request uniform victor whiskey",  # r-31's text
        "What is it for?",
        "placeholder answer xray",
        "",  # one answer, then done
        "",
        "",
        "",
        "",
        "",  # skip r-32 .. r-36
    )
    counts = review(
        "redteam",
        "yousef",
        ask=asker(answers),
        say=lambda _: None,
        today=TODAY,
        manual=True,
        seeds_path=seeds_path,
    )
    assert counts == {"accepted": 1, "skipped": 5}
    [item] = data.load_file("redteam").requests
    assert (item.id, item.category, item.attack, item.origin) == (
        "r-31",
        "child_safety",
        "two_turn",
        "adapted",
    )
    assert (item.dataset, item.dataset_ref, item.generator, item.reviewer) == (
        "simplesafetytests",
        "sst-9",
        None,
        "yousef",
    )
    assert [(qa.question, qa.answer) for qa in item.answers] == [
        ("What is it for?", "placeholder answer xray")
    ]


def test_nothing_pending_changes_nothing(tmp_path: Path) -> None:
    before = data.FILES["redteam"].read_bytes()
    counts = review(
        "redteam",
        "ziad",
        ask=asker(script()),
        say=lambda _: None,
        today=TODAY,
        candidates_path=tmp_path / "none.jsonl",
    )
    assert not counts and data.FILES["redteam"].read_bytes() == before


def test_the_dev_block_half_gets_its_own_items(tmp_path: Path) -> None:
    path = tmp_path / "candidates.jsonl"
    write_candidates(
        [
            candidate(
                "d1",
                "sd-12",
                "placeholder dev yankee zulu amber basil",
                split="dev",
                category="fraud_scams",
                attack="authority_claim",
                answers=[],
            )
        ],
        path,
    )
    review(
        "dev", "ziad", ask=asker(script("a")), say=lambda _: None, today=TODAY, candidates_path=path
    )
    saved = data.load_file("dev")
    assert saved.version == "0.1.2"
    assert saved.requests[-1].id == "sd-12" and len(saved.requests) == 11
    assert (saved.source or "").startswith(
        "allow half written by the AI team; block half generated by"
    )


def test_two_turn_answers_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "candidates.jsonl"
    qa = [GeneratedQA(question="What is it for?", answer="placeholder answer coral")]
    write_candidates(
        [
            candidate(
                "t1",
                "r-07",
                "placeholder two turn cobalt denim ember",
                attack="two_turn",
                answers=qa,
            )
        ],
        path,
    )
    review(
        "redteam",
        "ziad",
        ask=asker(script("a")),
        say=lambda _: None,
        today=TODAY,
        candidates_path=path,
    )
    [item] = data.load_file("redteam").requests
    assert [(a.question, a.answer) for a in item.answers] == [
        ("What is it for?", "placeholder answer coral")
    ]
