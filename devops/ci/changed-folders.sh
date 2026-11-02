#!/usr/bin/env bash
# Which department folders changed (OPS-02). Prints "ai=true" style lines for $GITHUB_OUTPUT.
# A change to the CI itself (.github/workflows/, devops/ci/) counts as every folder changed.
#
# Usage: changed-folders.sh <base-sha> <head-sha>
#   An empty or all-zero base (manual run, new branch) means every folder changed.
set -euo pipefail

FOLDERS=(ai backend frontend data)
base="${1:-}"
head="${2:-HEAD}"

all=false
changed=""
if [ -z "$base" ] || [ "$base" = "0000000000000000000000000000000000000000" ]; then
  all=true
else
  changed="$(git diff --name-only "$base...$head")"
  if grep -qE '^(\.github/workflows/|devops/ci/)' <<<"$changed"; then
    all=true
  fi
fi

for folder in "${FOLDERS[@]}"; do
  if [ "$all" = true ] || grep -q "^$folder/" <<<"$changed"; then
    echo "$folder=true"
  else
    echo "$folder=false"
  fi
done
