"""Startup check for the AI services (AI-21). No network.

python -m core.ops check                    # the environment SKILLFORGE_ENV names (default dev)
python -m core.ops check --env production   # exit 1 when production would refuse to start
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from core.ops.settings import apply_environment, check_environment, env_name

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.ops")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="check the environment before starting")
    check.add_argument("--env", choices=["dev", "staging", "production"])
    args = parser.parse_args(argv)
    # Like the gateway: real variables win; ai/.env fills gaps on a developer machine.
    load_dotenv(ENV_FILE, override=False)
    env = env_name(args.env)
    apply_environment(env)
    problems = check_environment(env)
    for problem in problems:
        print(problem, file=sys.stderr if problem.severity == "error" else sys.stdout)
    errors = sum(p.severity == "error" for p in problems)
    print(f"{env}: {errors} error(s), {len(problems) - errors} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
