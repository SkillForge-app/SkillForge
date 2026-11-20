from pathlib import Path

from evaluation.ai15_package_check import compare_packages


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


def test_rejects_overlong_description(tmp_path: Path) -> None:
    before = _package(tmp_path / "before")
    after = _package(tmp_path / "after", description="x" * 1025)

    assert any(
        "description is 1025 characters" in error
        for error in compare_packages(before, after, "claude")
    )
