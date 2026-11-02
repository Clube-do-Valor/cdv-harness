#!/usr/bin/env bash
#
# tinker.sh — run a PHP snippet through the repository's REPL command
# (`cmd_tinker` in .claude/harness/profile.yaml, for instance
# `docker compose exec -T app php artisan tinker --execute`). When the profile
# key `cmd_noise_filter` is set (an extended regular expression), the output
# lines that match it are dropped; otherwise the output passes through.
#
# Usage:
#   ./tinker.sh -e 'echo App\Models\User::count();'
#   ./tinker.sh -f path/to/snippet.php
#   echo 'echo 1;' | ./tinker.sh
#
# The profile value is a command prefix ending in the flag that takes the
# snippet (`--execute`); the snippet is appended to it as `--execute=<snippet>`.
# `.claude/harness/profile.local.yaml` overrides `profile.yaml` key by key.
#
# Exit code: passes through the REPL command's exit code.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"

profile_get() {
  local key="$1" file value=""
  for file in "$ROOT/.claude/harness/profile.yaml" "$ROOT/.claude/harness/profile.local.yaml"; do
    [[ -f "$file" ]] || continue
    local found
    found="$(sed -n "s/^${key}: *//p" "$file" | tail -n 1)"
    [[ -n "$found" ]] && value="$found"
  done
  value="${value%\"}"; value="${value#\"}"
  value="${value%\'}"; value="${value#\'}"
  printf '%s' "$value"
}

CMD_TINKER="$(profile_get cmd_tinker)"
NOISE_FILTER="$(profile_get cmd_noise_filter)"
[[ "$NOISE_FILTER" == "none" ]] && NOISE_FILTER=""
if [[ -z "$CMD_TINKER" || "$CMD_TINKER" == "none" ]]; then
  echo "tinker.sh: cmd_tinker is missing or 'none' in .claude/harness/profile.yaml; this repository has no REPL command." >&2
  exit 2
fi
read -r -a CMD <<< "$CMD_TINKER"
SNIPPET=""

usage() {
  cat <<EOF
Usage: $0 [-e 'PHP_SNIPPET' | -f FILE]

Options:
  -e PHP_SNIPPET   Inline PHP code to execute.
  -f FILE          Path to a file containing PHP code to execute.
  -h               Show this help.

If neither -e nor -f is given, reads PHP from stdin.

The command comes from `cmd_tinker` in .claude/harness/profile.yaml.
EOF
}

while getopts ":e:f:h" opt; do
  case "$opt" in
    e) SNIPPET="$OPTARG" ;;
    f) SNIPPET="$(cat "$OPTARG")" ;;
    h) usage; exit 0 ;;
    \?) echo "Invalid option: -$OPTARG" >&2; usage >&2; exit 2 ;;
    :) echo "Option -$OPTARG requires an argument." >&2; exit 2 ;;
  esac
done

if [[ -z "$SNIPPET" ]] && ! [[ -t 0 ]]; then
  SNIPPET="$(cat)"
fi

if [[ -z "$SNIPPET" ]]; then
  echo "No PHP snippet provided (use -e, -f, or stdin)." >&2
  usage >&2
  exit 2
fi

# "${CMD[@]}=..." appends "=<snippet>" to the last word of the command (`--execute`).
# `grep -v` exits 1 when it drops every line; that must not mask the command's status.
set +e
"${CMD[@]}=$SNIPPET" 2>&1 | { if [[ -n "$NOISE_FILTER" ]]; then grep -v -E -- "$NOISE_FILTER" || true; else cat; fi; }
exit "${PIPESTATUS[0]}"
