#!/usr/bin/env python3
"""Counters that may only move one way: the numbers of a refactor that nobody types.

    ratchet.py --folder <state folder> snapshot [--only <name>]
    ratchet.py --folder <state folder> check [--tighten] [--base [<rev>]] [--head <rev>]

`ratchet.json` in the state folder names the counters:

    {"counters": [{"name": "files-over-400-lines", "cmd": "<shell command>", "direction": "down"}]}

Each command runs from the repository root and its value is the last whole number it prints.
`direction` is `down` (the value may only fall), `up` (may only rise) or `same`. `snapshot` writes
the values to `baseline.json`: taken once at the start, and again in a commit that says why a
counter had to move the other way (tests deleted with the code they tested). `check` compares
today's values with the baseline and prints one line per counter; `--tighten` then writes the
values that improved, so that progress is never given back.

`check` alone compares today's values with the baseline in the working tree, which a commit can edit:
it can lower a cap or rewrite a counter's command and pass. `check --base <rev>` also reads the history
of `ratchet.json` and `baseline.json` commit by commit, oldest first (a merge against its first
parent), and fails when a commit

  - moves a baseline value the wrong way for its counter's direction,
  - rewrites the `cmd` or the `direction` of a counter that existed, or removes a counter,

unless the same commit adds an entry to `records.json` (the state folder's) under `accepted`, naming
the counter and the reason: `{"accepted": [{"counter": "tests", "reason": "tests deleted with the code
they tested, decision 4"}]}`. The working tree is judged against HEAD the same way. `--base` with no
revision reads it from `state.json` (the start of the running phase, else the base `init` recorded).
A counter that moves the right way, in any commit, passes.

Last line: `ratchet <mode>: PASS|FAIL|PARTIAL - ...`. Exit 0 every counter held, 1 a counter moved the
wrong way or a commit loosened one, 2 no configuration, a command that printed no number or a bad
argument, 3 git failed, 4 partial: nothing failed but a version of the files in the range could not be
read, so a commit was not judged.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts

TOOL = "ratchet"
DASH = "\u2014"
DIRECTIONS = ("down", "up", "same")
FROM_STATE = "@state"
UNREADABLE = object()


class BadInput(Exception):
    pass


class Environment(Exception):
    pass


def verdict(mode, status, text):
    print(f"{TOOL} {mode}: {status} {DASH} {text}")


def repository_root():
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(top.stdout.strip()) if top.returncode == 0 else Path.cwd()


def counters(folder):
    path = folder / "ratchet.json"
    if not path.is_file():
        raise BadInput(f"no ratchet.json in {folder}")
    listed = json.loads(path.read_text(encoding="utf-8")).get("counters", [])
    for counter in listed:
        if not counter.get("name") or not counter.get("cmd") or counter.get("direction") not in DIRECTIONS:
            raise BadInput(f"a counter needs name, cmd and direction ({', '.join(DIRECTIONS)}): {counter}")
    if not listed:
        raise BadInput("ratchet.json lists no counter")
    return listed


def measure(counter, root):
    result = subprocess.run(counter["cmd"], shell=True, cwd=root, capture_output=True, text=True)
    numbers = re.findall(r"-?\d+", result.stdout)
    if not numbers:
        raise BadInput(f"counter {counter['name']} printed no number (exit {result.returncode}): {result.stderr.strip()[:160]}")
    return int(numbers[-1])


def read_baseline(folder):
    path = folder / "baseline.json"
    return json.loads(path.read_text(encoding="utf-8")).get("counters", {}) if path.is_file() else {}


def write_baseline(folder, values):
    (folder / "baseline.json").write_text(json.dumps({"counters": values}, indent=2) + "\n", encoding="utf-8")


def worse(direction, before, after):
    return (direction == "down" and after > before) or (direction == "up" and after < before) or (direction == "same" and after != before)


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


# ---- the history walk -------------------------------------------------------------------------------------------


def git(root, *args, check=True):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode != 0:
        if check:
            raise Environment(f"git {' '.join(args[:3])} failed: {result.stderr.decode(errors='replace').strip()[:200]}")
        return None
    return result.stdout.decode(errors="replace")


def parse_files(texts):
    """({counter: (cmd, direction)}, {counter: value}, {(counter, reason)} accepted) of one version of the three files.
    `texts` is a dict of file name -> text or None (absent). UNREADABLE for a file that is not valid."""
    out = {}
    for name in ("ratchet.json", "baseline.json", "records.json"):
        text = texts.get(name)
        if text is None:
            out[name] = set() if name == "records.json" else {}
            continue
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            if name == "ratchet.json":
                out[name] = {c["name"]: (c.get("cmd"), c.get("direction")) for c in data.get("counters", []) if isinstance(c, dict) and "name" in c}
            elif name == "baseline.json":
                out[name] = {k: v for k, v in data.get("counters", {}).items() if isinstance(v, int)}
            else:
                out[name] = {(e["counter"], str(e.get("reason", "")).strip()) for e in data.get("accepted", [])
                             if isinstance(e, dict) and isinstance(e.get("counter"), str) and str(e.get("reason", "")).strip()}
        except (ValueError, KeyError, TypeError, AttributeError):
            if name == "records.json":
                out[name] = set()  # no waiver can be read: the judgement is stricter, not skipped
            else:
                return UNREADABLE
    return out["ratchet.json"], out["baseline.json"], out["records.json"]


def judge_move(before, after):
    """The problems of one transition between two versions: (list of (counter, message))."""
    (cmds_before, base_before, accepted_before), (cmds_after, base_after, accepted_after) = before, after
    waived = {counter for counter, _ in accepted_after - accepted_before}
    problems = []
    for name, (cmd, direction) in cmds_before.items():
        if name not in cmds_after:
            problems.append((name, f"removes the counter {name}"))
        elif cmds_after[name][0] != cmd:
            problems.append((name, f"rewrites the command of {name}"))
        elif cmds_after[name][1] != direction:
            problems.append((name, f"changes the direction of {name} ({direction} -> {cmds_after[name][1]})"))
    for name, was in base_before.items():
        if name in base_after:
            direction = (cmds_before.get(name) or cmds_after.get(name) or (None, None))[1]
            if direction in DIRECTIONS and worse(direction, was, base_after[name]):
                problems.append((name, f"moves the baseline of {name} the wrong way ({was} -> {base_after[name]}, may only go {direction})"))
    return [message for name, message in problems if name not in waived]


def history_problems(root, relative, base, head):
    """([(label, message)], unreadable commits) of every commit of base..head that touched the files, plus the working tree."""
    names = ("ratchet.json", "baseline.json", "records.json")
    paths = {name: f"{relative}/{name}" if relative != "." else name for name in names}

    def at(revision):
        return parse_files({name: git(root, "show", f"{revision}:{path}", check=False) for name, path in paths.items()})

    problems, unreadable = [], 0
    for sha in git(root, "rev-list", "--reverse", "--topo-order", f"{base}..{head}").split():
        parents = git(root, "rev-list", "--parents", "-n", "1", sha).split()[1:]
        parent = parents[0] if parents else None
        diff = ["diff-tree", "--root", "-r", "--name-only", "--no-commit-id"] if parent is None else ["diff-tree", "-r", "--name-only", parent]
        changed = git(root, *diff, sha, "--", paths["ratchet.json"], paths["baseline.json"])
        if not changed.split():
            continue
        label = git(root, "log", "-1", "--format=%h %s", sha).strip()
        after = at(sha)
        before = at(parent) if parent else parse_files({})
        if after is UNREADABLE or before is UNREADABLE:
            unreadable += 1
            continue
        problems += [(label, message) for message in judge_move(before, after)]
    disk = {name: (Path(root) / path).read_text(encoding="utf-8") if (Path(root) / path).is_file() else None for name, path in paths.items()}
    if any(text is not None for text in disk.values()):
        after, before = parse_files(disk), at(head)
        if after is UNREADABLE or before is UNREADABLE:
            unreadable += 1
        else:
            problems += [("the working tree", message) for message in judge_move(before, after)]
    return problems, unreadable


# -----------------------------------------------------------------------------------------------------------------


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise BadInput(message)


def main(argv=None):
    parser = Parser(description="Counters that may only move one way.")
    parser.add_argument("--folder", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--only")
    check = commands.add_parser("check")
    check.add_argument("--tighten", action="store_true")
    check.add_argument("--base", nargs="?", const=FROM_STATE, help="also judge every commit since <rev>; bare: from state.json")
    check.add_argument("--head", default="HEAD")
    mode = "check"
    try:
        args = parser.parse_args(argv)
        mode = args.command
        folder, root = Path(args.folder), repository_root()
        listed = counters(folder)
        baseline = read_baseline(folder)
        if args.command == "snapshot":
            for counter in listed:
                if args.only and counter["name"] != args.only:
                    continue
                baseline[counter["name"]] = measure(counter, root)
                print(f"{counter['name']}: {baseline[counter['name']]}")
            write_baseline(folder, baseline)
            verdict(mode, "PASS", f"{len(baseline)} baseline value(s) written")
            return 0
        failed, held, unreadable, judged = False, 0, 0, None
        if args.base is not None:
            base = base_from_state(folder) if args.base == FROM_STATE else args.base
            if not base:
                raise BadInput("--base needs a revision, or a base in state.json: run `refactor_state.py init` in the repository")
            for revision in (base, args.head):
                if git(root, "rev-parse", "--verify", "-q", f"{revision}^{{commit}}", check=False) is None:
                    raise BadInput(f"{revision} is not a commit of {root}")
            relative = os.path.relpath(folder.resolve(), Path(root).resolve())
            if relative.startswith(".."):
                raise BadInput(f"{folder} is outside the repository: its history cannot be read")
            problems, unreadable = history_problems(root, relative, base, args.head)
            for label, message in problems:
                print(f"LOOSENED {label}: {message}")
            failed = bool(problems)
            judged = len(problems)
        for counter in listed:
            name, value = counter["name"], measure(counter, root)
            if name not in baseline:
                raise BadInput(f"counter {name} has no baseline: run `snapshot --only {name}`")
            before = baseline[name]
            if worse(counter["direction"], before, value):
                failed = True
                print(f"WORSE  {name}: {before} -> {value} (may only go {counter['direction']})")
            elif value != before:
                print(f"better {name}: {before} -> {value}")
                held += 1
                if args.tighten:
                    baseline[name] = value
            else:
                print(f"ok     {name}: {value}")
                held += 1
        if args.tighten and not failed:
            write_baseline(folder, baseline)
        walk = "" if judged is None else f", history since {base[:12]}: {judged} loosening(s)"
        if failed:
            verdict(mode, "FAIL", f"a counter moved the wrong way or a commit loosened one{walk}")
            return 1
        if unreadable:
            verdict(mode, "PARTIAL", f"{unreadable} commit(s) changed files that could not be read, so they were not judged{walk}")
            return 4
        verdict(mode, "PASS", f"{len(listed)} counter(s) held{walk}")
        return 0
    except SystemExit as error:  # --help
        return error.code or 0
    except (BadInput, ValueError) as error:
        print(f"ratchet: {error}", file=sys.stderr)
        verdict(mode, "FAIL", f"usage: {error}")
        return 2
    except Environment as error:
        print(f"ratchet: {error}", file=sys.stderr)
        verdict(mode, "FAIL", f"environment: {error}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
