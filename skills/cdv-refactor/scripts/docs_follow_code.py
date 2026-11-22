#!/usr/bin/env python3
"""List the documents that still mention code a commit range deleted, renamed or moved.

    docs_follow_code.py [--base <rev> | --folder <state folder>] [--head <rev>] [--docs <path> ...]
                        [--name <symbol> ...] [--allow <file>]

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

Without `--base`, `--folder` names the state folder and the base is read from `state.json` (the start of the
running phase, else the base `init` recorded).

Last line: `docs_follow_code check: PASS|FAIL|PARTIAL - ...`. Exit 0 no stale mention, 1 at least one, 2 a bad
argument or no base, 3 not a git repository or git failed, 4 partial: no stale mention but no document was
searched.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts

DOC_SUFFIXES = (".md", ".mdx", ".txt", ".rst")
TOOL = "docs_follow_code"
DASH = "\u2014"


class Usage(Exception):
    pass


class Environment(Exception):
    pass


def verdict(status, text):
    print(f"{TOOL} check: {status} {DASH} {text}")


def base_from_state(folder):
    """The start of the running phase, else the base `init` recorded; None when state.json says neither."""
    path = Path(folder) / "state.json"
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    running = [p for p in state.get("phases", []) if p.get("status") == "running" and p.get("start")]
    return (running[-1]["start"] if running else None) or state.get("base")


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise Environment(f"git {' '.join(args[:3])} failed: {result.stderr.strip()[:200]}")
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
            raise Usage(f"no such document path: {given}")
    return sorted(out)


def allowed(path):
    if not path:
        return set()
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def main(argv=None):
    parser = Parser(description="Documents that still mention code a range moved.")
    parser.add_argument("--base")
    parser.add_argument("--folder", help="the refactor's state folder: the base is read from its state.json")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--docs", nargs="*", default=[])
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--allow")
    try:
        args = parser.parse_args(argv)
        base = args.base or (base_from_state(args.folder) if args.folder else None)
        if not base:
            raise Usage("no --base, and no base in the state.json of --folder")
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode != 0:
            raise Environment("not inside a git repository")
        root = Path(top.stdout.strip())
        search = needles(root, args.head, changed(root, base, args.head), args.name)
        accepted = allowed(args.allow)
        stale, searched = 0, 0
        for document in documents(root, args.docs):
            if document in accepted:
                continue
            try:
                lines = (root / document).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            searched += 1
            for number, line in enumerate(lines, 1):
                for needle, (pattern, why) in search.items():
                    if f"{document}:{needle}" in accepted or not pattern.search(line):
                        continue
                    print(f"{document}:{number}: {needle} ({why})")
                    stale += 1
    except SystemExit as error:  # --help
        return error.code or 0
    except Usage as error:
        print(f"docs_follow_code: {error}", file=sys.stderr)
        verdict("FAIL", f"usage: {error}")
        return 2
    except Environment as error:
        print(f"docs_follow_code: {error}", file=sys.stderr)
        verdict("FAIL", f"environment: {error}")
        return 3
    if stale:
        print(f"docs_follow_code: {stale} stale mention(s) of {len(search)} moved name(s)", file=sys.stderr)
        verdict("FAIL", f"{stale} stale mention(s) of {len(search)} moved name(s)")
        return 1
    if not searched:
        verdict("PARTIAL", "no document was searched")
        return 4
    verdict("PASS", f"no document mentions the {len(search)} moved name(s) ({searched} document(s) searched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
