#!/usr/bin/env python3
"""List the documents that still mention code a commit range deleted, renamed or moved.

    docs_follow_code.py --base <rev> [--head <rev>] [--docs <path> ...] [--name <symbol> ...]
                        [--allow <file>]

A path check cannot see a stale sentence: the guide still names a file that exists, and sends the
reader to the method that left it. This reads `git diff --name-status -M <base>..<head>`, takes
every file the range deleted or renamed, and searches the documents for:

  - its old path, as written;
  - its old file name, when no file of the head tree carries that name any more and the name is at
    least six characters without its extension (so `Index.vue` does not match every guide);
  - each `--name` given: a class, a method or a constant that left its old home.

Documents are the `--docs` paths (files or folders; default: every tracked `*.md`). Deleted and
renamed documents are not searched for. `--allow` names a file with one accepted mention per line,
`<document path>` or `<document path>:<needle>`: a changelog, a decision record, a report of what
was done. Prints `<document>:<line>: <needle> (<why>)` per mention.

Exit 0 no stale mention, 1 at least one, 2 a bad argument or not a git repository.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts

DOC_SUFFIXES = (".md", ".mdx", ".txt", ".rst")


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"docs_follow_code: git {' '.join(args[:3])} failed: {result.stderr.strip()[:200]}")
    return result.stdout


def changed(root, base, head):
    """[(old path, why)] for every non-document file the range deleted or renamed."""
    out = []
    for line in git(root, "diff", "--name-status", "-M", "--diff-filter=DR", f"{base}..{head}").splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or parts[1].endswith(DOC_SUFFIXES):
            continue
        why = "deleted" if parts[0].startswith("D") else f"renamed to {parts[2]}"
        out.append((parts[1], why))
    return out


def needles(root, head, moved, names):
    """{needle: (pattern, why)}: old paths, old file names that are gone, and the named symbols."""
    alive = {Path(p).name for p in git(root, "ls-tree", "-r", "--name-only", head).splitlines()}
    found = {}
    for old, why in moved:
        found[old] = (re.compile(re.escape(old)), why)
        name = Path(old).name
        if name not in alive and len(Path(old).stem) >= 6:
            found.setdefault(name, (re.compile(r"(?<![\w./-])" + re.escape(name) + r"(?![\w-])"), f"{old} {why}"))
    for name in names:
        found[name] = (re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])"), "named with --name")
    return found


def documents(root, paths):
    if not paths:
        return sorted(p for p in git(root, "ls-files").splitlines() if p.endswith(DOC_SUFFIXES))
    out = set()
    for given in paths:
        target = root / given
        if target.is_dir():
            out.update(p for p in git(root, "ls-files", given).splitlines() if p.endswith(DOC_SUFFIXES))
        elif target.is_file():
            out.add(given)
        else:
            raise SystemExit(f"docs_follow_code: no such document path: {given}")
    return sorted(out)


def allowed(path):
    if not path:
        return set()
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Documents that still mention code a range moved.")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--docs", nargs="*", default=[])
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--allow")
    args = parser.parse_args(argv)
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode != 0:
        print("docs_follow_code: not inside a git repository", file=sys.stderr)
        return 2
    root = Path(top.stdout.strip())
    search = needles(root, args.head, changed(root, args.base, args.head), args.name)
    accepted = allowed(args.allow)
    stale = 0
    for document in documents(root, args.docs):
        if document in accepted:
            continue
        try:
            lines = (root / document).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            for needle, (pattern, why) in search.items():
                if f"{document}:{needle}" in accepted or not pattern.search(line):
                    continue
                print(f"{document}:{number}: {needle} ({why})")
                stale += 1
    if stale:
        print(f"docs_follow_code: {stale} stale mention(s) of {len(search)} moved name(s)", file=sys.stderr)
        return 1
    print(f"docs_follow_code: no document mentions the {len(search)} moved name(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
