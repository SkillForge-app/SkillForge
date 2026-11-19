"""AI-06 child_safety items: SimpleSafetyTests rows used verbatim, by reference only, resolved
from the local download at evaluation time. Placeholder rows only; no real dataset text."""

import json
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from core.llm import FakeGateway, load_config
from evaluation.safety import data
from evaluation.safety.__main__ import main
from evaluation.safety.data import SafetyItem, VerbatimTextMissing
from evaluation.safety.generate import GENERATOR_PROMPTS
from evaluation.safety.precheck import guard_config
from evaluation.safety.verbatim import fill_verbatim
from tests.analysis.safety_files import install_empty_copies

SECRET = "PLACEHOLDER-ROW-TEXT"  # stands in for dataset text: must never be printed or logged


@pytest.fixture(autouse=True)
def _empty_copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    install_empty_copies(tmp_path, monkeypatch)
    load_config.cache_clear()
    yield
    load_config.cache_clear()


@pytest.fixture
def datasets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tiny SimpleSafetyTests download: 7 rows with harmful intent, 2 help-seeking, 1 other."""
    folder = tmp_path / "datasets"
    (folder / "simplesafetytests").mkdir(parents=True)
    rows = ["id,harm_area,counter,category,prompt"]
    for n in range(1, 10):
        kind = "help" if n in (2, 5) else "harm"
        rows.append(f"sst_{n:03d},Child Abuse,{n},x,{SECRET} {kind} {n}")
    rows.append(f"sst_100,Scams and Fraud,1,x,{SECRET} fraud")
    (folder / "simplesafetytests" / "sst_test_cases.csv").write_text(
        "\n".join(rows) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv(data.DATASETS_ENV, str(folder))
    return folder


class Guard(FakeGateway):
    """Llama Guard, faked: a help-seeking row is safe, a harmful one unsafe (S4)."""

    def __init__(self) -> None:
        super().__init__(prompts_root=GENERATOR_PROMPTS, config=guard_config())

    async def complete_text(self, prompt_id: str, inputs: Any, **kw: Any) -> str:
        reply = "safe" if " help " in inputs["conversation"] else "unsafe\nS4"
        self.register_text(prompt_id, reply)
        return await super().complete_text(prompt_id, inputs, **kw)


def verbatim_item(**fields: object) -> dict[str, object]:
    item: dict[str, object] = {
        "id": "r-31",
        "expected": "block",
        "category": "child_safety",
        "attack": "direct",
        "origin": "dataset-verbatim",
        "dataset": "simplesafetytests",
        "dataset_ref": "sst_001",
    }
    return {k: v for k, v in {**item, **fields}.items() if v is not None}


def write_items(items: list[dict[str, object]]) -> None:
    path = data.FILES["redteam"]
    text = path.read_text(encoding="utf-8").replace(
        "requests: []", "requests:\n" + textwrap.indent(yaml.safe_dump(items), "  ")
    )
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- the data model


def test_a_verbatim_item_has_a_reference_and_no_text() -> None:
    SafetyItem.model_validate(verbatim_item())
    with pytest.raises(ValidationError, match="by reference: no text"):
        SafetyItem.model_validate(verbatim_item(text="anything"))
    with pytest.raises(ValidationError, match="needs dataset and dataset_ref"):
        SafetyItem.model_validate(verbatim_item(dataset_ref=None))
    with pytest.raises(ValidationError, match="text is required"):
        SafetyItem.model_validate(verbatim_item(origin="adapted"))


def test_check_data_accepts_verbatim_child_safety_without_a_reviewer() -> None:
    write_items([verbatim_item()])
    issues = data.check_data()
    assert [str(i) for i in issues if i.severity == "error"] == []
    assert not [i for i in issues if i.code == "provenance"]


@pytest.mark.parametrize(
    ("item", "code"),
    [
        (
            {"id": "r-31", "text": "placeholder child request", "expected": "block",
             "category": "child_safety", "attack": "direct", "origin": "adapted",
             "dataset": "simplesafetytests", "dataset_ref": "sst_001", "reviewer": "ziad",
             "reviewed_on": "2026-11-17"},
            "child_safety",
        ),
        (verbatim_item(category="fraud_scams"), "verbatim"),
        (verbatim_item(dataset="harmbench"), "verbatim"),
    ],
)  # fmt: skip
def test_check_data_rules_for_verbatim(item: dict[str, object], code: str) -> None:
    write_items([item])
    assert code in {i.code for i in data.check_data() if i.severity == "error"}


# ---------------------------------------------------------------- resolving the text


def test_the_text_is_read_from_the_local_dataset_only_at_evaluation_time(datasets: Path) -> None:
    write_items([verbatim_item(dataset_ref="sst_003")])
    [checked] = data._items("redteam")  # what check-data uses: no text needed or read
    assert checked.verbatim and checked.text == ""
    [evaluated] = data.load_set("redteam")
    assert evaluated.text == f"{SECRET} harm 3"


def test_a_missing_dataset_fails_clearly_without_any_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(data.DATASETS_ENV, str(tmp_path / "nothing-here"))
    write_items([verbatim_item(dataset_ref="sst_003")])
    with pytest.raises(VerbatimTextMissing, match="r-31: simplesafetytests row sst_003 not found"):
        data.load_set("redteam")
    assert main(["run", "--set", "redteam"]) == 1  # the fake backend; no model is called
    assert "cannot run: r-31: simplesafetytests row sst_003 not found" in capsys.readouterr().out


# ---------------------------------------------------------------- choosing and storing rows


async def test_verbatim_fills_the_slots_with_harmful_rows_by_reference(
    datasets: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    selection = tmp_path / "selection.jsonl"
    run = await fill_verbatim(Guard(), folder=datasets, selection_path=selection)

    # 9 child-abuse rows; the help-seeking ones (002, 005) are skipped, the rest fill 7 slots
    assert (run.rows, run.unsafe, run.safe) == (9, 7, 2)
    assert run.filled == [
        ("r-31", "sst_001"), ("r-32", "sst_003"), ("r-33", "sst_004"), ("r-34", "sst_006"),
        ("r-35", "sst_007"), ("r-36", "sst_008"), ("sd-16", "sst_009"),
    ]  # fmt: skip
    for split in ("redteam", "dev"):
        text = data.FILES[split].read_text(encoding="utf-8")
        assert SECRET not in text  # stored by reference only
        items = [r for r in data.load_file(split).requests if r.origin == "dataset-verbatim"]
        assert all(r.text is None and r.attack == "direct" for r in items)
    assert "child_safety" not in {i.code for i in data.check_data()}
    assert not any("child_safety" in str(i) for i in data.check_data())  # coverage met

    logged = selection.read_text(encoding="utf-8")
    assert SECRET not in logged and SECRET not in capsys.readouterr().out
    assert [json.loads(line)["verdict"] for line in logged.splitlines()][:3] == [
        "unsafe", "safe", "unsafe",
    ]  # fmt: skip

    again = await fill_verbatim(Guard(), folder=datasets, selection_path=selection)
    assert again.filled == [] and again.unsafe == 0  # every slot is filled


def test_the_cli_refuses_verbatim_without_live(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["verbatim"]) == 2
    out = capsys.readouterr().out
    assert "refusing to call openrouter/meta-llama/llama-guard-4-12b without --live" in out
    assert "7 open slots" in out
