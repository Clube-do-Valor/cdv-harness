#!/usr/bin/env bash
#
# check-diff-size.sh — is a factory branch still "small"?
#
# The small tier of cdv-plan-feature (≤ ~3 files, no migration, no new
# screen) is a judgment call; the factory runs without a human, so the same
# criterion is decided here, over the real diff, with an exit code.
#
# The diff is the merge-base with origin/<default branch> up to the WORKING
# TREE, plus untracked files — so it can run before the commit as well as
# after it.
#
# Usage:
#   check-diff-size.sh [--base <ref>] [<worktree>]
#     <worktree>  defaults to the current directory
#     --base      defaults to origin/<profile.default_branch>
#
# Reads `.claude/harness/profile.yaml` (and `profile.local.yaml`, whose keys
# win) of the worktree: app_dir, default_branch, adr_dir, area_cards_glob,
# frontend_root and factory_restricted_paths.
#
# Exit codes: 0 = small; 1 = not small (every violated rule listed);
#             2 = usage or git error.
#
# Rules (<app> is profile.app_dir):
#   code-files   more than 3 code files under <app> (tests counted apart)
#   migration    anything under <app>/database/migrations/
#   new-page     a Vue file ADDED under <app>/<frontend_root>/*/Pages/ or
#                <app>/resources/js/Pages/
#   restricted   <app>/app/{Jobs,Console/Commands}/, <app>/routes/console.php,
#                <app>/config/, <adr_dir>/, docker-compose*, and every path of
#                profile.factory_restricted_paths (integration clients, adapters)
#   env          any .env* file
#   dependency   composer.json/lock, package.json/package-lock.json
#   outside-app  any other file outside <app> (an area card is allowed)
#
# Every changed file is also printed as `FILE <status>\t<path>` — the explicit
# path list cdv-factory-finalize commits (never a directory, never -A).
set -uo pipefail

usage() {
  sed -n '2,38p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

base_ref=""
wt="."
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --base) [[ $# -ge 2 ]] || usage; base_ref="$2"; shift 2 ;;
    -*) echo "check-diff-size: unknown option $1" >&2; usage ;;
    *) wt="$1"; shift ;;
  esac
done

git -C "$wt" rev-parse --git-dir >/dev/null 2>&1 || { echo "check-diff-size: $wt is not a git work tree" >&2; exit 2; }
top="$(git -C "$wt" rev-parse --show-toplevel)"

profile_value() { # key -> scalar, local file first; quotes stripped; empty when absent
  local key="$1" f v=""
  for f in "$top/.claude/harness/profile.local.yaml" "$top/.claude/harness/profile.yaml"; do
    [[ -f "$f" ]] || continue
    v="$(sed -n "s/^${key}: *//p" "$f" | head -n 1 | sed -e 's/[[:space:]]*#.*$//' -e "s/^[\"']//" -e "s/[\"']\$//")"
    [[ -n "$v" ]] && break
  done
  printf '%s' "$v"
}

profile_list() { # key -> one item per line, local file first
  local key="$1" f out=""
  for f in "$top/.claude/harness/profile.local.yaml" "$top/.claude/harness/profile.yaml"; do
    [[ -f "$f" ]] || continue
    out="$(awk -v k="$key" '
      $0 ~ "^" k ":" { on = 1; next }
      on && /^[[:space:]]*-[[:space:]]/ { sub(/^[[:space:]]*-[[:space:]]*/, ""); gsub(/^["\x27]|["\x27]$/, ""); print; next }
      on && !/^[[:space:]]*(#|$)/ { on = 0 }
    ' "$f")"
    [[ -n "$out" ]] && break
  done
  printf '%s' "$out"
}

[[ -f "$top/.claude/harness/profile.yaml" ]] || { echo "check-diff-size: .claude/harness/profile.yaml not found in $top" >&2; exit 2; }
app_dir="$(profile_value app_dir)"
default_branch="$(profile_value default_branch)"
adr_dir="$(profile_value adr_dir)"
area_cards="$(profile_value area_cards_glob)"
frontend_root="$(profile_value frontend_root)"
[[ -n "$app_dir" && -n "$default_branch" ]] || { echo "check-diff-size: the profile has no app_dir or default_branch" >&2; exit 2; }
[[ "$adr_dir" == none ]] && adr_dir=""
[[ "$area_cards" == none ]] && area_cards=""
[[ "$frontend_root" == none ]] && frontend_root=""

app="${app_dir%/}/"
[[ "$app_dir" == "." ]] && app=""
restricted_extra=()
while IFS= read -r p; do [[ -n "$p" ]] && restricted_extra+=("$p"); done < <(profile_list factory_restricted_paths)

[[ -n "$base_ref" ]] || base_ref="origin/$default_branch"
base="$(git -C "$wt" merge-base "$base_ref" HEAD 2>/dev/null)" || { echo "check-diff-size: no merge-base between $base_ref and HEAD" >&2; exit 2; }

changes="$(
  git -C "$wt" diff --name-status --no-renames "$base"
  git -C "$wt" ls-files --others --exclude-standard | sed 's/^/A\t/'
)"

code=0
tests=0
total=0
violations=()
code_list=()
files=()

flag() { violations+=("$1: $2"); }

is_restricted() {
  local path="$1" p
  case "$path" in
    "${app}app/Jobs/"*|"${app}app/Console/Commands/"*|"${app}routes/console.php"|"${app}config/"*|docker-compose*) return 0 ;;
  esac
  [[ -n "$adr_dir" && "$path" == "${adr_dir%/}/"* ]] && return 0
  for p in "${restricted_extra[@]}"; do
    # shellcheck disable=SC2254
    case "$path" in $p|"${p%/}/"*) return 0 ;; esac
  done
  return 1
}

while IFS=$'\t' read -r status path; do
  [[ -z "${path:-}" ]] && continue
  total=$((total + 1))
  files+=("FILE ${status}	${path}")
  name="${path##*/}"

  if [[ "$name" == .env* ]]; then flag env "$path"; continue; fi

  if [[ "$path" == "${app}database/migrations/"* ]]; then flag migration "$path"; continue; fi
  if is_restricted "$path"; then flag restricted "$path"; continue; fi
  case "$path" in
    composer.json|composer.lock|package.json|package-lock.json|"${app}composer.json"|"${app}composer.lock"|"${app}package.json"|"${app}package-lock.json")
      flag dependency "$path"; continue ;;
  esac

  if [[ "$status" == A ]]; then
    case "$path" in
      "${app}resources/js/Pages/"*.vue) flag new-page "$path" ;;
      "${app}${frontend_root%/}/"*/Pages/*.vue) [[ -n "$frontend_root" ]] && flag new-page "$path" ;;
    esac
  fi

  if [[ -n "$area_cards" ]]; then
    # shellcheck disable=SC2254
    case "$path" in $area_cards) continue ;; esac
  fi
  case "$path" in
    "${app}"*) ;;
    *) flag outside-app "$path"; continue ;;
  esac

  if [[ "$path" == "${app}tests/"* || "$path" == *.spec.ts || "$path" == *.spec.js || "$path" == */__tests__/* ]]; then
    tests=$((tests + 1))
  else
    code=$((code + 1))
    code_list+=("$path")
  fi
done <<< "$changes"

if [[ $code -gt 3 ]]; then
  flag code-files "$code code files under ${app:-the repository} (max 3): ${code_list[*]}"
fi

echo "check-diff-size: base $(git -C "$wt" rev-parse --short "$base") ($base_ref), $total changed file(s)"
echo "  code files under ${app:-the repository}: $code (max 3)"
echo "  test files: $tests"
for f in "${files[@]}"; do echo "$f"; done

if [[ ${#violations[@]} -eq 0 ]]; then
  echo "VERDICT: small"
  exit 0
fi

for v in "${violations[@]}"; do echo "FAIL $v"; done
echo "VERDICT: not small (${#violations[@]} violation(s))"
exit 1
