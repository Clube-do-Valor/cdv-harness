#!/usr/bin/env python3
"""The records of a refactor are not edited quietly: a frozen file changes only with a declaration.

    records_guard.py --folder <state folder> [--base <rev>] [--head <rev>] [--worktree] [--allow-stale]

The records are the proof that behaviour did not change: recorded outputs, goldens, snapshots, contract
fixtures. A refactor that "fixes" a failing record instead of the code defeats the proof. This guard
fails when a file under a frozen location was modified, deleted, renamed away or changed in type in any
commit of `<base>..<head>` (or in the working tree with `--worktree`), unless the change is declared,
with a reason, in `records.json` **by the same commit**. Adding a file is always allowed - the first
time; from the commit that adds it, the file is protected like the ones that existed at the base.

The recordings of a refactor are made after its base, so against the base every one is "added":
comparing the two ends of the range would let a later commit edit one unseen. The range is therefore
read commit by commit, oldest first, every parent (a merge commit against its first parent, where an
edit made while resolving the merge lives). Add, modify, revert is two modifications, each needing its
declaration.

`records.json` in the state folder (it must be tracked by git, inside the repository):

    {
      "frozen":   ["tests/records/", "src/**/__snapshots__/**", "tools/check.sh"],
      "excludes": ["tests/records/registry.json"],
      "declared": [
        {"path": "tests/records/routes.json", "change": "modified", "reason": "route X retired, decision 4", "count": 1}
      ]
    }

  frozen    a folder (ends with `/`, or any plain path: the path itself and everything under it) or a
            glob where `*` matches within one folder and `**` across folders (`**/` also matches no
            folder). A pattern that matches nothing today is fine: the file may appear later.
  excludes  paths or globs a frozen entry would cover that are not frozen.
  declared  path    a path or a glob (`*` within one folder, `?` one character; never `**`). A glob that
                    would cover a whole frozen location is refused (exit 2): name the files.
            change  "modified", "deleted" or "any" (default). A rename counts as "deleted" for the old
                    path. A glob is allowed only with "modified"; a deletion names the file.
            reason  required: who decided and why, in one line.
            count   the number of files the declaration covers in its commit. Required when it covers
                    more than 10 files, or when the declarations of the commit together cover more than
                    10; when present it must equal that number.
  A declaration covers only the changes of the commit that adds it to the file (with `--worktree`: the
  uncommitted changes, while the declaration is uncommitted). A declaration added in the range that
  covers no frozen change in its own commit is stale and fails (`--allow-stale` relaxes it). One that
  predates the base covers nothing of this range and is only reported.

The frozen list is read from every version of `records.json` in the range (the base, the head, every
commit that changed it) and from the file on disk: the union of the `frozen` lists, and only the
`excludes` every version has. Removing a location in the commit that edits it does not unfreeze it;
an entry once written freezes for good. Without `--base` the base comes from `state.json` (the start of
the running phase, else the base `init` recorded).

What this cannot see: a history rewritten before the check (it reads the history it is given: a shallow
clone is not enough); what a commit that adds a file puts in it; a record in a location nobody listed;
a declaration that is honest in form and wrong in substance - it makes the act visible, it does not
judge it.

Last line: `records_guard check: PASS|FAIL|PARTIAL - ...`. Exit 0 pass, 1 an undeclared change, a stale or
miscounted declaration, or a frozen path hidden from git, 2 usage (no `records.json`, a bad file, no
base), 3 environment (git failed), 4 partial: nothing failed but a version of `records.json` could not be
read, or no frozen location is declared, so some or all of the range was not judged.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts

TOOL = "records_guard"
KIND = {"M": "modified", "T": "modified", "D": "deleted"}
WILDCARD = re.compile(r"[*?]")
COUNT_FROM = 10  # a declaration (or a commit) covering more files than this must state `count`
DASH = "—"


class Usage(Exception):
    pass


class Environment(Exception):
    pass


def verdict(mode, status, text):
    print(f"{TOOL} {mode}: {status} {DASH} {text}")


def git(root, *args, check=True):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode != 0:
        if check:
            raise Environment(f"git {' '.join(args[:3])} failed: {result.stderr.decode(errors='replace').strip()[:200]}")
        return None
    return result.stdout.decode(errors="replace")


def git_show(root, revision, relative):
    return git(root, "show", f"{revision}:{relative}", check=False)


def glob_to_regex(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


def probe_of(pattern):
    """A path that exists nowhere and matches the pattern at its deepest: a declaration that also matches it covers the whole location."""
    return pattern.replace("**/", "x/y/").replace("**", "x/y").replace("*", "a").replace("?", "a")


class Entry:
    """One frozen or excluded entry: a glob, or a path that stands for itself and everything under it."""

    def __init__(self, text):
        self.text = text
        self.is_glob = bool(WILDCARD.search(text))
        self.regex = glob_to_regex(text) if self.is_glob else None
        self.prefix = text.rstrip("/") + "/"
        self.folder = None if self.is_glob else text.endswith("/")  # None until known_files tells a plain path is a folder

    def matches(self, path):
        if self.is_glob:
            return bool(self.regex.match(path))
        return path == self.text.rstrip("/") or path.startswith(self.prefix)


class Locations:
    """The frozen locations minus the excluded ones."""

    def __init__(self, frozen=(), excludes=(), known_files=()):
        self.frozen_entries = [Entry(e) for e in dict.fromkeys(frozen)]
        self.exclude_entries = [Entry(e) for e in dict.fromkeys(excludes)]
        for entry in self.frozen_entries:
            if entry.folder is None:
                entry.folder = any(f.startswith(entry.prefix) for f in known_files)

    def frozen(self, path):
        if any(e.matches(path) for e in self.exclude_entries):
            return False
        return any(e.matches(path) for e in self.frozen_entries)

    def empty(self):
        return not self.frozen_entries


def lists_of(text):
    """(frozen, excludes) of a version of records.json, or None when it cannot be read."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    frozen = data.get("frozen", [])
    excludes = data.get("excludes", [])
    if not isinstance(frozen, list) or not isinstance(excludes, list):
        return None
    return ([p for p in frozen if isinstance(p, str) and p.strip("/ ")], [p for p in excludes if isinstance(p, str) and p.strip("/ ")])


def versions_of(root, relative, base, head):
    """The text of a tracked file at the base, the head and every commit of the range that changed it."""
    texts = [git_show(root, base, relative), git_show(root, head, relative)]
    for commit in git(root, "log", "--full-history", "-m", "--format=%H", f"{base}..{head}", "--", relative).split():
        texts.append(git_show(root, commit, relative))
    return [t for t in texts if t]


def frozen_locations(root, path, relative, base, head, known_files):
    """Returns (Locations, unreadable): the union of the `frozen` lists of every version and of the file on disk,
    and the `excludes` that every readable version has."""
    texts = versions_of(root, relative, base, head)
    if path.is_file():
        texts.append(path.read_text(encoding="utf-8"))
    frozen, excludes, unreadable = [], None, 0
    for text in texts:
        found = lists_of(text)
        if found is None:
            unreadable += 1
            continue
        frozen += found[0]
        excludes = set(found[1]) if excludes is None else excludes & set(found[1])
    return Locations(frozen, sorted(excludes or ()), known_files), unreadable


def too_broad(glob, locations, known_files=()):
    """True when the declaration would cover every file of a frozen location: by shape (every depth, or a whole
    level) or by fact (it matches every frozen file that exists, at the base or now, under one location)."""
    regex = glob_to_regex(glob)
    if not glob.strip("*/"):
        return True
    last = glob.rsplit("/", 1)[-1]
    for entry in locations.frozen_entries:
        if entry.is_glob:
            if regex.match(probe_of(entry.text)):
                return True
            under = [f for f in known_files if entry.matches(f) and locations.frozen(f)]
        elif entry.folder:
            if regex.match(entry.prefix + "x/y/b.php"):
                return True
            if regex.match(entry.prefix + "a.php") and re.fullmatch(r"\*(\.\w+)?", last):
                return True
            under = [f for f in known_files if f.startswith(entry.prefix)]
        else:
            continue
        if under and WILDCARD.search(glob) and all(regex.match(f) for f in under):
            return True
    return False


def entry_key(entry):
    """(path, change, reason, count) of a declaration as written, or None when it is not well formed."""
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
        return None
    reason = entry.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None
    count = entry.get("count")
    return (entry["path"], entry.get("change", "any"), reason.strip(), count if isinstance(count, int) and not isinstance(count, bool) else None)


def keys_of(text):
    """The well-formed declarations of a version of records.json, as a set of keys."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return set()
    declared = data.get("declared") if isinstance(data, dict) else None
    if not isinstance(declared, list):
        return set()
    return {key for key in (entry_key(e) for e in declared) if key is not None and "**" not in key[0] and key[1] in ("modified", "deleted", "any")
            and not (key[1] != "modified" and WILDCARD.search(key[0]))}


def load_declarations(label, text, locations, known_files):
    """Validates the declarations strictly (usage error) and returns their keys."""
    try:
        data = json.loads(text)
    except ValueError as error:
        raise Usage(f"{label} is not valid JSON: {error}")
    if not isinstance(data, dict):
        raise Usage(f"{label} must be a JSON object")
    declared = data.get("declared", [])
    if not isinstance(declared, list):
        raise Usage(f'{label}: "declared" must be a list')
    entries = []
    for index, entry in enumerate(declared):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
            raise Usage(f"{label}: declared[{index}] needs a path")
        path = entry["path"]
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            raise Usage(f"{label}: declared[{index}] ({path}) needs a reason")
        if "**" in path:
            raise Usage(f"{label}: declared[{index}] ({path}) TOO BROAD: `**` is not allowed in a declaration; `*` matches within one folder, so name the files or a sub-folder")
        if too_broad(path, locations, known_files):
            raise Usage(f"{label}: declared[{index}] ({path}) TOO BROAD: it covers a whole frozen location; name the files or a sub-folder")
        change = entry.get("change", "any")
        if change not in ("modified", "deleted", "any"):
            raise Usage(f'{label}: declared[{index}] change must be "modified", "deleted" or "any"')
        if change in ("deleted", "any") and WILDCARD.search(path):
            raise Usage(f'{label}: declared[{index}] ({path}) is a glob and its change is "{change}": a deletion must name the file exactly; use "change": "modified" for a glob')
        if "count" in entry and (not isinstance(entry["count"], int) or isinstance(entry["count"], bool) or entry["count"] < 1):
            raise Usage(f"{label}: declared[{index}] ({path}) count must be a positive integer")
        entries.append(entry_key(entry))
    return entries


def name_status_pairs(raw):
    fields = [field for field in raw.split("\0") if field != ""]
    return list(zip(fields[0::2], fields[1::2]))


def history_commits(root, base, head):
    """[{sha, label, changes: [(status, path)]}] of every commit of base..head, oldest first; a merge against its first parent."""
    raw = git(root, "log", "--reverse", "--topo-order", "--root", "--no-renames", "--name-status", "-z", "--diff-merges=first-parent",
              "--format=%x01%H%x02%h %s", f"{base}..{head}")
    commits, current = [], None
    tokens = [token.lstrip("\n") for token in raw.split("\0")]
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("\x01"):
            sha, label = token[1:].split("\x02", 1)
            current = {"sha": sha, "label": label, "changes": []}
            commits.append(current)
            i += 1
        elif re.fullmatch(r"[A-Z]", token) and i + 1 < len(tokens) and current is not None:
            current["changes"].append((token, tokens[i + 1]))
            i += 2
        else:
            i += 1
    return commits


def declarations_added(root, relative, base, head):
    """{commit sha: set of declaration keys that the commit adds to records.json} (against the union of its parents)."""
    listing = git(root, "log", "--full-history", "-m", "--format=%H %P", f"{base}..{head}", "--", relative)
    added = {}
    for row in listing.splitlines():
        sha, *parents = row.split()
        after = keys_of(git_show(root, sha, relative) or "")
        before = set()
        for parent in parents:
            before |= keys_of(git_show(root, parent, relative) or "")
        if after - before:
            added[sha] = added.get(sha, set()) | (after - before)
    return added


def frozen_events(changes, locations):
    events = {}
    for status, path in changes:
        kind = KIND.get(status[0])
        if kind is not None and locations.frozen(path):
            events[path] = kind
    return events


def judge(events, keys):
    """For one commit: (undeclared events, {key: [matched paths]}, problems). `events` is {path: kind}."""
    matched, union = {}, set()
    for key in sorted(keys, key=str):
        regex = glob_to_regex(key[0])
        paths = sorted(p for p, kind in events.items() if regex.match(p) and key[1] in ("any", kind))
        matched[key] = paths
        union |= set(paths)
    problems = []
    for key, paths in matched.items():
        n = len(paths)
        if key[3] is not None and key[3] != n:
            problems.append(f"COUNT MISMATCH: the declaration of {key[0]} says count {key[3]}, it covers {n} file(s) in this commit")
        elif key[3] is None and n > 0 and (n > COUNT_FROM or len(union) > COUNT_FROM):
            problems.append(f'TOO BROAD: the declaration of {key[0]} covers {n} file(s) ({len(union)} with the others of this commit) and has no "count": state the size, add "count": {n}')
    undeclared = {p: kind for p, kind in events.items() if p not in union}
    return undeclared, matched, problems


def hidden_frozen_paths(root, locations):
    """Tracked frozen paths with the skip-worktree or assume-unchanged bit set: git would not show an edit of them."""
    hidden = []
    for record in git(root, "ls-files", "-v", "-z").split("\0"):
        if len(record) > 2 and record[1] == " ":
            tag, path = record[0], record[2:]
            if (tag == "S" or tag.islower()) and locations.frozen(path):
                hidden.append(path)
    return sorted(hidden)


def known_files_of(root, base, head, worktree):
    files = set(git(root, "ls-tree", "-r", "--name-only", "-z", base).split("\0"))
    files |= set(git(root, "ls-tree", "-r", "--name-only", "-z", head).split("\0"))
    if worktree:
        files |= set(git(root, "ls-files", "-z").split("\0"))
    files.discard("")
    return sorted(files)


def base_from_state(folder):
    """The start of the running phase, else the base `init` recorded; None when state.json says neither."""
    path = folder / "state.json"
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    running = [p for p in state.get("phases", []) if p.get("status") == "running" and p.get("start")]
    return (running[-1]["start"] if running else None) or state.get("base")


def check(root, folder, base, head, worktree, allow_stale):
    path = folder / "records.json"
    relative = os.path.relpath(path.resolve(), root)
    if relative.startswith(".."):
        raise Usage(f"{path} is outside the repository {root}: its history cannot be read")
    for revision in (base, head):
        if git(root, "rev-parse", "--verify", "-q", f"{revision}^{{commit}}", check=False) is None:
            raise Usage(f"{revision} is not a commit of {root}")
    head_text = git_show(root, "HEAD" if worktree else head, relative)
    disk = path.read_text(encoding="utf-8") if path.is_file() else None
    current_text = disk if (worktree and disk is not None) else head_text
    if current_text is None:
        raise Usage(f"no records.json in {folder}: declare the frozen locations in it first")

    known = known_files_of(root, base, head, worktree)
    locations, unreadable = frozen_locations(root, path, relative, base, head, known)
    current = load_declarations(str(relative), current_text, locations, known)
    added = declarations_added(root, relative, base, head)

    lines, undeclared_all, problems, origins, judged = [], [], [], {}, 0
    for commit in history_commits(root, base, head):
        judged += 1
        events = frozen_events(commit["changes"], locations)
        keys = added.get(commit["sha"], set())
        if not events and not keys:
            continue
        undeclared, matched, issues = judge(events, keys)
        for changed, kind in sorted(undeclared.items()):
            undeclared_all.append((changed, kind, commit["label"]))
        problems += [f"{issue} (commit {commit['label']})" for issue in issues]
        for key, paths in matched.items():
            origins.setdefault(key, []).append((commit["label"], len(paths)))
            if paths:
                lines.append((key, commit["label"], len(paths)))
    hidden = []
    if worktree:
        events = frozen_events(name_status_pairs(git(root, "diff", "--name-status", "--no-renames", "-z", "HEAD")), locations)
        keys = keys_of(current_text or "") - keys_of(head_text or "")
        undeclared, matched, issues = judge(events, keys)
        for changed, kind in sorted(undeclared.items()):
            undeclared_all.append((changed, kind, "the working tree"))
        problems += [f"{issue} (the working tree)" for issue in issues]
        for key, paths in matched.items():
            origins.setdefault(key, []).append(("the working tree", len(paths)))
            if paths:
                lines.append((key, "the working tree", len(paths)))
        hidden = hidden_frozen_paths(root, locations)

    stale, old = [], []
    for key in current:
        places = origins.get(key)
        if places is None:
            old.append(key)
        else:
            stale += [(key, f"its commit {label} changes no frozen file it matches") for label, n in places if n == 0]

    print(f"{TOOL}: {base} -> {head}{' + working tree' if worktree else ''}")
    for key, label, n in lines:
        print(f"  declared  {key[1]} {key[0]} [{'count %d' % key[3] if key[3] is not None else 'no count'}]: {n} file(s) in {label}  ({key[2]})")
    for key in old:
        print(f"  old       declaration of {key[0]} [{key[1]}] predates the base: it covers nothing of this range")
    for key, why in stale:
        print(f"{'  stale' if allow_stale else 'STALE'} declaration of {key[0]} [{key[1]}]: {why}: delete the entry")
    for changed, kind, label in undeclared_all:
        print(f"UNDECLARED {kind:<8} {changed}  [{label}]")
    for problem in problems:
        print(f"FAIL      {problem}")
    for changed in hidden:
        print(f"SKIP-WORKTREE {changed}: a frozen path git is told not to look at (git update-index --no-skip-worktree / --no-assume-unchanged)")
    if undeclared_all:
        print(
            f"\n{len(undeclared_all)} frozen change(s) without a declaration IN THE COMMIT THAT MAKES THEM. The records are the proof that\n"
            "behaviour did not change: fix the code, not the record. A file counts as frozen from the commit that adds it. If the change is\n"
            f"intended and approved, amend that commit to add a declaration with a reason to {relative} (a declaration added by a later\n"
            "commit covers nothing earlier)."
        )
    failed = bool(undeclared_all) or bool(problems) or bool(hidden) or (bool(stale) and not allow_stale)
    summary = f"{judged} commit(s) read, {len(undeclared_all)} undeclared, {len({(k, label) for k, label, _ in lines})} declaration(s) in use, {len(stale)} stale"
    if failed:
        verdict("check", "FAIL", summary)
        return 1
    if locations.empty():
        verdict("check", "PARTIAL", f"no frozen location is declared in {relative}: nothing was judged ({summary})")
        return 4
    if unreadable:
        verdict("check", "PARTIAL", f"{unreadable} version(s) of {relative} could not be read, so their lists were not applied ({summary})")
        return 4
    verdict("check", "PASS", summary)
    return 0


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def main(argv=None):
    parser = Parser(description="A frozen record changes only with a declaration in the same commit.")
    parser.add_argument("--folder", required=True, help="the refactor's state folder (holds records.json)")
    parser.add_argument("--base", help="the start of the range; default: from state.json")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--worktree", action="store_true", help="also judge the working tree against HEAD")
    parser.add_argument("--allow-stale", action="store_true", help="do not fail on a declaration that covers nothing")
    try:
        args = parser.parse_args(argv)
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode != 0:
            raise Environment("not inside a git repository")
        root = Path(top.stdout.strip()).resolve()
        folder = Path(args.folder)
        base = args.base or base_from_state(folder)
        if not base:
            raise Usage("no --base and no base in state.json: run `refactor_state.py init` in the repository, or pass --base")
        return check(root, folder, base, args.head, args.worktree, args.allow_stale)
    except SystemExit as error:  # --help
        return error.code or 0
    except Usage as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        verdict("check", "FAIL", f"usage: {error}")
        return 2
    except Environment as error:
        print(f"{TOOL}: {error}", file=sys.stderr)
        verdict("check", "FAIL", f"environment: {error}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
