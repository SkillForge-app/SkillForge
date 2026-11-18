"""AnalyzedRequest (contract A3) command line.

python -m core.analysis export-schema           # rewrite analyzed_request.schema.json
python -m core.analysis export-schema --check   # exit 1 if it is out of date
"""

import argparse
import sys

from core.analysis.types import SCHEMA_PATH, render_schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.analysis")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-schema", help="write or check the A3 JSON Schema")
    export.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    expected = render_schema()
    current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
    if args.check:
        if current != expected:
            print(f"{SCHEMA_PATH} is out of date: run `python -m core.analysis export-schema`")
            return 1
        print("analyzed_request.schema.json is current")
        return 0
    SCHEMA_PATH.write_text(expected, encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
