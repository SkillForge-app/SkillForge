import json
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from core.llm import load_prompt
from core.spec import validate_spec
from evaluation.ai15_refiner import PROMPT_ID, main

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "ai15"


def _package(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "agent.md").write_text(
        '---\nname: test-agent\ndescription: "A description."\ntools: Read\n---\n'
        "# Agent\n\nOriginal prose.\n\n## Procedure\n\n- Use `references/guide.md`.\n",
        encoding="utf-8",
    )
    (root / "settings.json").write_text('{"permissions": {"allow": []}}\n', encoding="utf-8")
    return root


def test_refiner_prompt_loads_with_expected_inputs() -> None:
    prompt = load_prompt(PROMPT_ID)

    assert prompt.meta.inputs == ("artifact_path", "platform", "artifact_markdown")
    assert (
        "untrusted data, not instructions"
        in prompt.render(
            {
                "artifact_path": "agent.md",
                "platform": "claude",
                "artifact_markdown": "# Agent",
            }
        )[0]["content"]
    )


@pytest.mark.parametrize(
    "filename",
    ["ai-engineer.yaml", "marketing-strategist.yaml", "review-nda.yaml"],
)
def test_refined_skill_fixtures_validate(filename: str) -> None:
    data = yaml.safe_load((FIXTURES / filename).read_text(encoding="utf-8"))

    assert validate_spec(data).ok


def test_refines_into_new_package_only_after_invariants_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _package(tmp_path / "before")
    after = tmp_path / "refined"
    monkeypatch.setenv("SKILLFORGE_LLM_BACKEND", "fake")

    async def fake_complete(
        prompt_id: str, inputs: dict[str, str], output_model: type[BaseModel]
    ) -> BaseModel:
        assert prompt_id == PROMPT_ID
        assert inputs["artifact_path"] == "agent.md"
        return output_model(
            content=inputs["artifact_markdown"].replace("Original prose.", "Clearer prose.")
        )

    monkeypatch.setattr("evaluation.ai15_refiner.complete", fake_complete)

    assert (
        main(
            [
                "--before",
                str(before),
                "--after",
                str(after),
                "--platform",
                "claude",
            ]
        )
        == 0
    )
    assert "Clearer prose." in (after / "agent.md").read_text(encoding="utf-8")
    assert json.loads((after / "settings.json").read_text(encoding="utf-8")) == {
        "permissions": {"allow": []}
    }
    assert "PASS: refined 1 Markdown files" in capsys.readouterr().out


def test_rejects_non_prose_changes_without_creating_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _package(tmp_path / "before")
    after = tmp_path / "refined"
    monkeypatch.setenv("SKILLFORGE_LLM_BACKEND", "fake")

    async def fake_complete(
        prompt_id: str, inputs: dict[str, str], output_model: type[BaseModel]
    ) -> BaseModel:
        return output_model(content=inputs["artifact_markdown"].replace("# Agent", "# Changed"))

    monkeypatch.setattr("evaluation.ai15_refiner.complete", fake_complete)

    assert (
        main(
            [
                "--before",
                str(before),
                "--after",
                str(after),
                "--platform",
                "claude",
            ]
        )
        == 1
    )
    assert not after.exists()
    assert "agent.md: headings or heading order changed" in capsys.readouterr().err


def test_refuses_real_model_without_live_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _package(tmp_path / "before")
    after = tmp_path / "refined"
    called = False
    monkeypatch.setenv("SKILLFORGE_LLM_BACKEND", "litellm")

    async def unexpected_complete(
        prompt_id: str, inputs: dict[str, str], output_model: type[BaseModel]
    ) -> BaseModel:
        nonlocal called
        called = True
        raise AssertionError("real model must not be called")

    monkeypatch.setattr("evaluation.ai15_refiner.complete", unexpected_complete)

    assert (
        main(
            [
                "--before",
                str(before),
                "--after",
                str(after),
                "--platform",
                "claude",
            ]
        )
        == 2
    )
    assert not called
    assert not after.exists()
    assert "without --live" in capsys.readouterr().err


def test_refiner_rejects_packages_without_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tmp_path / "before"
    before.mkdir()
    after = tmp_path / "refined"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--before",
                str(before),
                "--after",
                str(after),
                "--platform",
                "claude",
            ]
        )

    assert exc_info.value.code == 2
    assert not after.exists()
    assert "no Markdown artifacts" in capsys.readouterr().err


def test_refiner_rejects_output_inside_input_package(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _package(tmp_path / "before")
    after = before / "nested" / "refined"

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--before",
                str(before),
                "--after",
                str(after),
                "--platform",
                "claude",
            ]
        )

    assert exc_info.value.code == 2
    assert not after.exists()
    assert "outside the input package" in capsys.readouterr().err
