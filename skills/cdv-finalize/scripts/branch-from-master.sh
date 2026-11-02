#!/usr/bin/env bash
#
# branch-from-master.sh — fetch origin/<default branch> and create a new feature
# branch from it. Used by cdv-finalize before any commit when the current branch
# is the default branch or another protected branch. The default branch is
# `default_branch` in .claude/harness/profile.yaml (profile.local.yaml wins).
# With neither file, `master` is assumed.
#
# Usage: ./branch-from-master.sh <new-branch-name>
#
# Aborts if:
#   - <new-branch-name> is missing
#   - the branch already exists locally
#   - the working tree has staged changes that would conflict with the checkout
#     (unstaged tracked changes are carried over to the new branch)

set -euo pipefail

profile_value() {
  local key="$1" file value=""
  for file in .claude/harness/profile.yaml .claude/harness/profile.local.yaml; do
    [[ -f "$file" ]] || continue
    local found
    found="$(sed -n "s/^${key}: *//p" "$file" | head -n1 | sed -e 's/^["'\'']//' -e 's/["'\'']$//')"
    [[ -n "$found" ]] && value="$found"
  done
  printf '%s' "$value"
}

DEFAULT_BRANCH="$(profile_value default_branch)"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-master}"

NEW_BRANCH="${1:-}"

if [[ -z "$NEW_BRANCH" ]]; then
  echo "Usage: $0 <new-branch-name>" >&2
  exit 2
fi

if git show-ref --quiet "refs/heads/$NEW_BRANCH"; then
  echo "Branch '$NEW_BRANCH' already exists locally. Aborting." >&2
  exit 1
fi

echo "Fetching origin/$DEFAULT_BRANCH..."
git fetch origin "$DEFAULT_BRANCH" >/dev/null 2>&1

echo "Creating '$NEW_BRANCH' from origin/$DEFAULT_BRANCH..."
git checkout -b "$NEW_BRANCH" "origin/$DEFAULT_BRANCH"

echo "Done. Now on:"
git branch --show-current
git log --oneline -1
