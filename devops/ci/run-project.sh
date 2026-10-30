#!/usr/bin/env bash
# CI skeleton for a department folder (OPS-02): finds the project type, then runs its install,
# lint, type check and tests when they exist. An empty folder passes with a notice.
# Departments replace this with their own steps in .github/workflows/<department>.yml when they need more.
#
# Usage: run-project.sh <folder>
set -euo pipefail

dir="${1:?usage: run-project.sh <folder>}"

if [ -z "$(git ls-files -- "$dir")" ]; then
  echo "::notice::$dir/ has no files yet; nothing to check"
  exit 0
fi
cd "$dir"

# Runs a command inside a collapsible log group.
step() {
  echo "::group::$*"
  "$@"
  echo "::endgroup::"
}

ran=false

if [ -f pyproject.toml ]; then
  ran=true
  if [ -f uv.lock ]; then
    step uv sync --locked --all-extras
  else
    step uv venv
    step uv pip install -e ".[dev]" || step uv pip install -e .
  fi
  bin=.venv/bin
  if [ -x "$bin/ruff" ]; then
    step "$bin/ruff" check .
  fi
  if [ -x "$bin/mypy" ] && grep -q '^\[tool\.mypy\]' pyproject.toml; then
    step "$bin/mypy" .
  fi
  if [ -x "$bin/pytest" ]; then
    set +e
    "$bin/pytest" -q
    code=$?
    set -e
    if [ "$code" = 5 ]; then
      echo "::notice::no tests collected in $dir/"
    elif [ "$code" != 0 ]; then
      exit "$code"
    fi
  fi
fi

if [ -f package.json ]; then
  ran=true
  if [ -f pnpm-lock.yaml ]; then
    corepack enable
    pm=pnpm
    step pnpm install --frozen-lockfile
  elif [ -f yarn.lock ]; then
    corepack enable
    pm=yarn
    step yarn install --immutable
  elif [ -f package-lock.json ]; then
    pm=npm
    step npm ci
  else
    pm=npm
    step npm install
  fi
  for script in lint typecheck test build; do
    if node -e "process.exit(require('./package.json').scripts?.['$script'] ? 0 : 1)"; then
      step "$pm" run "$script"
    fi
  done
fi

if [ "$ran" = false ]; then
  echo "::notice::$dir/ has no pyproject.toml or package.json; nothing to run"
fi
