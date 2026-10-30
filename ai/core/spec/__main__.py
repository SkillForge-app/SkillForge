"""SkillSpec command line.

python -m core.spec export-schema           # rewrite core/spec/schema.json
python -m core.spec export-schema --check   # exit 1 if schema.json is out of date
python -m core.spec validate FILE [FILE ...]
"""

import argparse
import sys
from pathlib import Path

import yaml

from core.spec.models import SCHEMA_PATH, render_schema
from core.spec.validator import Issue, validate_spec


def export_schema(check: bool) -> int:
    expected = render_schema()
    current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
    if check:
        if current != expected:
            print(f"{SCHEMA_PATH} is out of date: run `python -m core.spec export-schema`")
            return 1
        print("schema.json is current")
        return 0
    SCHEMA_PATH.write_text(expected, encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
    return 0


def validate_files(paths: list[Path]) -> int:
    failed = False
    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            issues: tuple[Issue, ...] = (Issue("", "unreadable", str(exc)),)
        else:
            if isinstance(data, dict):
                issues = validate_spec(data).issues
            else:
                issues = (Issue("", "not_a_mapping", "expected a mapping"),)
        errors = [i for i in issues if i.severity == "error"]
        failed |= bool(errors)
        print(f"{'FAIL' if errors else 'OK'}  {path}")
        for issue in issues:
            print(f"  {issue.severity:<7} {issue}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.spec")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-schema", help="write or check core/spec/schema.json")
    export.add_argument("--check", action="store_true")
    validate = commands.add_parser("validate", help="validate SkillSpec YAML or JSON files")
    validate.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    if args.command == "export-schema":
        return export_schema(args.check)
    return validate_files(args.files)


if __name__ == "__main__":
    sys.exit(main())
