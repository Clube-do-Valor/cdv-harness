#!/usr/bin/env bash
# Usage: verify-anchors.sh <comments-dir> [base-ref] [head-ref]
#
# Reads every per-finding *.md under <comments-dir> and asserts the
# `<!-- ANCHOR: path:line -->` header on its first non-empty line points to a
# `+` line (added or modified) in `git diff <base-ref>...<head-ref>`.
# Defaults: base-ref=origin/<default_branch> (the `default_branch` of
# .claude/harness/profile.yaml, fetched first), head-ref=HEAD. The local
# default-branch ref is possibly far behind and was never the
# intended base: a review computed against it anchors to unrelated hunks.
# Useful in PR-number mode:
#   verify-anchors.sh <review-dir> origin/<default_branch> <feature-branch>
# validates anchors against a branch without requiring a checkout.
#
# Files skipped (not inline, no anchor): _summary.md, INDEX.md, nitpicks.md.
#
# Exit 0 → all anchors valid; exit 1 → one or more anchors are missing,
# off-by-line, or point to a context (unchanged) line; exit 2 → setup error.
set -euo pipefail

dir="${1:?usage: verify-anchors.sh <comments-dir> [base-ref] [head-ref]}"
head_ref="${3:-HEAD}"

if [[ ! -d "$dir" ]]; then
  echo "verify-anchors: directory not found: $dir" >&2
  exit 2
fi

dir="$(cd "$dir" && pwd)"
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

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

default_branch="$(profile_get default_branch)"
if [[ -z "$default_branch" && -z "${2:-}" ]]; then
  echo "verify-anchors: no default_branch in .claude/harness/profile.yaml and no base-ref given." >&2
  exit 2
fi
base="${2:-origin/$default_branch}"

# Refresh the default branch when it is the base (default) or the caller passed
# the bare local name — in the latter case warn, since the local ref is usually stale.
if [[ -n "$default_branch" && "$base" == "$default_branch" ]]; then
  echo "verify-anchors: warning — base '$base' is the LOCAL ref; prefer 'origin/$default_branch'." >&2
fi
if [[ -n "$default_branch" && ( "$base" == "origin/$default_branch" || "$base" == "$default_branch" ) ]] \
   && git rev-parse --verify "origin/$default_branch" >/dev/null 2>&1; then
  git fetch --quiet origin "$default_branch" || true
fi

# Guard: base must resolve.
if ! git rev-parse --verify "$base" >/dev/null 2>&1; then
  echo "verify-anchors: base ref '$base' not found locally. Try 'origin/<default_branch>'." >&2
  exit 2
fi

# Guard: head ref must resolve.
if ! git rev-parse --verify "$head_ref" >/dev/null 2>&1; then
  echo "verify-anchors: head ref '$head_ref' not found locally." >&2
  exit 2
fi

# Build set of changed files in the diff.
mapfile -t changed_files < <(git diff "$base...$head_ref" --name-only)
if [[ ${#changed_files[@]} -eq 0 ]]; then
  echo "verify-anchors: no files in diff '$base...$head_ref' — nothing to anchor to. Confirm refs." >&2
  exit 2
fi

# Membership as a set lookup. The pipeline this replaces (printf | grep -qx) was wrong twice
# over: `grep -q` exits at the first match, the writing `printf` takes SIGPIPE, and under
# `set -o pipefail` that non-zero status made a present file report as missing — the earlier a
# path matched, the likelier it broke, so the failures looked random. It also fed the path to
# grep as a regex, so `.` matched any character.
declare -A changed_set
for cf in "${changed_files[@]}"; do
  changed_set["$cf"]=1
done

# Build a map "path:line" -> 1 for every `+` line in the unified diff (U0).
declare -A added_lines
current_file=""
cur_lineno=0
in_hunk=0
while IFS= read -r line; do
  case "$line" in
    "+++ b/"*)
      current_file="${line#+++ b/}"
      in_hunk=0
      ;;
    "@@ "*)
      new_start="$(printf '%s\n' "$line" | sed -E 's/^@@ -[0-9]+(,[0-9]+)? \+([0-9]+)(,[0-9]+)? @@.*/\2/')"
      cur_lineno="$new_start"
      in_hunk=1
      ;;
    +++*) : ;;
    +*)
      if [[ $in_hunk -eq 1 ]]; then
        added_lines["$current_file:$cur_lineno"]=1
        cur_lineno=$((cur_lineno + 1))
      fi
      ;;
    -*) : ;;
    " "*)
      [[ $in_hunk -eq 1 ]] && cur_lineno=$((cur_lineno + 1))
      ;;
    *) in_hunk=0 ;;
  esac
done < <(git diff "$base...$head_ref" -U0 --no-color)

# Collect anchors from <!-- ANCHOR: path:line --> headers.
declare -a anchors=()
declare -a anchor_files=()
while IFS= read -r f; do
  bn="$(basename "$f")"
  case "$bn" in
    _summary.md|INDEX.md|nitpicks.md) continue ;;
  esac
  a="$(grep -m1 -oE '<!-- ANCHOR: [A-Za-z0-9_./\-]+:[0-9]+ -->' "$f" 2>/dev/null | sed -E 's/^<!-- ANCHOR: ([^ ]+) -->/\1/' || true)"
  if [[ -z "$a" ]]; then
    echo "verify-anchors: missing <!-- ANCHOR: path:line --> header in $f" >&2
    exit 1
  fi
  anchors+=("$a")
  anchor_files+=("$f")
done < <(find "$dir" -maxdepth 1 -type f -name '*.md' | sort)

if [[ ${#anchors[@]} -eq 0 ]]; then
  echo "verify-anchors: no per-finding files found under $dir"
  exit 0
fi

bad=0
printf '%-72s  %-20s  %s\n' "anchor" "status" "file"
printf '%-72s  %-20s  %s\n' "------------------------------------------------------------------------" "--------------------" "----"
for i in "${!anchors[@]}"; do
  a="${anchors[$i]}"
  f="${anchor_files[$i]}"
  path="${a%:*}"
  line="${a##*:}"
  status=
  if [[ -z "${changed_set["$path"]:-}" ]]; then
    status="missing-from-diff"
  elif [[ ! -f "$path" ]]; then
    status="out-of-file"
  else
    total="$(wc -l < "$path")"
    if (( line > total )); then
      status="out-of-file"
    elif [[ -z "${added_lines["$path:$line"]:-}" ]]; then
      status="not-+-line"
    else
      status="ok"
    fi
  fi
  printf '%-72s  %-20s  %s\n' "$a" "$status" "$(basename "$f")"
  [[ "$status" != "ok" ]] && bad=1
done

if (( bad )); then
  echo
  echo "verify-anchors: one or more anchors failed. Fix them before emitting comment files." >&2
  exit 1
fi
echo
echo "verify-anchors: all ${#anchors[@]} anchors ok"
