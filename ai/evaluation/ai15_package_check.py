"""Post-compilation package checks for the AI-15 wording-only refinement."""

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from core.spec import PLATFORM_LIMITS, contains_xml_tag

_FENCED_BLOCK = re.compile(
    r"(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[ \t]*$"
)
_HEADING = re.compile(r"(?m)^ {0,3}#{1,6}[ \t]+.*$")
_INLINE_CODE = re.compile(r"(?<!`)`+[^`\n]+`+(?!`)")
_LIST_MARKER = re.compile(r"(?m)^([ \t]*(?:[-*+]|\d+[.)])[ \t]+)")
_LINK_TARGET = re.compile(r"\]\(([^)]+)\)")
_PATH = re.compile(
    r"(?<![A-Za-z0-9:/])(?:\.{1,2}/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+(?![A-Za-z0-9])"
)


def _frontmatter(text: str, path: Path) -> tuple[dict[str, Any] | None, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            raw = "".join(lines[1:end])
            data = yaml.safe_load(raw)
            if not isinstance(data, dict):
                raise ValueError(f"{path}: frontmatter must be a mapping")
            return data, "".join(lines[end + 1 :])
    raise ValueError(f"{path}: unterminated frontmatter")


def _fenced_blocks(text: str) -> list[str]:
    return [match.group(0) for match in _FENCED_BLOCK.finditer(text)]


def _markdown_errors(before: Path, after: Path, platform: str) -> list[str]:
    errors: list[str] = []
    try:
        before_text = before.read_text(encoding="utf-8")
        after_text = after.read_text(encoding="utf-8")
        before_meta, before_body = _frontmatter(before_text, before)
        after_meta, after_body = _frontmatter(after_text, after)
    except (UnicodeDecodeError, yaml.YAMLError, ValueError) as exc:
        return [str(exc)]

    relative = after.name
    if (before_meta is None) != (after_meta is None):
        errors.append(f"{relative}: frontmatter presence changed")
    elif before_meta is not None and after_meta is not None:
        if before_meta.keys() != after_meta.keys():
            errors.append(f"{relative}: frontmatter keys changed")
        for key in before_meta.keys() & after_meta.keys():
            if key != "description" and before_meta[key] != after_meta[key]:
                errors.append(f"{relative}: frontmatter field {key!r} changed")

    if before_meta is not None and after_meta is not None:
        limit = PLATFORM_LIMITS[platform].description
        description = after_meta.get("description")
        if isinstance(description, str):
            if len(description) > limit:
                errors.append(
                    f"{relative}: description is {len(description)} characters; "
                    f"{platform} limit is {limit}"
                )
            if contains_xml_tag(description):
                errors.append(f"{relative}: description contains an XML-like tag")

    if _HEADING.findall(before_body) != _HEADING.findall(after_body):
        errors.append(f"{relative}: headings or heading order changed")
    if _fenced_blocks(before_body) != _fenced_blocks(after_body):
        errors.append(f"{relative}: fenced code blocks changed")
    if _INLINE_CODE.findall(before_text) != _INLINE_CODE.findall(after_text):
        errors.append(f"{relative}: inline code, paths, or commands changed")
    if _PATH.findall(before_text) != _PATH.findall(after_text):
        errors.append(f"{relative}: path literals changed")
    if _LINK_TARGET.findall(before_text) != _LINK_TARGET.findall(after_text):
        errors.append(f"{relative}: link targets changed")
    if _LIST_MARKER.findall(before_body) != _LIST_MARKER.findall(after_body):
        errors.append(f"{relative}: list structure changed")
    if contains_xml_tag(after_text):
        errors.append(f"{relative}: package contains an XML-like tag")
    return errors


def compare_packages(before_root: Path, after_root: Path, platform: str) -> list[str]:
    """Compare two compiled packages, allowing prose and description edits only."""
    if platform not in PLATFORM_LIMITS:
        return [f"unsupported platform {platform!r}"]
    if not before_root.is_dir() or not after_root.is_dir():
        return ["both package paths must be directories"]

    before_files = {
        path.relative_to(before_root).as_posix(): path
        for path in before_root.rglob("*")
        if path.is_file()
    }
    after_files = {
        path.relative_to(after_root).as_posix(): path
        for path in after_root.rglob("*")
        if path.is_file()
    }
    errors = [
        f"package file set changed (missing: {sorted(before_files.keys() - after_files.keys())}; "
        f"added: {sorted(after_files.keys() - before_files.keys())})"
    ] if before_files.keys() != after_files.keys() else []

    for relative in sorted(before_files.keys() & after_files.keys()):
        before = before_files[relative]
        after = after_files[relative]
        if after.suffix.lower() == ".md":
            errors.extend(
                f"{relative}: {error}"
                for error in _markdown_errors(before, after, platform)
            )
        elif before.read_bytes() != after.read_bytes():
            errors.append(f"{relative}: non-Markdown artifact changed")
    return errors


def check_package_trees(before_root: Path, after_root: Path) -> list[str]:
    """Compare Claude and Codex output trees rooted at platform/skill/."""
    errors: list[str] = []
    for platform in ("claude", "codex"):
        before = before_root / platform
        after = after_root / platform
        if not before.is_dir() or not after.is_dir():
            errors.append(f"missing {platform} package directory")
            continue
        errors.extend(
            f"{platform}: {error}"
            for error in compare_packages(before, after, platform)
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True, help="Pre-refinement package tree")
    parser.add_argument("--after", type=Path, required=True, help="Post-refinement package tree")
    args = parser.parse_args()

    errors = check_package_trees(args.before, args.after)
    if errors:
        print("\n".join(f"FAIL: {error}" for error in errors), file=sys.stderr)
        return 1

    file_count = sum(
        1
        for platform in ("claude", "codex")
        for path in (args.after / platform).rglob("*")
        if path.is_file()
    )
    print(f"PASS: package invariants hold for {file_count} compiled files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
