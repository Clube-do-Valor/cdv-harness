#!/bin/sh
# verify.sh - check that the vendored harness core matches .claude/harness.lock.
#
# Usage: verify.sh [--repo DIR] [--skip-trailer-range GIT_RANGE]
#
# Run from the repository root, or pass --repo. Exit codes: 0 the vendored files match the
# lock, 1 they differ, 2 the lock is missing or unreadable. With --skip-trailer-range, a
# difference is forgiven when a commit in the range carries a `Harness-skip: <reason>` line.
#
# Limits: paths that contain spaces are not supported (the lock lists one path per line and
# the comparison splits on blanks). Needs only sh, find, sort, sed, grep, awk, sha256sum, and
# git for the trailer option. No network.

set -u

usage() {
  echo "usage: verify.sh [--repo DIR] [--skip-trailer-range GIT_RANGE]" >&2
  exit 2
}

repo=.
range=
while [ $# -gt 0 ]; do
  case $1 in
    --repo)
      [ $# -ge 2 ] || usage
      repo=$2
      shift 2
      ;;
    --skip-trailer-range)
      [ $# -ge 2 ] || usage
      range=$2
      shift 2
      ;;
    -h | --help) usage ;;
    *)
      echo "harness: unknown argument: $1" >&2
      usage
      ;;
  esac
done

cd "$repo" 2>/dev/null || {
  echo "harness: cannot enter $repo" >&2
  exit 2
}

lock=.claude/harness.lock
if [ ! -r "$lock" ]; then
  echo "harness: lock not found or unreadable: $lock" >&2
  exit 2
fi
if ! grep -q '^  "schema": 1,\{0,1\}[[:space:]]*$' "$lock" ||
  ! grep -q '^  "paths": \[' "$lock" ||
  ! grep -q '^  "files": {' "$lock"; then
  echo "harness: $lock is not a schema 1 lock (needs schema, paths and files)" >&2
  exit 2
fi

# Print the entry lines of the multi-line array or object that opens with "$1".
section() {
  awk -v open="$1" '
    index($0, open) == 1 {
      if (substr($0, length(open) + 1) ~ /^[]}],?$/) exit
      inside = 1
      next
    }
    inside && /^  []}],?$/ { exit }
    inside { print }
  ' "$lock"
}

locked_paths=$(section '  "paths": [' | sed 's/^    "\(.*\)",\{0,1\}$/\1/')
locked_files=$(section '  "files": {' | sed 's/^    "\(.*\)": "\([0-9a-f]*\)",\{0,1\}$/\1 \2/')
locked_tree=$(sed -n 's/^  "tree_sha256": "\([0-9a-f]*\)",\{0,1\}$/\1/p' "$lock")
ref=$(sed -n 's/^  "ref": "\(.*\)",\{0,1\}$/\1/p' "$lock")

current_files=$(printf '%s\n' "$locked_paths" | while IFS= read -r p; do
  if [ -n "$p" ] && [ -e "$p" ]; then
    find "$p" -type f
  fi
done | LC_ALL=C sort -u)

current_sums=$(printf '%s\n' "$current_files" | while IFS= read -r f; do
  if [ -n "$f" ]; then
    sha256sum "$f"
  fi
done)

if [ -n "$current_sums" ]; then
  current_tree=$(printf '%s\n' "$current_sums" | sha256sum | awk '{ print $1 }')
else
  current_tree=$(printf '' | sha256sum | awk '{ print $1 }')
fi

differences=$(
  {
    printf '%s\n' "$locked_files" | sed 's/^/L /'
    printf '%s\n' "$current_sums" | awk 'NF { print "C " $2 " " $1 }'
  } | awk '
    $1 == "L" && NF == 3 { locked[$2] = $3 }
    $1 == "C" && NF == 3 { current[$2] = $3 }
    END {
      for (p in current) {
        if (!(p in locked)) print "created: " p
        else if (locked[p] != current[p]) print "changed: " p
      }
      for (p in locked) if (!(p in current)) print "deleted: " p
    }
  ' | LC_ALL=C sort
)

status=0
if [ -n "$differences" ]; then
  status=1
fi
if [ "$current_tree" != "$locked_tree" ]; then
  status=1
fi

if [ "$status" -eq 0 ]; then
  echo "harness: vendored core matches $ref"
  exit 0
fi

if [ -n "$differences" ]; then
  printf '%s\n' "$differences"
fi
echo "tree_sha256: recomputed $current_tree, locked $locked_tree"

if [ -n "$range" ]; then
  reason=$(git log --format=%B "$range" 2>/dev/null |
    sed -n 's/^Harness-skip:[[:space:]]*\(.*[^[:space:]]\)[[:space:]]*$/\1/p' | awk 'NR == 1 { print; exit }')
  if [ -n "$reason" ]; then
    echo "harness: skipped by trailer: $reason"
    exit 0
  fi
fi

echo "harness: vendored core differs from $lock (run harness sync, or harness propose to send the change to the core)" >&2
exit 1
