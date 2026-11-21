"""AI-13 support threshold: the calibration pairs, the F1 pick, and the tracked report.

A stub embedder (bag of hashed words) stands in for the model; one `model` test runs the real
local bge-small (deselected by default: `pytest -m model`)."""

import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path

import pytest

from core.agents.writers.support import SUPPORT_THRESHOLD, support_scores
from core.knowledge.retrieval import load_fixtures
from evaluation.architect.support import best_f1, calibrate, calibration_pairs, sentences, write
from evaluation.common import AI_ROOT

DIMS = 128


async def stub_embed(texts: Sequence[str]) -> list[list[float]]:
    """Each word adds 1 to a hashed dimension: shared words mean similar vectors."""
    out = []
    for text in texts:
        v = [0.0] * DIMS
        for word in text.lower().split():
            v[int(hashlib.sha1(word.strip(".,;:").encode()).hexdigest(), 16) % DIMS] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / norm for x in v])
    return out


FIXTURE = """version: 9.9.9
passages:
  - chunk_id: tst-a-01
    domain: data/analytics
    source_url: https://a.example/one
    title: A
    retrieved: 2026-10-01
    text: >-
      Charts should start from the question the reader needs answered. Pick the chart type
      that matches the comparison you want the reader to make.
  - chunk_id: tst-b-01
    domain: data/analytics
    source_url: https://b.example/two
    title: B
    retrieved: 2026-10-01
    text: >-
      Analysts agree research questions and scope with stakeholders first. User needs come
      before any chosen tool or solution in every project.
  - chunk_id: tst-c-01
    domain: hr/recruiting
    source_url: https://c.example/three
    title: C
    retrieved: 2026-10-01
    text: >-
      Job adverts may not discourage applicants because of protected traits such as age.
"""


def test_sentences_keep_six_words_or_more() -> None:
    text = "Short one. This sentence has exactly six words. And another sentence here with seven."
    assert sentences(text) == [
        "This sentence has exactly six words.",
        "And another sentence here with seven.",
    ]


def test_best_f1_picks_the_separating_threshold_and_the_lower_on_ties() -> None:
    assert best_f1([0.9, 0.8, 0.75], [0.5, 0.6])["threshold"] == 0.75
    assert best_f1([0.9, 0.8], [0.5, 0.6])["f1"] == 1.0
    assert best_f1([0.9, 0.8], [0.5, 0.6])["threshold"] == 0.8  # the lowest perfect one


async def test_pairs_use_another_page_of_the_same_domain(tmp_path: Path) -> None:
    path = tmp_path / "passages.yaml"
    path.write_text(FIXTURE, encoding="utf-8")
    pairs = await calibration_pairs(load_fixtures(path), embed_fn=stub_embed)
    by_chunk = {p.chunk_id: p for p in pairs}
    assert {p.chunk_id for p in pairs} == {"tst-a-01", "tst-b-01", "tst-c-01"}
    assert by_chunk["tst-a-01"].other_id == "tst-b-01"  # same domain, other page
    assert by_chunk["tst-c-01"].other_id is None  # the only page of its domain: no negative
    assert all(p.negative is None or p.positive > p.negative for p in pairs)


async def test_calibrate_writes_a_report_that_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "passages.yaml"
    path.write_text(FIXTURE, encoding="utf-8")
    result = await calibrate(path=path, embed_fn=stub_embed, model="stub")
    assert result.fixtures == "passages.yaml 9.9.9" and 0.0 <= result.threshold <= 1.0
    md1, _ = write(result, tmp_path / "reports")
    md2, js2 = write(result, tmp_path / "reports")
    assert md1.name.endswith(".md") and md2.stem.endswith("-2")
    assert json.loads(js2.read_text(encoding="utf-8"))["method"].startswith("positive:")


def test_the_threshold_comes_from_the_tracked_calibration_report() -> None:
    reports = sorted(
        (AI_ROOT / "evaluation" / "architect" / "reports").glob("support-calibration-*.json")
    )
    assert reports, "the calibration report must be committed"
    saved = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert saved["threshold"] == SUPPORT_THRESHOLD
    assert saved["fixtures"].startswith("passages.yaml ")
    assert saved["model"] == "local/BAAI/bge-small-en-v1.5"


@pytest.mark.model
async def test_real_model_scores_a_paraphrase_above_an_unrelated_chunk() -> None:
    """`model` tests keep the real gateway: this embeds with the local bge-small."""
    [support, unrelated] = await support_scores(
        [
            (
                "Adverts must not put off older applicants.",
                ["Job adverts may not discourage applicants because of age."],
            ),
            (
                "Adverts must not put off older applicants.",
                ["Pick the chart type that matches the comparison you want to show."],
            ),
        ]
    )
    assert support > unrelated
