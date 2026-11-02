#!/usr/bin/env bash
# Usage: resolve-ticket-id.sh [override]
#
# Echoes a ticket id for the current feature branch.
#
# Resolution order:
#   1. $1 override, if given (any non-empty string).
#   2. A key in `git branch --show-current` matching `ticket_key_pattern` from
#      .claude/harness/profile.yaml (an extended regular expression, matched
#      case-insensitively), or a bare #<n>. Without the profile key (missing or
#      `none`) only the bare #<n> form is tried.
#   3. Fallback: a slug derived from the branch name with the type prefix
#      stripped (e.g. `feat/report-export` -> `report-export`).
#
# Exit 1 only if none of the above resolves (e.g. detached HEAD with no override).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# Reads `key: value` from the repository profile (the local file wins), quotes stripped.
profile_get() {
  local key="$1" v="" f
  for f in .claude/harness/profile.local.yaml .claude/harness/profile.yaml; do
    [[ -f "$f" ]] || continue
    v="$(sed -n "s/^${key}: *//p" "$f" | head -n1 | tr -d '\r')"
    [[ -n "$v" ]] && break
  done
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

override="${1:-}"
if [[ -n "$override" ]]; then
  echo "$override"
  exit 0
fi

branch="$(git branch --show-current)"

# Prefer an explicit ticket id in the branch name.
pattern="$(profile_get ticket_key_pattern)"
[[ "$pattern" == "none" ]] && pattern=""
shopt -s nocasematch
if [[ -n "$pattern" && "$branch" =~ $pattern ]]; then
  echo "${BASH_REMATCH[0]}"
  exit 0
fi
if [[ "$branch" =~ (#[0-9]+) ]]; then
  echo "${BASH_REMATCH[1]}"
  exit 0
fi
shopt -u nocasematch

# Fallback: branch slug with the type prefix stripped.
if [[ -n "$branch" ]]; then
  slug="${branch#*/}"          # drop feat/ fix/ refactor/ chore/ prefix
  slug="${slug//\//-}"          # any remaining slashes -> dashes
  if [[ -n "$slug" ]]; then
    echo "$slug"
    exit 0
  fi
fi

echo "resolve-ticket-id: no ticket pattern or usable branch name in '$branch' and no override given" >&2
exit 1
