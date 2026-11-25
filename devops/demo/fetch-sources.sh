#!/usr/bin/env bash
# backend/ and frontend/ for the demo (OPS). main has neither yet, so until they merge, the demo
# builds them from their department branches, the same idea as the compose workflow's
# backend-ref / frontend-ref inputs. Called by devops/demo/demo.sh; docs/devops/demo-codespaces.md.
#
#   DEMO_BACKEND_REF   a branch name or a full 40-character commit SHA (default: Backend)
#   DEMO_FRONTEND_REF  the same (default: Frontend)
#
# - A folder that is already in this checkout (backend/app/main.py, frontend/package.json) is used
#   as it is, and nothing is fetched for it.
# - Otherwise the ref's folder is exported with `git archive` into .demo/src/<folder>/ (gitignored).
#   The working tree and the index are never touched. .demo/src/<folder>.ref records the commit.
# - A full clone is never made shallow: --depth=1 is used only when the repository already is
#   shallow (a CI checkout, or a shallow codespace clone). A laptop clone, whose .git all worktrees
#   share, gets a plain fetch.
# - If a ref can't be fetched (no network) and an earlier export of the SAME ref exists, that export
#   is used, with a warning; another branch or SHA never stands in (the script stops instead). A
#   pinned SHA that is already in the repository needs no network at all.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"
OUT=.demo/src
mkdir -p "${OUT}"

log() { printf 'sources: %s\n' "$*"; }
die() { printf 'sources: ERROR: %s\n' "$*" >&2; exit 1; }

if [ "$(git rev-parse --is-shallow-repository)" = true ]; then
  DEPTH=(--depth=1)
else
  DEPTH=()
fi

# check_ref <ref>: stops the script on a ref that can never work (run in this shell, not in $(...),
# so `die` really stops).
check_ref() {
  local ref="$1"
  [[ "${ref}" =~ ^[0-9a-f]{40}$ ]] && return
  if [[ "${ref}" =~ ^[0-9a-f]{7,39}$ ]]; then
    die "'${ref}' looks like a short SHA: use the full 40-character SHA (git rev-parse ${ref})"
  fi
  git check-ref-format --branch "${ref}" > /dev/null 2>&1 || die "'${ref}' is not a valid branch name"
}

# fetch_commit <ref>: prints the commit the ref names, fetching it if needed; returns 1 if it can't.
fetch_commit() {
  local ref="$1"
  if [[ "${ref}" =~ ^[0-9a-f]{40}$ ]]; then
    # Already here: no network needed. Otherwise GitHub serves a reachable commit by its SHA.
    git cat-file -e "${ref}^{commit}" 2> /dev/null \
      || git fetch --quiet --no-tags "${DEPTH[@]}" origin "${ref}" || return 1
    git cat-file -e "${ref}^{commit}" 2> /dev/null || return 1
    printf '%s\n' "${ref}"
    return
  fi
  git fetch --quiet --no-tags "${DEPTH[@]}" origin "refs/heads/${ref}" || return 1
  git rev-parse FETCH_HEAD
}

# export_folder <folder> <ref> <file that must exist inside the folder>
export_folder() {
  local dir="$1" ref="$2" marker="$3" commit previous="" previous_ref=""
  if [ -f "${dir}/${marker}" ]; then
    rm -rf "${OUT:?}/${dir}" "${OUT}/${dir}.ref"
    log "${dir}/: from this checkout ($(git rev-parse --short HEAD)); ${ref} not fetched"
    return
  fi
  check_ref "${ref}"
  if [ -f "${OUT}/${dir}.ref" ]; then
    read -r _ previous_ref previous < "${OUT}/${dir}.ref"
  fi
  if ! commit="$(fetch_commit "${ref}")"; then
    # Only an earlier export of the SAME ref may stand in: never another branch or SHA.
    if [ "${previous_ref}" = "${ref}" ] && [ -f "${OUT}/${dir}/${marker}" ]; then
      log "WARNING: could not fetch ${ref}; using its earlier export (${previous:0:12})"
      return
    fi
    die "could not fetch ${ref} from origin, and there is no earlier export of that ref"
  fi
  git cat-file -e "${commit}:${dir}/${marker}" 2> /dev/null \
    || die "${ref} (${commit:0:12}) has no ${dir}/${marker}"
  if [ "${commit}" = "${previous}" ] && [ -f "${OUT}/${dir}/${marker}" ]; then
    printf '%s %s %s\n' "${dir}" "${ref}" "${commit}" > "${OUT}/${dir}.ref"
    log "${dir}/: ${ref} at ${commit:0:12} (unchanged)"
    return
  fi
  rm -rf "${OUT:?}/${dir}"
  git archive --format=tar "${commit}" "${dir}" | tar -x -C "${OUT}"
  printf '%s %s %s\n' "${dir}" "${ref}" "${commit}" > "${OUT}/${dir}.ref"
  log "${dir}/: ${ref} at ${commit:0:12} -> ${OUT}/${dir}/"
}

export_folder backend "${DEMO_BACKEND_REF:-Backend}" app/main.py
export_folder frontend "${DEMO_FRONTEND_REF:-Frontend}" package.json
