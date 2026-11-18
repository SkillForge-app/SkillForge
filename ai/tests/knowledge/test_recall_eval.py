"""The AI-11 recall evaluation (evaluation/retrieval): data, metrics, decision rule, report.

The end-to-end test swaps the local model for deterministic fake vectors, so it runs offline;
the real numbers come from `python -m evaluation.retrieval run`.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from core.knowledge import ExtractConfig, extract_page
from core.knowledge.types import Passage
from core.llm.fake import fake_vector
from evaluation.extraction.report import page_configs
from evaluation.retrieval.__main__ import main
from evaluation.retrieval.data import indexed_pages, load_candidates, load_questions
from evaluation.retrieval.evaluate import (
    BASELINE,
    CHUNK_SIZES,
    RunResult,
    _decision,
    decide,
    evaluate,
    hit_rank,
)
from evaluation.retrieval.report import render_markdown, write_report

QUESTIONS = load_questions()
CANDIDATES = load_candidates()


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_question_set_shape() -> None:
    assert len(QUESTIONS.questions) >= 40
    assert {q.domain for q in QUESTIONS.questions} == {"marketing", "technology/ai"}
    assert len({q.page for q in QUESTIONS.questions}) >= 9
    assert not any(norm(q.evidence) in norm(q.question) for q in QUESTIONS.questions)


def test_every_evidence_phrase_is_in_its_page() -> None:
    labels = indexed_pages(QUESTIONS)
    configs = page_configs(labels, ExtractConfig())
    texts = {
        label.file: norm(
            extract_page(
                label.path.read_bytes(), url=str(label.url), retrieved=label.retrieved,
                config=configs[label.file],
            ).text
        )
        for label in labels
    }  # fmt: skip
    missing = [q.id for q in QUESTIONS.questions if norm(q.evidence) not in texts[q.page]]
    assert missing == []


def test_candidates_are_pinned_local_models() -> None:
    assert set(CANDIDATES) == {"minilm-l6", "bge-small", "bge-base"}
    for candidate in CANDIDATES.values():
        role = candidate.model_config_for().role("embedding")
        assert role.model.startswith("local/") and role.dimensions == candidate.dimensions
    assert CANDIDATES["bge-small"].local == load_config_local()  # the shipped choice


def load_config_local() -> object:
    from core.llm import load_config

    return load_config().role("embedding").local


def passage(url: str, text: str, n: int = 1) -> Passage:
    data = {"chunk_id": f"x.org-{n:08d}", "text": text, "source_url": url, "title": "T",
            "retrieved": "2026-10-25"}  # fmt: skip
    return Passage.model_validate_json(json.dumps(data))


def test_hit_rank_needs_the_right_page_and_the_evidence() -> None:
    url = "https://a.example/"
    found = [
        passage("https://b.example/", "Opt-out requests are honoured WITHIN 10 business days.", 1),
        passage(url, "Something else.", 2),
        passage(url, "You must act within  10 business\ndays.", 3),
    ]
    assert hit_rank(found, url, "within 10 business days") == 3
    assert hit_rank(found, url, "never said") is None


def run(system: str, words: int, hits: int, total: int = 40, seconds: float = 1.0) -> RunResult:
    ranks = {f"q{i:02d}": (1 if i < hits else None) for i in range(total)}
    dims = CANDIDATES[system].dimensions if system in CANDIDATES else None
    return RunResult(system, words, 100, ranks, seconds, 1.0, dims)


def test_recall_and_mrr() -> None:
    r = RunResult("x", 180, 10, {"q01": 1, "q02": 2, "q03": None, "q04": 5})
    assert (r.recall(1), r.recall(5), r.mrr) == (0.25, 0.75, round((1 + 0.5 + 0.2) / 4, 4))


def test_decision_rule_keeps_180_unless_another_size_clearly_wins() -> None:
    results = [run("bge-small", 120, 33), run("bge-small", 180, 32), run("bge-small", 250, 31)]
    assert decide(results, {"bge-small": CANDIDATES["bge-small"]}, 5).chunk_words == 180
    results.append(run("bge-small", 250, 34))
    results = [r for r in results if not (r.chunk_words == 250 and r.hits(5) == 31)]
    assert decide(results, {"bge-small": CANDIDATES["bge-small"]}, 5).chunk_words == 250


def test_decision_rule_breaks_ties_by_dimensions_then_speed() -> None:
    results = [
        run("bge-base", 180, 33, seconds=5),
        run("bge-small", 180, 32, seconds=2),
        run("minilm-l6", 180, 32, seconds=1),
    ]
    decision = decide(results, CANDIDATES, 5)
    assert decision.model == "minilm-l6"  # tied with bge-base; 384 dimensions; fastest
    results[0] = run("bge-base", 180, 36, seconds=5)
    assert decide(results, CANDIDATES, 5).model == "bge-base"  # clearly better: 768 earns it


def test_a_person_can_choose_but_must_say_who_and_why() -> None:
    results = [run("minilm-l6", 180, 32), run("bge-small", 180, 32)]
    picked = _decision(results, CANDIDATES, 5, ("bge-small", 180), "Ziad", "tie; stronger model")
    assert (picked.model, picked.rule_model, picked.chosen_by) == ("bge-small", "minilm-l6", "Ziad")
    with pytest.raises(ValueError, match="chosen_by"):
        _decision(results, CANDIDATES, 5, ("bge-small", 180), "", "")
    with pytest.raises(ValueError, match="not part of this run"):
        _decision(results, CANDIDATES, 5, ("bge-base", 180), "Ziad", "why")


async def test_end_to_end_offline_with_fake_vectors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_local(model: str, local: object, texts: list[str]) -> list[list[float]]:
        return [fake_vector(t, 384) for t in texts]

    monkeypatch.setattr("core.llm.litellm_gateway.embed_local", fake_local)
    report = await evaluate(
        QUESTIONS,
        {"bge-small": CANDIDATES["bge-small"]},
        sizes=[180],
        k=5,
        today=date(2026, 10, 25),
        choose=("bge-small", 180),
        chosen_by="a test",
        why="checking the report",
    )
    systems = {r.system for r in report.results}
    assert systems == {"bge-small", BASELINE}
    assert all(len(r.ranks) == len(QUESTIONS.questions) for r in report.results)
    baseline = next(r for r in report.results if r.system == BASELINE)
    assert baseline.recall(5) > 0.5  # word overlap works on these questions
    md = render_markdown(report, QUESTIONS)
    assert "Chosen by a test, not by the decision rule" in md and "Vector dimension: 384" in md
    first = write_report(report, QUESTIONS, tmp_path)
    second = write_report(report, QUESTIONS, tmp_path)
    assert first[0].name == "recall-2026-10-25.md" and second[0].name == "recall-2026-10-25-2.md"


def test_chunk_size_variants_fit_the_a4_limit() -> None:
    assert set(CHUNK_SIZES) == {120, 180, 250}
    assert all(s.max_chars <= 2000 for s in CHUNK_SIZES.values())
    assert CHUNK_SIZES[180] == CHUNK_SIZES[180].model_copy()  # the AI-10 default


def test_cli_check_data(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-data"]) == 0
    assert "40 questions" in capsys.readouterr().out
