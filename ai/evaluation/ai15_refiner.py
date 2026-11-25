"""Refine compiled package wording, then enforce the AI-15 package invariants."""

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel

from core.llm import complete
from evaluation.ai15_package_check import compare_packages
from evaluation.common import live_guard

PROMPT_ID = "evaluation/ai15_refine"


class RefinedMarkdown(BaseModel):
    content: str


async def _refine_markdown(
    path: str, platform: str, content: str, check_errors: tuple[str, ...] = ()
) -> str:
    result = await complete(
        PROMPT_ID,
        {
            "artifact_path": path,
            "platform": platform,
            "artifact_markdown": content,
            "check_errors": "\n".join(f"- {error}" for error in check_errors) or "None",
        },
        RefinedMarkdown,
    )
    if not result.content.strip():
        raise ValueError(f"{path}: refiner returned an empty Markdown artifact")
    return result.content


def _file_errors(relative: Path, errors: list[str]) -> tuple[str, ...]:
    prefix = f"{relative.as_posix()}:"
    return tuple(error for error in errors if error.startswith(prefix))


async def _refine_package(before_root: Path, after_root: Path, platform: str) -> int:
    baseline_errors = compare_packages(before_root, before_root, platform)
    if baseline_errors:
        print("\n".join(f"FAIL: {error}" for error in baseline_errors), file=sys.stderr)
        return 1

    markdown_files = sorted(
        path.relative_to(before_root)
        for path in before_root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".md"
    )
    after_root.parent.mkdir(parents=True, exist_ok=True)
    report_path = after_root.with_name(f"{after_root.name}.ai15-refiner.json")
    if report_path.exists():
        print(f"refiner report already exists: {report_path}", file=sys.stderr)
        return 2
    fallback_files: set[str] = set()
    with tempfile.TemporaryDirectory(dir=after_root.parent) as temp_dir:
        staging = Path(temp_dir) / "package"
        shutil.copytree(before_root, staging)
        original_bytes: dict[Path, bytes] = {}
        for relative in markdown_files:
            source_path = before_root / relative
            original_bytes[relative] = source_path.read_bytes()
            source = original_bytes[relative].decode("utf-8")
            refined = await _refine_markdown(relative.as_posix(), platform, source)
            (staging / relative).write_text(refined, encoding="utf-8", newline="\n")

        errors = compare_packages(before_root, staging, platform)
        for relative in markdown_files:
            file_errors = _file_errors(relative, errors)
            if not file_errors:
                continue
            repaired = await _refine_markdown(
                relative.as_posix(),
                platform,
                (staging / relative).read_text(encoding="utf-8"),
                file_errors,
            )
            (staging / relative).write_text(repaired, encoding="utf-8", newline="\n")
            repair_errors = _file_errors(relative, compare_packages(before_root, staging, platform))
            if repair_errors:
                (staging / relative).write_bytes(original_bytes[relative])
                fallback_files.add(relative.as_posix())

        errors = compare_packages(before_root, staging, platform)
        if errors:
            fallback_files.update(path.as_posix() for path in markdown_files)
            for relative in markdown_files:
                (staging / relative).write_bytes(original_bytes[relative])
            errors = compare_packages(before_root, staging, platform)
        if errors:
            print("\n".join(f"FAIL: {error}" for error in errors), file=sys.stderr)
            return 1

        staging.rename(after_root)

    report = {
        "status": "passed",
        "refined_files": [path.as_posix() for path in markdown_files],
        "fallback_files": sorted(fallback_files),
    }
    with report_path.open("x", encoding="utf-8", newline="\n") as file:
        file.write(json.dumps(report, indent=2) + "\n")
    print(f"PASS: refined {len(markdown_files)} Markdown files; package invariants hold.")
    if fallback_files:
        print(f"FALLBACK: original files restored: {', '.join(sorted(fallback_files))}")
    print(f"Refiner report written to {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True, help="Compiled input package")
    parser.add_argument("--after", type=Path, required=True, help="New refined package directory")
    parser.add_argument("--platform", choices=("claude", "codex"), required=True)
    parser.add_argument("--live", action="store_true", help="Allow real, paid model calls")
    args = parser.parse_args(argv)

    before_root = args.before.resolve()
    after_root = args.after.resolve()
    if not before_root.is_dir():
        parser.error(f"compiled input package is not a directory: {before_root}")
    if not any(path.is_file() and path.suffix.lower() == ".md" for path in before_root.rglob("*")):
        parser.error(f"compiled input package has no Markdown artifacts: {before_root}")
    if after_root.exists():
        parser.error(f"refined package output already exists: {after_root}")
    report_path = after_root.with_name(f"{after_root.name}.ai15-refiner.json")
    if report_path.exists():
        parser.error(f"refiner report already exists: {report_path}")
    if after_root == before_root or before_root in after_root.parents:
        parser.error("refined package output must be outside the input package")

    if (refused := live_guard(args.live, PROMPT_ID)) is not None:
        return refused
    return asyncio.run(_refine_package(before_root, after_root, args.platform))


if __name__ == "__main__":
    raise SystemExit(main())
