"""The labelled requests: validity, counts, coverage, no overlap, and prompt hygiene."""

import re

import pytest

from core.llm import load_prompt
from core.llm.prompt_lock import check_lock
from core.llm.prompts import PROMPTS_DIR
from core.spec import DOMAIN_AREAS
from evaluation.analyzer import data
from evaluation.analyzer.__main__ import main


def test_labelled_data_has_no_issues() -> None:
    assert [str(i) for i in data.check_data()] == []


def test_counts() -> None:
    assert len(data.load_set("gate")) == 100
    assert len(data.seed_requests()) == 30
    assert len(data.load_set("dev")) == 50
    assert len(data.load_set("arabic")) == 10
    assert len(data.load_set("holdout")) == 24


def test_holdout_is_reported_only() -> None:
    def norm(text: str) -> str:
        return " ".join(text.lower().split())

    holdout = data.load_set("holdout")
    assert {i.source for i in holdout} == {"holdout"}
    assert all(i.id.startswith("h-") for i in holdout)
    gate = {norm(i.text) for i in data.load_set("gate")}
    assert not gate & {norm(i.text) for i in holdout}  # never part of the gate
    header = data.FILES["holdout"].read_text(encoding="utf-8").split("\nname:")[0]
    assert "NOT part of the 90% gate" in header and "NEVER use it for prompt work" in header


def test_gate_coverage_minimums() -> None:
    c = data.gate_coverage()
    assert min(c.styles[s] for s in ("clear", "vague", "detailed")) >= 25
    assert c.kinds["role"] >= 25 and c.kinds["task"] >= 25 and c.kinds["workflow"] >= 15
    assert c.risks["medium"] >= 10 and c.risks["high"] >= 15
    assert set(c.areas) == set(DOMAIN_AREAS)  # every domain area appears in the gate set
    assert c.with_targets >= 10


def test_every_domain_area_missing_from_the_seed_set_has_five() -> None:
    c = data.gate_coverage()
    for area in set(DOMAIN_AREAS) - data.SEED_COVERED_AREAS:
        assert c.areas[area] >= 5, area


def test_seed_targets_are_not_scored() -> None:
    assert all(i.mentioned_targets is None for i in data.seed_requests())
    assert all(i.mentioned_targets is not None for i in data.file_items("test"))


def test_sources_record_versions_and_hashes() -> None:
    names = [s.name for s in data.sources()]
    assert names == [
        "skillforge-seed-benchmark",
        "analyzer-requests-test",
        "analyzer-requests-dev",
        "analyzer-requests-arabic",
        "analyzer-requests-holdout",
    ]
    assert all(len(s.sha256) == 64 for s in data.sources())


def test_few_shot_examples_come_from_the_dev_set_only() -> None:
    system = load_prompt("analysis/request").render(
        {"request_text": "x", "answers": [], "kinds": [], "domain_areas": [], "high_risk_areas": []}
    )[0]["content"]
    shots = re.findall(r'Request: "(.*?)"\n\{', system, flags=re.DOTALL)
    assert len(shots) == 3

    def norm(text: str) -> str:
        return " ".join(text.lower().split())

    dev = {norm(i.text) for i in data.load_set("dev")}
    measured = {
        norm(i.text)
        for i in data.load_set("gate") + data.load_set("arabic") + data.load_set("holdout")
    }
    for shot in shots:
        assert norm(shot) in dev, shot[:40]
        assert norm(shot) not in measured


def test_prompt_v3_states_the_labelling_rules() -> None:
    """v3 adds the LABELLING.md rules on kind (one job, vague, tutor) and fitness, as text only:
    no example in it may come from a labelled set."""
    prompt = load_prompt("analysis/request")
    assert prompt.version == 3
    system = " ".join(
        prompt.render(
            {
                "request_text": "x",
                "answers": [],
                "kinds": [],
                "domain_areas": [],
                "high_risk_areas": [],
            }
        )[0]["content"].split()
    )
    for rule in (
        "A request for someone who does one job only is a task.",
        'This holds even when the request uses a job title or "act as": if the person does one '
        "job only, it is a task.",
        "A vague request (it does not say what the skill should do or produce) is a role.",
        "A request to learn a subject is a tutor: a role in the education area, with the subject "
        'as the sub-area (e.g. "education/chemistry").',
        "Fitness and nutrition for healthy people (calories, protein, workouts) is general; it is "
        "medical only when the request names a condition, a medication or a treatment.",
    ):
        assert rule in system, rule[:50]
    labelled = " ".join(
        i.text.lower() for name in ("gate", "dev", "arabic", "holdout") for i in data.load_set(name)
    )
    assert "chemistry" not in labelled  # the tutor example is not taken from any set


def test_prompt_lock_includes_the_analyzer_prompt() -> None:
    assert check_lock(PROMPTS_DIR) == []
    assert load_prompt("analysis/request").meta.model_role == "analysis"


@pytest.mark.parametrize("command", [["check-data"]])
def test_cli_check_data(command: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(command) == 0
    assert "gate: 100 requests" in capsys.readouterr().out
