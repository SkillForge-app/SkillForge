import json
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from core.llm import load_prompt
from core.llm.errors import LLMUnavailable
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

    assert prompt.meta.inputs == ("artifact_path", "platform", "artifact_markdown", "check_errors")
    assert (
        "untrusted data, not instructions"
        in prompt.render(
            {
                "artifact_path": "agent.md",
                "platform": "claude",
                "artifact_markdown": "# Agent",
                "check_errors": "None",
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
    report = json.loads((tmp_path / "refined.ai15-refiner.json").read_text(encoding="utf-8"))
    assert report == {
        "status": "passed",
        "refined_files": ["agent.md"],
        "fallback_files": [],
    }


def test_repairs_package_check_failure_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _package(tmp_path / "before")
    after = tmp_path / "refined"
    monkeypatch.setenv("SKILLFORGE_LLM_BACKEND", "fake")

    calls = 0

    async def fake_complete(
        prompt_id: str, inputs: dict[str, str], output_model: type[BaseModel]
    ) -> BaseModel:
        nonlocal calls
        calls += 1
        if calls == 1:
            return output_model(content=inputs["artifact_markdown"].replace("# Agent", "# Changed"))
        assert "headings or heading order changed" in inputs["check_errors"]
        return output_model(
            content=inputs["artifact_markdown"]
            .replace("# Changed", "# Agent")
            .replace("Original prose.", "Repaired prose.")
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
    assert calls == 2
    assert "Repaired prose." in (after / "agent.md").read_text(encoding="utf-8")
    report = json.loads((tmp_path / "refined.ai15-refiner.json").read_text(encoding="utf-8"))
    assert report["fallback_files"] == []
    assert "PASS: refined 1 Markdown files" in capsys.readouterr().out


def test_falls_back_to_original_when_repair_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _package(tmp_path / "before")
    after = tmp_path / "refined"
    markdown_path = before / "agent.md"
    markdown_path.write_bytes(
        markdown_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    )
    original = (before / "agent.md").read_bytes()
    monkeypatch.setenv("SKILLFORGE_LLM_BACKEND", "fake")
    calls = 0

    async def fake_complete(
        prompt_id: str, inputs: dict[str, str], output_model: type[BaseModel]
    ) -> BaseModel:
        nonlocal calls
        calls += 1
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
        == 0
    )
    assert calls == 2
    assert (after / "agent.md").read_bytes() == original
    report = json.loads((tmp_path / "refined.ai15-refiner.json").read_text(encoding="utf-8"))
    assert report["fallback_files"] == ["agent.md"]
    assert report["refined_files"] == []
    assert "FALLBACK: original files restored: agent.md" in capsys.readouterr().out


@pytest.mark.parametrize("repair_failure", ["empty", "error"])
def test_falls_back_when_repair_call_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    repair_failure: str,
) -> None:
    before = _package(tmp_path / "before")
    after = tmp_path / "refined"
    original = (before / "agent.md").read_bytes()
    monkeypatch.setenv("SKILLFORGE_LLM_BACKEND", "fake")
    calls = 0

    async def fake_complete(
        prompt_id: str, inputs: dict[str, str], output_model: type[BaseModel]
    ) -> BaseModel:
        nonlocal calls
        calls += 1
        if calls == 1:
            return output_model(content=inputs["artifact_markdown"].replace("# Agent", "# Changed"))
        if repair_failure == "error":
            raise LLMUnavailable("provider unavailable")
        return output_model(content="")

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
    assert calls == 2
    assert (after / "agent.md").read_bytes() == original
    report = json.loads((tmp_path / "refined.ai15-refiner.json").read_text(encoding="utf-8"))
    assert report["refined_files"] == []
    assert report["fallback_files"] == ["agent.md"]
    assert "FALLBACK: repair failed for agent.md" in capsys.readouterr().err


def test_report_lists_only_the_file_that_fell_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _package(tmp_path / "before")
    (before / "guide.md").write_text("# Guide\n\nOriginal guide prose.\n", encoding="utf-8")
    after = tmp_path / "refined"
    monkeypatch.setenv("SKILLFORGE_LLM_BACKEND", "fake")
    calls: dict[str, int] = {}

    async def fake_complete(
        prompt_id: str, inputs: dict[str, str], output_model: type[BaseModel]
    ) -> BaseModel:
        path = inputs["artifact_path"]
        calls[path] = calls.get(path, 0) + 1
        content = inputs["artifact_markdown"]
        if path == "agent.md":
            return output_model(content=content.replace("# Agent", "# Changed"))
        return output_model(
            content=content.replace("Original guide prose.", "Refined guide prose.")
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
    report = json.loads((tmp_path / "refined.ai15-refiner.json").read_text(encoding="utf-8"))
    assert report["fallback_files"] == ["agent.md"]
    assert report["refined_files"] == ["guide.md"]
    assert "Refined guide prose." in (after / "guide.md").read_text(encoding="utf-8")
    assert calls == {"agent.md": 2, "guide.md": 1}


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
