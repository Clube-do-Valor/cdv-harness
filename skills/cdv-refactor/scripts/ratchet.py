#!/usr/bin/env python3
"""Counters that may only move one way: the numbers of a refactor that nobody types.

    ratchet.py --folder <state folder> snapshot [--only <name>]
    ratchet.py --folder <state folder> check [--tighten]

`ratchet.json` in the state folder names the counters:

    {"counters": [{"name": "files-over-400-lines", "cmd": "<shell command>", "direction": "down"}]}

Each command runs from the repository root and its value is the last whole number it prints.
`direction` is `down` (the value may only fall), `up` (may only rise) or `same`. `snapshot` writes
the values to `baseline.json`: taken once at the start, and again in a commit that says why a
counter had to move the other way (tests deleted with the code they tested). `check` compares
today's values with the baseline and prints one line per counter; `--tighten` then writes the
values that improved, so that progress is never given back.

Exit 0 every counter held, 1 a counter moved the wrong way, 2 no configuration or a command that
printed no number.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts

DIRECTIONS = ("down", "up", "same")


class BadInput(Exception):
    pass


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


def main(argv=None):
    parser = argparse.ArgumentParser(description="Counters that may only move one way.")
    parser.add_argument("--folder", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--only")
    check = commands.add_parser("check")
    check.add_argument("--tighten", action="store_true")
    args = parser.parse_args(argv)
    folder, root = Path(args.folder), repository_root()
    try:
        listed = counters(folder)
        baseline = read_baseline(folder)
        if args.command == "snapshot":
            for counter in listed:
                if args.only and counter["name"] != args.only:
                    continue
                baseline[counter["name"]] = measure(counter, root)
                print(f"{counter['name']}: {baseline[counter['name']]}")
            write_baseline(folder, baseline)
            return 0
        failed = False
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
                if args.tighten:
                    baseline[name] = value
            else:
                print(f"ok     {name}: {value}")
        if args.tighten and not failed:
            write_baseline(folder, baseline)
        return 1 if failed else 0
    except BadInput as error:
        print(f"ratchet: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
