#!/usr/bin/env bash
#
# lint-factory-pr.sh — cdv-finalize's PR lint, with the two waivers a
# factory request earns.
#
# Runs cdv-finalize/scripts/lint-pr-description.sh unchanged and keeps
# every one of its verdicts, except:
#   - "no external link in the body" — waived only with --no-public-link, for a
#     request that arrived through an internal chat thread with no public URL
#     (PR_GUIDELINES forbids linking a private workspace). The file must then
#     carry the line "Origem: pedido interno" so the reviewer knows why.
#   - the 40-line FLOOR — a three-file change honestly described can be
#     shorter. The 100-line ceiling still fails.
#
# Usage: lint-factory-pr.sh [--no-public-link] <slug>-pr.md
# Exit codes: 0 = pass (waivers printed as WAIVE); 1 = at least one FAIL;
#             2 = usage error or the base lint was not found.
set -uo pipefail

no_link=0
file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-public-link) no_link=1; shift ;;
    -h|--help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
    *) file="$1"; shift ;;
  esac
done
[[ -n "$file" && -f "$file" ]] || { echo "usage: $0 [--no-public-link] <slug>-pr.md" >&2; exit 2; }

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
base_lint="$here/../../cdv-finalize/scripts/lint-pr-description.sh"
if [[ ! -f "$base_lint" ]]; then
  top="$(git rev-parse --show-toplevel 2>/dev/null)"
  base_lint="$top/.claude/skills/cdv-finalize/scripts/lint-pr-description.sh"
fi
[[ -f "$base_lint" ]] || { echo "lint-factory-pr: cdv-finalize's lint-pr-description.sh not found" >&2; exit 2; }

out="$(bash "$base_lint" "$file")"
fail=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  if [[ "$line" == FAIL* ]]; then
    if [[ $no_link -eq 1 && "$line" == *"no external link in the body"* ]]; then
      if grep -q 'Origem: pedido interno' "$file"; then
        echo "WAIVE ${line#FAIL } (--no-public-link)"
      else
        echo "FAIL ${line#FAIL } — with --no-public-link the file must say 'Origem: pedido interno'"
        fail=1
      fi
      continue
    fi
    if [[ "$line" =~ ([0-9]+)\ lines\ \(target ]] && [[ "${BASH_REMATCH[1]}" -lt 40 ]]; then
      echo "WAIVE ${line#FAIL } (floor waived for factory PRs)"
      continue
    fi
    fail=1
  fi
  echo "$line"
done <<< "$out"

exit $fail
