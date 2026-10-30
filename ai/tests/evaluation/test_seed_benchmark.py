"""The seed benchmark (AI-04): content rules, coverage, and immutable versioned releases."""

import json
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft202012Validator

from core.spec import HIGH_RISK_AREAS, KINDS, load_spec
from evaluation.benchmarks.__main__ import main
from evaluation.benchmarks.dataset import (
    RECORD_FILES,
    SEED_DIR,
    BenchmarkError,
    load_benchmark,
    render_release,
    verify_release,
    write_release,
)

SEED_SKILL_NAMES = {
    "ai-engineer",
    "marketing-strategist",
    "review-nda",
    "data-analyst",
    "code-reviewer",
    "incident-postmortem",
    "write-press-release",
    "hr-recruiter",
    "explain-medical-results",
    "small-business-budgeting",
}


@pytest.fixture
def seed(tmp_path: Path) -> Path:
    """A writable copy of the seed sources (no releases)."""
    root = tmp_path / "seed"
    shutil.copytree(SEED_DIR / "skills", root / "skills")
    return root


def edit(root: Path, name: str, change: Callable[[dict[str, Any]], object]) -> None:
    path = root / "skills" / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def issue_codes(root: Path) -> list[tuple[str, str]]:
    return [(i.path, i.code) for i in load_benchmark(root)[1]]


def mark_reviewed(root: Path) -> None:
    for path in (root / "skills").glob("*.yaml"):
        edit(root, path.stem, lambda d: d.update(review={"status": "reviewed", "reviewer": "Ziad"}))


# ---------------------------------------------------------------- the real dataset


def test_seed_sources_have_no_issues() -> None:
    skills, issues = load_benchmark()
    assert [str(i) for i in issues] == []
    assert {s.name for s in skills} == SEED_SKILL_NAMES


def test_coverage_and_sizes() -> None:
    skills, _ = load_benchmark()
    assert sum(s.technical for s in skills) == 4
    assert {s.kind for s in skills} == set(KINDS)
    assert {s.area for s in skills} >= HIGH_RISK_AREAS
    assert sum(len(s.test_prompts) for s in skills) == 80
    assert sum(len(s.should_not_trigger) for s in skills) == 60
    assert sum(len(s.requests) for s in skills) == 30
    assert all(5 <= len(s.rubric) <= 8 for s in skills)


def test_the_three_example_specs_are_seed_skills_with_their_prompts() -> None:
    skills = {s.name: s for s in load_benchmark()[0]}
    for name in ("ai-engineer", "marketing-strategist", "review-nda"):
        skill = skills[name]
        assert skill.spec == f"examples/skillspec/{name}.yaml"
        spec = load_spec(Path(__file__).resolve().parents[2] / skill.spec)
        texts = {p.text for p in skill.test_prompts}
        assert set(spec.evaluation.test_prompts) <= texts


# ---------------------------------------------------------------- one test per rule


def test_counts(seed: Path) -> None:
    edit(seed, "data-analyst", lambda d: d["test_prompts"].pop())
    assert issue_codes(seed) == [("skills/data-analyst.yaml#/test_prompts", "count")]


def test_near_misses(seed: Path) -> None:
    def untag(d: dict[str, Any]) -> None:
        for p in d["should_not_trigger"]:
            p["tags"] = ["unrelated"]
            p.pop("closer_skill", None)

    edit(seed, "code-reviewer", untag)
    assert issue_codes(seed) == [
        ("skills/code-reviewer.yaml#/should_not_trigger", "too_few_near_misses")
    ]


def test_request_styles(seed: Path) -> None:
    edit(seed, "hr-recruiter", lambda d: d["requests"][1].update(style="clear"))
    assert issue_codes(seed) == [("skills/hr-recruiter.yaml#/requests", "request_styles")]


def test_duplicate_text_across_skills(seed: Path) -> None:
    copied = "Write a SQL query that shows monthly active customers for the last 12 months from an orders table with customer_id and order_date."  # noqa: E501
    edit(seed, "code-reviewer", lambda d: d["test_prompts"][0].update(text=copied.upper()))
    assert issue_codes(seed) == [
        ("skills/data-analyst.yaml#/test_prompts/1/text", "duplicate_text")
    ]


def test_duplicate_id(seed: Path) -> None:
    edit(seed, "write-press-release", lambda d: d["test_prompts"][1].update(id="tp-1"))
    assert issue_codes(seed) == [
        ("skills/write-press-release.yaml#/test_prompts/1/id", "duplicate_id")
    ]


@pytest.mark.parametrize(
    ("name", "risk", "code"),
    [("review-nda", "medium", "risk_mismatch"), ("data-analyst", "high", "risk_mismatch")],
)
def test_risk_follows_the_domain_area(seed: Path, name: str, risk: str, code: str) -> None:
    def change(d: dict[str, Any]) -> None:
        d["risk"] = risk
        for r in d["requests"]:
            r["labels"]["risk"] = risk

    edit(seed, name, change)
    assert (f"skills/{name}.yaml#/risk", code) in issue_codes(seed)


def test_high_risk_needs_a_critical_guardrail_item(seed: Path) -> None:
    def soften(d: dict[str, Any]) -> None:
        for r in d["rubric"]:
            r["critical"] = False

    edit(seed, "explain-medical-results", soften)
    assert issue_codes(seed) == [
        ("skills/explain-medical-results.yaml#/rubric", "high_risk_needs_critical_guardrail")
    ]


def test_request_labels_must_match_the_skill(seed: Path) -> None:
    edit(seed, "review-nda", lambda d: d["requests"][2]["labels"].update(kind="role"))
    assert issue_codes(seed) == [
        ("skills/review-nda.yaml#/requests/2/labels/kind", "label_mismatch")
    ]


def test_spec_prompts_must_be_in_the_benchmark(seed: Path) -> None:
    edit(seed, "ai-engineer", lambda d: d["test_prompts"][0].update(text="Something else entirely"))
    assert issue_codes(seed) == [("skills/ai-engineer.yaml#/test_prompts", "spec_prompt_missing")]


def test_spec_must_match_the_skill(seed: Path) -> None:
    edit(
        seed, "marketing-strategist", lambda d: d.update(spec="examples/skillspec/review-nda.yaml")
    )
    assert ("skills/marketing-strategist.yaml#/name", "spec_mismatch") in issue_codes(seed)


def test_closer_skill_must_exist(seed: Path) -> None:
    edit(seed, "data-analyst", lambda d: d["should_not_trigger"][0].update(closer_skill="nobody"))
    assert issue_codes(seed) == [
        ("skills/data-analyst.yaml#/should_not_trigger/0/closer_skill", "unknown_closer_skill")
    ]


def test_schema_errors_point_into_the_file(seed: Path) -> None:
    edit(seed, "hr-recruiter", lambda d: d.update(risks="medium"))
    [issue] = load_benchmark(seed)[1]
    assert (issue.path, issue.code) == ("skills/hr-recruiter.yaml#/risks", "schema.unknown_field")
    assert 'did you mean "risk"' in issue.message


def test_name_must_match_the_file(seed: Path) -> None:
    shutil.move(seed / "skills" / "hr-recruiter.yaml", seed / "skills" / "recruiter.yaml")
    assert ("skills/recruiter.yaml#/name", "name_mismatch") in issue_codes(seed)


def test_coverage_rules(seed: Path) -> None:
    (seed / "skills" / "incident-postmortem.yaml").unlink()  # the only workflow, a technical skill
    messages = [i.message for i in load_benchmark(seed)[1] if i.code == "coverage"]
    assert messages == [
        "the seed benchmark needs 10 skills",
        "needs at least 4 technical and 4 non-technical skills",
        "no skill of kind ['workflow']",
    ]


# ---------------------------------------------------------------- releases


def test_release_writes_valid_jsonl_and_manifest(seed: Path) -> None:
    release = write_release(seed, "0.1.0", created=date(2026, 11, 3))
    manifest = release.manifest
    assert manifest["dataset"] == "skillforge-seed-benchmark"
    assert manifest["counts"] == {
        "skills": 10,
        "test_prompts": 80,
        "should_not_trigger": 60,
        "rubric_items": 62,
        "labelled_requests": 30,
    }
    assert manifest["review"] == {"reviewed": 0, "draft": 10}
    for name in RECORD_FILES:
        schema_file = name.replace(".jsonl", ".schema.json")
        schema = json.loads((release.path / "schemas" / schema_file).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        rows = [json.loads(line) for line in (release.path / name).read_text("utf-8").splitlines()]
        assert rows, name
        for row in rows:
            assert list(validator.iter_errors(row)) == [], (
                name,
                row["id" if "id" in row else "name"],
            )
    assert verify_release(release.path) == []


def test_requests_file_is_ready_for_ai05(seed: Path) -> None:
    release = write_release(seed, "0.1.0")
    rows = [
        json.loads(x) for x in (release.path / "requests.jsonl").read_text("utf-8").splitlines()
    ]
    assert len(rows) == 30
    assert {r["style"] for r in rows} == {"clear", "vague", "detailed"}
    assert all(
        {"text", "kind", "domain", "domain_area", "risk", "targets"} <= r.keys() for r in rows
    )


def test_release_is_deterministic(seed: Path) -> None:
    skills, _ = load_benchmark(seed)
    assert render_release(skills, "0.1.0") == render_release(load_benchmark(seed)[0], "0.1.0")


def test_releases_are_immutable(seed: Path) -> None:
    write_release(seed, "0.1.0")
    with pytest.raises(BenchmarkError, match="immutable"):
        write_release(seed, "0.1.0")


def test_release_refuses_bad_versions_and_errors(seed: Path) -> None:
    with pytest.raises(BenchmarkError, match="MAJOR.MINOR.PATCH"):
        write_release(seed, "1.0")
    edit(seed, "data-analyst", lambda d: d["test_prompts"].pop())
    with pytest.raises(BenchmarkError, match="has errors") as info:
        write_release(seed, "0.1.0")
    assert [i.code for i in info.value.issues] == ["count"]


def test_version_1_needs_every_skill_reviewed(seed: Path) -> None:
    with pytest.raises(BenchmarkError, match="still draft"):
        write_release(seed, "1.0.0")
    mark_reviewed(seed)
    assert write_release(seed, "1.0.0").manifest["review"] == {"reviewed": 10, "draft": 0}


def test_verify_detects_changed_missing_and_added_files(seed: Path) -> None:
    path = write_release(seed, "0.1.0").path
    with (path / "prompts.jsonl").open("a", encoding="utf-8") as f:
        f.write("{}\n")
    (path / "rubrics.jsonl").unlink()
    (path / "extra.txt").write_text("x", encoding="utf-8")
    assert sorted((i.path, i.code) for i in verify_release(path)) == [
        ("extra.txt", "unexpected_file"),
        ("prompts.jsonl", "changed_file"),
        ("rubrics.jsonl", "missing_file"),
    ]


def test_committed_releases_are_untouched() -> None:
    releases = sorted((SEED_DIR / "releases").glob("*/manifest.json"))
    for manifest in releases:
        assert verify_release(manifest.parent) == [], manifest.parent.name


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_never_converts_release_line_endings() -> None:
    """Hashes are over exact bytes; core.autocrlf must not touch release files."""
    import subprocess

    release_file = SEED_DIR / "releases" / "0.1.0" / "prompts.jsonl"
    out = subprocess.run(
        ["git", "check-attr", "text", "--", str(release_file)],
        capture_output=True,
        text=True,
        check=True,
        cwd=SEED_DIR,
    ).stdout
    assert out.strip().endswith("text: unset"), out


def test_cli_validate_and_verify(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", "seed"]) == 0
    assert main(["verify", "seed"]) == 0
    out = capsys.readouterr().out
    assert "OK  seed: 10 skills, 80 test prompts, 60 should-not-trigger" in out
