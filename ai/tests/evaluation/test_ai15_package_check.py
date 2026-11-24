import shutil
import sys
from pathlib import Path

import pytest

from evaluation.ai15_package_check import check_package_trees, compare_packages, main


def _package(
    root: Path, *, description: str = "A description.", body: str = "Original prose."
) -> Path:
    root.mkdir(parents=True)
    (root / "agent.md").write_text(
        f'---\nname: test-agent\ndescription: "{description}"\ntools: Read\n---\n'
        f"# Agent\n\n{body}\n\n```sh\necho unchanged\n```\n\n"
        "## Procedure\n\n- Use `references/guide.md`.\n",
        encoding="utf-8",
    )
    (root / "settings.json").write_text('{"permissions": {"allow": []}}\n', encoding="utf-8")
    return root


def test_allows_prose_and_description_edits(tmp_path: Path) -> None:
    before = _package(tmp_path / "before")
    after = _package(
        tmp_path / "after",
        description="A clearer description.",
        body="Improved ordinary prose.",
    )

    assert compare_packages(before, after, "claude") == []


def test_rejects_file_set_change(tmp_path: Path) -> None:
    before = _package(tmp_path / "before")
    after = _package(tmp_path / "after")
    (after / "extra.md").write_text("# Extra\n", encoding="utf-8")

    assert any("file set changed" in error for error in compare_packages(before, after, "claude"))


def test_rejects_heading_code_path_and_configuration_changes(tmp_path: Path) -> None:
    before = _package(tmp_path / "before")
    after = _package(tmp_path / "after", body="Improved prose.")
    (after / "agent.md").write_text(
        '---\nname: test-agent\ndescription: "A description."\ntools: Read\n---\n'
        "# Renamed\n\nImproved prose.\n\n```sh\necho changed\n```\n\n"
        "## Procedure\n\n- Use `after/references/guide.md`.\n",
        encoding="utf-8",
    )
    (after / "settings.json").write_text('{"permissions": {"allow": ["Bash"]}}\n', encoding="utf-8")

    errors = compare_packages(before, after, "claude")
    assert any("headings" in error for error in errors)
    assert any("fenced code blocks" in error for error in errors)
    assert any("inline code" in error for error in errors)
    assert any("non-Markdown artifact changed" in error for error in errors)


def test_rejects_frontmatter_key_and_xml_changes(tmp_path: Path) -> None:
    before = _package(tmp_path / "before")
    after = _package(tmp_path / "after", description="Use <tag>.")
    (after / "agent.md").write_text(
        '---\nname: test-agent\ndescription: "Use <tag>."\ntools: Read\nnew_key: value\n---\n'
        "# Agent\n\nUpdated prose.\n\n## Procedure\n\n- Use `after/references/guide.md`.\n",
        encoding="utf-8",
    )

    errors = compare_packages(before, after, "claude")
    assert any("frontmatter keys changed" in error for error in errors)
    assert any("XML-like tag" in error for error in errors)


def test_allows_autolinks_and_generic_types_in_markdown(tmp_path: Path) -> None:
    before = _package(
        tmp_path / "before",
        body="See <https://example.com/> and `List<String>`.",
    )
    after = _package(
        tmp_path / "after",
        body="See <https://docs.example.com/> and `List<String>`.",
    )

    assert compare_packages(before, after, "claude") == []


def test_rejects_xml_tags_in_visible_prose(tmp_path: Path) -> None:
    before = _package(tmp_path / "before")
    after = _package(tmp_path / "after", body="Keep <unsafe> content out.")

    errors = compare_packages(before, after, "claude")

    assert any("package contains an XML-like tag" in error for error in errors)


def test_rejects_path_literal_changes_without_flagging_and_or(tmp_path: Path) -> None:
    before = _package(tmp_path / "before", body="Use and/or read references/guide.md.")
    after = _package(tmp_path / "after", body="Use and/or read references/updated.md.")

    errors = compare_packages(before, after, "claude")

    assert any("path literals changed" in error for error in errors)


def test_rejects_link_target_changes(tmp_path: Path) -> None:
    before = _package(tmp_path / "before", body="Read [the guide](https://example.com/guide).")
    after = _package(tmp_path / "after", body="Read [the guide](https://other.example/guide).")

    assert any(
        "link targets changed" in error for error in compare_packages(before, after, "claude")
    )


def test_rejects_list_structure_changes(tmp_path: Path) -> None:
    before = _package(tmp_path / "before", body="- First item\n- Second item")
    after = _package(tmp_path / "after", body="- First item\n* Second item")

    assert any(
        "list structure changed" in error for error in compare_packages(before, after, "claude")
    )


def test_rejects_frontmatter_presence_change(tmp_path: Path) -> None:
    before = _package(tmp_path / "before")
    after = _package(tmp_path / "after")
    (after / "agent.md").write_text("# Agent\n\nUpdated prose.\n", encoding="utf-8")

    assert any(
        "frontmatter presence changed" in error
        for error in compare_packages(before, after, "claude")
    )


def test_reports_relative_file_path_once(tmp_path: Path) -> None:
    before = _package(tmp_path / "before" / "nested")
    after = _package(tmp_path / "after" / "nested")
    (after / "agent.md").write_text(
        '---\nname: changed-agent\ndescription: "A description."\ntools: Read\n---\n'
        "# Agent\n\nOriginal prose.\n\n```sh\necho unchanged\n```\n\n"
        "## Procedure\n\n- Use `references/guide.md`.\n",
        encoding="utf-8",
    )

    errors = compare_packages(before.parent, after.parent, "claude")

    assert errors == ["nested/agent.md: frontmatter field 'name' changed"]


def test_rejects_overlong_description(tmp_path: Path) -> None:
    before = _package(tmp_path / "before")
    after = _package(tmp_path / "after", description="x" * 1025)

    assert any(
        "description is 1025 characters" in error
        for error in compare_packages(before, after, "claude")
    )


def test_check_package_trees_and_cli_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    for platform in ("claude", "codex"):
        _package(before / platform / "skill")
        _package(after / platform / "skill", body="Improved ordinary prose.")

    assert check_package_trees(before, after) == []
    monkeypatch.setattr(
        sys,
        "argv",
        ["ai15-package-check", "--before", str(before), "--after", str(after)],
    )

    assert main() == 0
    assert "PASS: package invariants hold for 4 compiled files." in capsys.readouterr().out

    shutil.rmtree(after / "codex")
    errors = check_package_trees(before, after)
    assert errors == ["missing codex package directory"]
