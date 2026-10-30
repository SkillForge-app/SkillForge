#!/usr/bin/env bash
# One-time copy of the old repository into SkillForge-app/SkillForge (OPS-01, run on 29 Oct 2026).
# Kept for the record. It only works against an empty target repository.
#
# Brings over Master (as main) and the 5 department branches. Personal branches stayed in the old repo.
# Usage (Git Bash): devops/github/mirror.sh <empty-work-dir>
set -euo pipefail

OLD="https://github.com/mmtrabya/AgentForge.git"
NEW="https://github.com/SkillForge-app/SkillForge.git"
WORK="${1:?usage: mirror.sh <empty-work-dir>}"

git clone --bare "$OLD" "$WORK/AgentForge.git"
cd "$WORK/AgentForge.git"

# main first, so GitHub makes it the default branch
git push "$NEW" refs/heads/Master:refs/heads/main
git push "$NEW" \
  refs/heads/AI:refs/heads/AI \
  refs/heads/Backend:refs/heads/Backend \
  refs/heads/Data-Engineering:refs/heads/Data-Engineering \
  refs/heads/DevOps:refs/heads/DevOps \
  refs/heads/Frontend:refs/heads/Frontend

git ls-remote "$NEW"
