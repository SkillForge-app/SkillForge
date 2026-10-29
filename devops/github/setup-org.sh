#!/usr/bin/env bash
# Applies the OPS-01 GitHub settings to SkillForge-app/SkillForge: org defaults, repo settings,
# teams (sends invites), team access, labels and both rulesets. Safe to re-run.
#
# Needs: gh logged in as an org owner with scopes repo, admin:org, workflow.
# Usage (Git Bash, from the repo root):
#   devops/github/setup-org.sh --dry-run   # print the changes, run only read-only lookups
#   devops/github/setup-org.sh             # apply
set -euo pipefail

ORG="${ORG:-SkillForge-app}"
REPO="${REPO:-SkillForge}"
HERE="$(cd "$(dirname "$0")" && pwd)"

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

# Teams: "slug|description"
TEAMS=(
  "ai|AI department: SkillSpec, LLM gateway, NLP, retrieval, evaluation"
  "backend|Backend department: API, workers, compilers, CLI"
  "data-engineering|Data Engineering department: crawler, pipelines, knowledge store"
  "frontend|Frontend department: website"
  "devops|DevOps department: repo rules, CI/CD, infrastructure"
)

# Members: "team user role". Anyone not listed here is removed from the team.
MEMBERS=(
  "ai zaid2658a-debug maintainer"
  "ai engyousefk04-dot member"
  "backend AbdelrahmanMohamedahmed22 member"
  "backend abdonader061-wq member"
  "data-engineering Mo-mgay1 member"
  "data-engineering mohamed-shahba-dev member"
  "frontend omark243 member"
  "frontend mohammedhamdy33 member"
  "devops zaid2658a-debug maintainer"
  "devops engyousefk04-dot member"
)

# Labels: "name|color|description"
LABELS=(
  "task|c5def5|One task from the department plans (has a task ID)"
  "contract-change|d93f0b|Changes a shared contract; consumers must review"
  "ai|7057ff|AI department"
  "backend|1d76db|Backend department"
  "data-engineering|fbca04|Data Engineering department"
  "frontend|0e8a16|Frontend department"
  "devops|5319e7|DevOps department"
  "P0|ededed|Phase P0: Foundations"
  "P1|ededed|Phase P1: Walking skeleton"
  "P2|ededed|Phase P2: MVP features"
  "P3|ededed|Phase P3: Hardening and beta"
  "P4|ededed|Phase P4: Production launch"
  "P5|ededed|Phase P5: After launch"
)

# Prints a command, then runs it unless --dry-run.
run() {
  printf '+ %s\n' "$*"
  [ "$DRY_RUN" = 1 ] || "$@"
}

echo "== Org defaults"
run gh api -X PATCH "orgs/$ORG" --silent \
  -f default_repository_permission=read \
  -F members_can_create_repositories=false

echo "== Repo settings"
run gh api -X PATCH "repos/$ORG/$REPO" --silent \
  -F allow_merge_commit=true -F allow_squash_merge=true -F allow_rebase_merge=false \
  -F delete_branch_on_merge=false \
  -f merge_commit_title=PR_TITLE -f merge_commit_message=BLANK \
  -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=COMMIT_MESSAGES \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
run gh api -X PUT "repos/$ORG/$REPO/actions/permissions/workflow" --silent \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false

echo "== Teams"
for entry in "${TEAMS[@]}"; do
  team="${entry%%|*}"; desc="${entry#*|}"
  if gh api "orgs/$ORG/teams/$team" --silent 2>/dev/null; then
    echo "   team $team exists"
  else
    run gh api -X POST "orgs/$ORG/teams" --silent -f name="$team" -f privacy=closed -f description="$desc"
  fi
  run gh api -X PUT "orgs/$ORG/teams/$team/repos/$ORG/$REPO" --silent -f permission=push
done

echo "== Team members (non-members get an org invite)"
for entry in "${MEMBERS[@]}"; do
  read -r team user role <<<"$entry"
  run gh api -X PUT "orgs/$ORG/teams/$team/memberships/$user" --silent -f role="$role"
done

# Creating a team makes its creator a maintainer; drop anyone not listed above.
echo "== Remove unlisted team members"
for entry in "${TEAMS[@]}"; do
  team="${entry%%|*}"
  current="$(gh api "orgs/$ORG/teams/$team/members" --jq '.[].login' 2>/dev/null)" || continue
  for user in $current; do
    if ! printf '%s\n' "${MEMBERS[@]}" | grep -qx "$team $user [a-z]*"; then
      run gh api -X DELETE "orgs/$ORG/teams/$team/memberships/$user" --silent
    fi
  done
done

echo "== Labels"
for entry in "${LABELS[@]}"; do
  IFS='|' read -r name color desc <<<"$entry"
  run gh label create "$name" --repo "$ORG/$REPO" --color "$color" --description "$desc" --force
done

echo "== Rulesets"
for file in "$HERE/ruleset-main.json" "$HERE/ruleset-departments.json"; do
  name="$(sed -n 's/^  "name": "\(.*\)",$/\1/p' "$file")"
  id="$(gh api "repos/$ORG/$REPO/rulesets" --jq ".[] | select(.name == \"$name\") | .id")"
  if [ -n "$id" ]; then
    run gh api -X PUT "repos/$ORG/$REPO/rulesets/$id" --silent --input "$file"
  else
    run gh api -X POST "repos/$ORG/$REPO/rulesets" --silent --input "$file"
  fi
done

echo "Done."
