"""The prompt version lock (AI-03): every prompt content change needs a `version` bump.

`prompts/prompts.lock.json` records the version and sha256 of each prompt file. CI runs the
check (tests/llm/test_prompts.py); it fails when a prompt changed without a bump, or when the
lock is out of date.

    python -m core.llm.prompt_lock            # check
    python -m core.llm.prompt_lock --update   # rewrite the lock after bumping versions
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.llm.errors import PromptFormatError, PromptLockError
from core.llm.prompts import PROMPTS_DIR, parse_prompt

LOCK_NAME = "prompts.lock.json"


LockEntry = dict[str, int | str]
ProblemKind = Literal["new", "removed", "not_bumped", "version_lowered", "bumped"]
BLOCKING: frozenset[ProblemKind] = frozenset({"not_bumped", "version_lowered"})


@dataclass(frozen=True)
class LockProblem:
    prompt_id: str
    kind: ProblemKind
    message: str


def discover(root: Path) -> dict[str, Path]:
    """All prompt files under root, keyed by prompt_id. README.md files are skipped."""
    return {
        path.relative_to(root).with_suffix("").as_posix(): path
        for path in sorted(root.rglob("*.md"))
        if path.name.lower() != "readme.md"
    }


def build_lock(root: Path) -> dict[str, LockEntry]:
    lock: dict[str, LockEntry] = {}
    for prompt_id, path in discover(root).items():
        prompt = parse_prompt(path.read_text(encoding="utf-8"), prompt_id)
        lock[prompt_id] = {"version": prompt.version, "sha256": prompt.sha256}
    return lock


def read_lock(lock_path: Path) -> dict[str, LockEntry]:
    if not lock_path.exists():
        return {}
    data: dict[str, LockEntry] = json.loads(lock_path.read_text(encoding="utf-8"))
    return data


def check_lock(root: Path, lock_path: Path | None = None) -> list[LockProblem]:
    """Compare prompt files with the lock. An empty list means the lock is current."""
    locked = read_lock(lock_path or root / LOCK_NAME)
    current = build_lock(root)
    fix = "run `python -m core.llm.prompt_lock --update`"
    problems = []
    for prompt_id, entry in current.items():
        old = locked.get(prompt_id)
        if old is None:
            problems.append(LockProblem(prompt_id, "new", f"{prompt_id}: new prompt; {fix}"))
        elif entry["sha256"] == old["sha256"]:
            continue
        elif entry["version"] == old["version"]:
            problems.append(
                LockProblem(
                    prompt_id,
                    "not_bumped",
                    f"{prompt_id}: content changed but version is still {old['version']}; "
                    "bump `version` in the frontmatter",
                )
            )
        elif int(entry["version"]) < int(old["version"]):
            problems.append(
                LockProblem(
                    prompt_id,
                    "version_lowered",
                    f"{prompt_id}: version went down from {old['version']} to {entry['version']}",
                )
            )
        else:
            problems.append(LockProblem(prompt_id, "bumped", f"{prompt_id}: version bumped; {fix}"))
    for prompt_id in sorted(set(locked) - set(current)):
        problems.append(LockProblem(prompt_id, "removed", f"{prompt_id}: file removed; {fix}"))
    return problems


def update_lock(root: Path, lock_path: Path | None = None) -> dict[str, LockEntry]:
    """Rewrite the lock. Refuses while any prompt changed without a version bump."""
    lock_path = lock_path or root / LOCK_NAME
    blocking = [p.message for p in check_lock(root, lock_path) if p.kind in BLOCKING]
    if blocking:
        raise PromptLockError("cannot update the prompt lock:\n" + "\n".join(blocking))
    lock = build_lock(root)
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.llm.prompt_lock")
    parser.add_argument("--root", type=Path, default=PROMPTS_DIR)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="check the lock (default)")
    action.add_argument("--update", action="store_true", help="rewrite prompts.lock.json")
    args = parser.parse_args(argv)
    try:
        if args.update:
            lock = update_lock(args.root)
            print(f"prompt lock updated: {len(lock)} prompts")
            return 0
        problems = check_lock(args.root)
    except (PromptFormatError, PromptLockError) as exc:
        print(exc, file=sys.stderr)
        return 1
    for problem in problems:
        print(problem.message, file=sys.stderr)
    if not problems:
        print("prompt lock is current")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
