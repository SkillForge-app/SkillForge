"""Gap Checker (AI-08): text, cards, the fake index, verdicts, the labelled set and metrics.

Fake gateway (hash-based embeddings), no network; `pytest -m model` runs the real local model.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest
import yaml

from core.analysis import (
    AnalyzedRequest,
    AnalyzerInfo,
    FixtureSkillIndex,
    GapSettings,
    IndexInfo,
    SkillCard,
    check_gap,
    load_settings,
    request_text,
    skill_text,
)
from core.analysis.gap_checker import load_cards
from core.llm import ConfigError, FakeGateway, embed, load_config
from core.spec import load_spec
from evaluation.common import AI_ROOT, wilson_interval
from evaluation.gap import __main__ as gap_cli
from evaluation.gap.__main__ import main
from evaluation.gap.data import (
    CARDS_PATH,
    LabelledRequest,
    Review,
    check_data,
    load_fixture_cards,
    load_pairs,
)
from evaluation.gap.evaluate import (
    Counts,
    ScoreTable,
    best_threshold,
    confusion,
    pair_counts,
    request_outcomes,
)
from evaluation.gap.report import (
    VariantResult,
    run_test,
    settings_text,
    write_test_report,
    write_tuning,
)

SPECS = ["ai-engineer", "marketing-strategist", "review-nda"]


def analyzed(
    summary: str = "A skill that reviews NDAs.", domain: str = "legal/contracts"
) -> AnalyzedRequest:
    return AnalyzedRequest(
        request="Build me a skill.",
        kind="task",
        domain=domain,
        risk="high" if domain.startswith("legal") else "low",
        summary=summary,
        expected_outputs=["clause risk list"],
        needs_clarification=False,
        analyzer=AnalyzerInfo(prompt_id="test", prompt_version=1),
    )


def card(name: str, domain: str = "legal/contracts", **extra: object) -> SkillCard:
    return SkillCard.model_validate(
        {
            "id": f"registry:{name}",
            "name": name,
            "title": name.replace("-", " ").title(),
            "description": f"Does {name}.",
            "kind": "task",
            "domain": domain,
            "source": "registry",
            **extra,
        }
    )


SETTINGS = GapSettings(
    version="t",
    request_text="structured",
    query_prefix=False,
    same_area_for_exists=False,
    exists=0.8,
    similar=0.6,
    tuned_on="test",
)


@dataclass
class Stub:
    """An index that returns fixed scores, for verdict and merge tests."""

    results: list[tuple[SkillCard, float]]
    model: str | None = None
    dimensions: int | None = None

    def info(self) -> IndexInfo:
        role = load_config().role("embedding")
        return IndexInfo(
            len(self.results), self.model or role.model, self.dimensions or role.dimensions
        )

    async def search(self, vector: Sequence[float], k: int) -> list[tuple[SkillCard, float]]:
        return sorted(self.results, key=lambda p: (-p[1], p[0].id))[:k]


# ------------------------------------------------------------------ text


def test_request_text_variants() -> None:
    a = analyzed("A skill that reviews NDAs before signing.")
    assert request_text(a, "summary") == "A skill that reviews NDAs before signing."
    assert request_text(a, "structured") == (
        "A task skill for legal contracts. A skill that reviews NDAs before signing. "
        "Outputs: clause risk list."
    )
    assert request_text(a) == request_text(a, "structured")


def test_skill_text_never_includes_avoid_when() -> None:
    spec = load_spec(AI_ROOT / "examples/skillspec/review-nda.yaml")
    text = skill_text(SkillCard.from_spec(spec))
    assert text.startswith("Review an NDA. A task skill for legal contracts.")
    assert spec.triggers.use_when[0] in text
    for avoid in spec.triggers.avoid_when:
        assert avoid not in text


def test_an_arabic_request_is_matched_on_its_english_summary() -> None:
    gd41 = next(r for r in load_pairs("dev").requests if r.language == "ar")
    text = request_text(gd41.analyzed())
    assert gd41.analysis.summary in text and not any("؀" <= ch <= "ۿ" for ch in text)


@pytest.mark.parametrize("name", SPECS)
def test_a_card_from_a_spec(name: str) -> None:
    spec = load_spec(AI_ROOT / f"examples/skillspec/{name}.yaml")
    c = SkillCard.from_spec(spec, source="corpus")
    assert (c.id, c.name, c.domain) == (f"corpus:{name}", name, spec.skill.domain)
    assert c.use_when == list(spec.triggers.use_when) and c.description == spec.skill.summary


def test_the_fixture_cards_load(tmp_path: Path) -> None:
    cards = load_cards(CARDS_PATH)
    assert len(cards) == 48 and len({c.id for c in cards}) == 48
    assert {c.source for c in cards} == {"registry", "corpus"}
    assert all(c.licence == "own" and c.url for c in cards if c.source == "corpus")
    twice = tmp_path / "skills.yaml"
    entry = card("x-skill").model_dump(mode="json")
    twice.write_text(yaml.safe_dump({"cards": [entry, entry]}), encoding="utf-8")
    with pytest.raises(ConfigError, match="unique"):
        load_cards(twice)


# ------------------------------------------------------------------ the fake index


async def test_the_fixture_index_ranks_an_exact_text_first(fake: FakeGateway) -> None:
    index = FixtureSkillIndex(CARDS_PATH)
    target = next(c for c in index.cards if c.name == "meeting-minutes-writer")
    [vector] = await embed([skill_text(target)])
    results = await index.search(vector, 3)
    assert results[0][0].id == target.id and results[0][1] == pytest.approx(1.0, abs=1e-5)
    assert len(results) == 3 and results[0][1] > results[1][1]
    assert index.info().count == 48 and index.info().model == load_config().role("embedding").model


async def test_ties_are_broken_by_card_id(fake: FakeGateway) -> None:
    same = {"title": "Same", "description": "Same text.", "name": "same-b"}
    b = card("same-b").model_copy(update=same | {"id": "registry:same-b"})
    a = card("same-a").model_copy(update=same | {"id": "registry:same-a", "name": "same-a"})
    index = FixtureSkillIndex(cards=[b, a])
    [vector] = await embed([skill_text(a)])
    assert [c.id for c, _ in await index.search(vector, 2)] == [
        "registry:same-a",
        "registry:same-b",
    ]


def test_a_fixture_index_needs_a_path_or_cards() -> None:
    with pytest.raises(ValueError):
        FixtureSkillIndex()
    with pytest.raises(ValueError):
        FixtureSkillIndex(CARDS_PATH, cards=[])
    assert FixtureSkillIndex(cards=[]).info() == IndexInfo(0, None, None)


# ------------------------------------------------------------------ verdicts


@pytest.mark.parametrize(
    ("score", "verdict"),
    [(0.95, "exists"), (0.8, "exists"), (0.79, "similar"), (0.6, "similar"), (0.59, "new")],
)
async def test_the_verdict_comes_from_the_top_score(
    fake: FakeGateway, score: float, verdict: str
) -> None:
    result = await check_gap(
        analyzed(), indexes=[Stub([(card("review-nda"), score)])], settings=SETTINGS
    )
    assert result.verdict == verdict
    assert (result.exists_threshold, result.similar_threshold) == (0.8, 0.6)
    assert result.matches[0].skill.id == "registry:review-nda"


async def test_no_skills_means_new(fake: FakeGateway) -> None:
    result = await check_gap(analyzed(), indexes=[Stub([])], settings=SETTINGS)
    assert result.verdict == "new" and result.matches == []


async def test_two_indexes_merge_to_the_best_score_per_skill(fake: FakeGateway) -> None:
    nda, lease = card("review-nda"), card("lease-review")
    registry = Stub([(nda, 0.7), (lease, 0.5)])
    corpus = Stub([(nda, 0.9), (card("draft-nda"), 0.65)])
    result = await check_gap(analyzed(), indexes=[registry, corpus], k=2, settings=SETTINGS)
    # review-nda keeps its best score (0.9, not 0.7); draft-nda (0.65) beats lease-review (0.5)
    assert [(m.skill.name, m.score) for m in result.matches] == [
        ("review-nda", 0.9),
        ("draft-nda", 0.65),
    ]
    assert result.verdict == "exists"


async def test_the_area_gate_turns_a_cross_area_exists_into_similar(fake: FakeGateway) -> None:
    gated = SETTINGS.model_copy(update={"same_area_for_exists": True})
    other = card("hr-thing", domain="hr/recruiting")
    assert (
        await check_gap(analyzed(), indexes=[Stub([(other, 0.9)])], settings=gated)
    ).verdict == "similar"
    assert (
        await check_gap(analyzed(), indexes=[Stub([(other, 0.9)])], settings=SETTINGS)
    ).verdict == "exists"


async def test_an_index_of_another_model_is_refused(fake: FakeGateway) -> None:
    with pytest.raises(ConfigError, match="rebuild"):
        await check_gap(
            analyzed(), indexes=[Stub([(card("x-y"), 0.9)], model="local/other")], settings=SETTINGS
        )
    with pytest.raises(ConfigError, match="rebuild"):
        await check_gap(
            analyzed(), indexes=[Stub([(card("x-y"), 0.9)], dimensions=768)], settings=SETTINGS
        )
    with pytest.raises(ValueError, match="k must be"):
        await check_gap(analyzed(), indexes=[], k=0, settings=SETTINGS)


def test_settings_are_checked() -> None:
    load_settings.cache_clear()
    assert load_settings().similar < load_settings().exists
    with pytest.raises(ValueError, match="below"):
        SETTINGS.model_validate({**SETTINGS.model_dump(), "similar": 0.9})


# ------------------------------------------------------------------ the labelled set


def test_the_labelled_set_is_valid() -> None:
    cards = load_fixture_cards()
    dev, test = load_pairs("dev"), load_pairs("test")
    assert check_data(cards, [dev, test]) == []
    assert (len(dev.requests), len(test.requests)) == (41, 61)
    assert {r.best_label for r in dev.requests} == {"match", "near_miss", "no_match"}
    assert not {r.id for r in dev.requests} & {r.id for r in test.requests}


def test_check_data_finds_problems() -> None:
    cards = load_fixture_cards()
    dev = load_pairs("dev")
    bad = dev.requests[0].model_copy(update={"match": ["registry:nope"]})
    copy = load_pairs("test").requests[0].model_copy(update={"text": dev.requests[1].text})
    broken_dev = dev.model_copy(update={"requests": [bad, *dev.requests[1:]]})
    broken_test = load_pairs("test").model_copy(update={"requests": [copy]})
    problems = check_data(cards, [broken_dev, broken_test])
    assert any("unknown card registry:nope" in p for p in problems)
    assert any("same text is in dev and test" in p for p in problems)
    assert any("test: no request is" in p for p in problems)


def test_a_labelled_request() -> None:
    r = load_pairs("dev").requests[10]  # gd-11, the detailed NDA request
    assert r.label("registry:review-nda") == "match"
    assert r.label("corpus:draft-nda-template") == "near_miss"
    assert r.label("registry:meal-planner") == "no_match" and r.best_label == "match"
    assert r.analyzed().risk == "high" and r.analyzed().analyzer.prompt_id == "gold-labels"
    with pytest.raises(ValueError, match="both match and near_miss"):
        LabelledRequest.model_validate({**r.model_dump(), "near_miss": ["registry:review-nda"]})


# ------------------------------------------------------------------ metrics


def test_counts() -> None:
    c = Counts(tp=6, fp=2, fn=4)
    assert (c.precision, c.recall) == (0.75, 0.6)
    assert c.f_beta(1) == pytest.approx(2 * 0.75 * 0.6 / 1.35)
    assert c.f_beta(0.5) == pytest.approx(1.25 * 0.45 / (0.25 * 0.75 + 0.6))
    assert Counts(0, 0, 3).precision == 0.0 and Counts(0, 0, 0).f_beta(1) == 0.0


def test_wilson_interval() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)
    low, high = wilson_interval(8, 10)
    assert (round(low, 3), round(high, 3)) == (0.49, 0.943)
    assert wilson_interval(10, 10)[1] == 1.0


def tiny_table() -> ScoreTable:
    dev = load_pairs("dev")
    requests = [dev.requests[10], dev.requests[20], dev.requests[32]]  # NDA, NDA template, speech
    cards = {c.id: c for c in load_fixture_cards()}
    columns = [
        cards["registry:review-nda"],
        cards["corpus:draft-nda-template"],
        cards["registry:meal-planner"],
    ]
    scores = np.array([[0.9, 0.7, 0.1], [0.75, 0.85, 0.2], [0.3, 0.3, 0.4]])
    return ScoreTable(requests, columns, scores)


def test_pair_counts_and_the_best_threshold() -> None:
    table = tiny_table()
    # match pairs: (NDA, review-nda) 0.9 and (template, draft-nda) 0.85
    assert pair_counts(table, 0.8, positive=["match"]) == Counts(tp=2, fp=0, fn=0)
    assert pair_counts(table, 0.7, positive=["match"]) == Counts(tp=2, fp=2, fn=0)
    related = pair_counts(table, 0.7, positive=["match", "near_miss"])
    assert related == Counts(tp=4, fp=0, fn=0)
    t, counts = best_threshold(table, positive=["match"], beta=0.5)
    assert t == 0.85 and counts == Counts(tp=2, fp=0, fn=0)  # ties go to the higher threshold
    assert best_threshold(table, positive=["match", "near_miss"], beta=1, below=0.85)[0] == 0.7


def test_request_outcomes_and_confusion() -> None:
    outcomes = request_outcomes(tiny_table(), SETTINGS)
    assert [(o.verdict, o.gold, o.correct) for o in outcomes] == [
        ("exists", "exists", True),
        ("exists", "exists", True),
        ("new", "new", True),
    ]
    assert confusion(outcomes)["exists"]["exists"] == 2


# ------------------------------------------------------------------ tune and report (fake model)


def test_write_tuning_sets_the_yaml_and_never_overwrites(tmp_path: Path) -> None:
    result = VariantResult(
        "structured",
        {"request_text": "structured", "query_prefix": False, "same_area_for_exists": False},
        0.81,
        Counts(5, 1, 2),
        0.66,
        Counts(9, 3, 4),
    )
    settings_path = tmp_path / "gap_checker.yaml"
    dev, cards = load_pairs("dev"), load_fixture_cards()
    md, js = write_tuning(
        dev,
        cards,
        [result],
        out_dir=tmp_path,
        settings_path=settings_path,
        today=date(2026, 10, 27),
    )
    again, _ = write_tuning(
        dev,
        cards,
        [result],
        out_dir=tmp_path,
        settings_path=settings_path,
        today=date(2026, 10, 27),
    )
    assert (md.name, again.name) == ("gap-dev-2026-10-27.md", "gap-dev-2026-10-27-2.md")
    tuned = load_settings(settings_path)
    assert (tuned.exists, tuned.similar, tuned.request_text) == (0.81, 0.66, "structured")
    assert tuned.tuned_on == "evaluation/gap/reports/gap-dev-2026-10-27-2.md"
    assert json.loads(js.read_text(encoding="utf-8"))["chosen"] == "structured"
    assert "(chosen)" in md.read_text(encoding="utf-8")
    assert settings_text(result, version="v", tuned_on="x").count("\n") == 13


async def test_run_test_and_its_report(fake: FakeGateway, tmp_path: Path) -> None:
    small = load_pairs("test").model_copy(update={"requests": load_pairs("test").requests[:4]})
    cards = load_fixture_cards()
    result = await run_test(small, cards, SETTINGS)
    assert len(result.outcomes) == 4 and result.agree == 4  # check_gap agrees with the table
    md, js = write_test_report(small, cards, result, out_dir=tmp_path, today=date(2026, 10, 27))
    text = md.read_text(encoding="utf-8")
    assert "## Done-when: precision on labelled pairs" in text and "95% CI" in text
    assert json.loads(js.read_text(encoding="utf-8"))["requests"] == 4


def test_the_cli(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    assert main(["check-data"]) == 0
    assert "OK" in capsys.readouterr().out
    # `report` refuses before loading the model: untuned settings, then draft test labels.
    real = load_settings()
    untuned = real.model_copy(update={"tuned_on": "not tuned yet (placeholders)"})
    monkeypatch.setattr(gap_cli, "load_settings", lru_cache(lambda: untuned))
    assert main(["report"]) == 2
    assert "not tuned" in capsys.readouterr().err
    tuned = real.model_copy(update={"tuned_on": "evaluation/gap/reports/gap-dev-x.md"})
    monkeypatch.setattr(gap_cli, "load_settings", lru_cache(lambda: tuned))
    draft = load_pairs("test").model_copy(update={"review": Review(status="draft")})
    monkeypatch.setattr(gap_cli, "load_pairs", lambda split: draft)
    assert main(["report"]) == 2
    assert "still draft" in capsys.readouterr().err


# ------------------------------------------------------------------ the real model (opt-in)


@pytest.mark.model
async def test_real_model_tells_review_from_drafting() -> None:
    """`pytest -m model`: the local bge-small separates a seed skill from its near-miss."""
    index = FixtureSkillIndex(CARDS_PATH)
    pairs = {r.id: r for r in load_pairs("dev").requests}
    review = await check_gap(pairs["gd-11"].analyzed(), indexes=[index], k=3)
    draft = await check_gap(pairs["gd-21"].analyzed(), indexes=[index], k=3)
    assert review.matches[0].skill.id == "registry:review-nda"
    assert draft.matches[0].skill.id == "corpus:draft-nda-template"
