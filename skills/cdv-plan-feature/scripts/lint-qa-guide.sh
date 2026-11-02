#!/usr/bin/env bash
# Mechanical checks for a composed QA-<slug>.md (Step 4c authoring rules).
# Placeholder ids, non-local hosts and heredocs are hard failures; the
# route:list exception ({client}-style framework patterns) is honored by
# only matching the specific placeholder spellings the rules forbid.
# Repository values (local URL, test runner) come from the cdv-harness profile.
#
# Usage: ./lint-qa-guide.sh QA-<slug>.md   (repo root, ephemeral)
# Exit codes: 0 = pass; 1 = at least one FAIL; 2 = usage or profile error.

set -uo pipefail

FILE="${1:-}"
[ -n "$FILE" ] && [ -f "$FILE" ] || { echo "usage: $0 QA-<slug>.md" >&2; exit 2; }

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PROFILE="$ROOT/.claude/harness/profile.yaml"
LOCAL="$ROOT/.claude/harness/profile.local.yaml"
[ -f "$PROFILE" ] || { echo "lint-qa-guide: $PROFILE not found (this gate needs the repository's cdv-harness profile)" >&2; exit 2; }

profile_get() { # key -> value from profile.local.yaml, else profile.yaml (quotes stripped)
  local v=""
  [ -f "$LOCAL" ] && v="$(sed -n "s/^$1: *//p" "$LOCAL" | head -n1)"
  [ -n "$v" ] || v="$(sed -n "s/^$1: *//p" "$PROFILE" | head -n1)"
  v="${v%\"}"; v="${v#\"}"; v="${v%\'}"; v="${v#\'}"
  printf '%s' "$v"
}

fail=0
check_absent() { # label pattern
  hits="$(grep -nE "$2" "$FILE" || true)"
  if [ -n "$hits" ]; then printf 'FAIL %s:\n%s\n' "$1" "$hits"; fail=1; else printf 'PASS %s\n' "$1"; fi
}

check_absent "no placeholder ids ({your, <id>, SOME_ID, {some, pick one of, your-)" '\{your|<id>|SOME_ID|\{some|pick one of|your-'

# QA is local-only: every URL host must be localhost, a loopback address or the host of profile.qa_url.
qa_url="$(profile_get qa_url)"
allowed_host="$(printf '%s' "$qa_url" | sed -n 's#^[a-z]*://\([^/:]*\).*#\1#p')"
bad_hosts="$(grep -noE 'https?://[^/[:space:])>`"'"'"']+' "$FILE" | while IFS= read -r hit; do
  host="$(printf '%s' "$hit" | sed 's#^[0-9]*:https\{0,1\}://##; s#:[0-9]*$##')"
  case "$host" in localhost|127.0.0.1|0.0.0.0|'[::1]') continue ;; esac
  [ -n "$allowed_host" ] && [ "$host" = "$allowed_host" ] && continue
  printf '%s\n' "$hit"
done)"
if [ -n "$bad_hosts" ]; then printf 'FAIL URL host is not the local one (QA is local-only; profile.qa_url=%s):\n%s\n' "${qa_url:-unset}" "$bad_hosts"; fail=1; else printf 'PASS every URL host is local\n'; fi

check_absent "no heredoc REPL (breaks on copy-paste)" "<<-?'?EOF"

headings="$(grep -cE '^## [0-9]+\.' "$FILE" || true)"
unlabeled="$(grep -E '^## [0-9]+\.' "$FILE" | grep -cvE '\[(READ-ONLY|MUTABLE|PRODUCTION-AFFECTING)' || true)"
if [ "$unlabeled" -gt 0 ]; then printf 'FAIL %s of %s step headings missing a mutation label\n' "$unlabeled" "$headings"; fail=1; else printf 'PASS all %s step headings carry a mutation label\n' "$headings"; fi

if grep -q 'PRODUCTION-AFFECTING' "$FILE" && ! grep -qiE 'do not run the .?\[?PRODUCTION-AFFECTING' "$FILE"; then
  printf 'FAIL file has PRODUCTION-AFFECTING steps but no manual-only header note\n'; fail=1
else
  printf 'PASS production-affecting header note consistent\n'
fi

# The repository has one test runner (profile.cmd_test_backend); a guide naming another one is wrong.
runner_cmd="$(profile_get cmd_test_backend)"
runner=""
for r in 'php artisan test' 'vendor/bin/phpunit' 'vendor/bin/pest'; do
  case "$runner_cmd" in *"$r"*) runner="$r"; break ;; esac
done
if [ -z "$runner" ]; then
  printf 'FAIL profile.cmd_test_backend (%s) names none of: php artisan test, vendor/bin/phpunit, vendor/bin/pest\n' "${runner_cmd:-unset}"; fail=1
else
  wrong=0
  for r in 'php artisan test' 'vendor/bin/phpunit' 'vendor/bin/pest'; do
    [ "$r" = "$runner" ] && continue
    if grep -qF "$r" "$FILE"; then printf 'FAIL uses "%s" (the repository runner is "%s" — use only that)\n' "$r" "$runner"; wrong=1; fail=1; fi
  done
  [ "$wrong" -eq 0 ] && printf 'PASS test runner is %s\n' "$runner"
fi

exit $fail
