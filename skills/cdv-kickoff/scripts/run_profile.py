#!/usr/bin/env python3
"""Validate a run profile file (door 1 of the kickoff plan).

    run_profile.py validate <file>

Prints one line per error, `<file>:<line>: <key>: <problem>`, and exits 1 when there is any; exits
0 when the file is valid and 2 when it cannot be read. A run profile is flat `key: value` lines and
`- item` lists: every scalar key of door 1, the lists `optional`, `stops` and `chain`, and optional
role lines `role_<role>: <account> <model alias> <effort>` that win over the repository profile's
line for this run. No other key is accepted.
"""

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_common import (  # noqa: E402
    ALL_STAGES,
    BAD_INPUT,
    EFFORTS,
    INVALID,
    INVESTIGATE,
    OK,
    ROLE_KEYS,
    RUN_LISTS,
    RUN_SCALARS,
    SLUG_RE,
    STAGES,
    parse_lines,
)


def check_role_line(value):
    words = value.split()
    if len(words) != 3:
        return "must be `<account> <model alias> <effort>`"
    _account, alias, effort = words
    if alias == "inherit":
        return "the model alias `inherit` is not allowed: name the model"
    if effort not in EFFORTS:
        return f"effort `{effort}` is not one of {', '.join(EFFORTS)}"
    return None


def check_chain(items):
    if not items:
        return "the chain is empty"
    if len(set(items)) != len(items):
        return "a stage is listed twice"
    if INVESTIGATE in items:
        return None if items == [INVESTIGATE] else "`investigate` is a chain of its own"
    order = [STAGES.index(item) for item in items]
    if order != sorted(order):
        return "stages out of order: " + ", ".join(STAGES)
    return None


def validate_text(text):
    """The problems of a run profile text, each `<line>: <key>: <problem>`; [] when valid."""
    entries, errors = parse_lines(text)
    problems = [f"{number}: {message}" for number, message in errors]
    seen = {}
    for number, key, value in entries:
        if key in seen:
            problems.append(f"{number}: {key}: duplicate key (first on line {seen[key]})")
            continue
        seen[key] = number
        if key in RUN_SCALARS:
            if isinstance(value, list):
                problems.append(f"{number}: {key}: must be a value, not a list")
                continue
            allowed = RUN_SCALARS[key]
            if allowed == "slug":
                if not SLUG_RE.match(value):
                    problems.append(f"{number}: {key}: `{value}` is not a kebab-case slug")
            elif value not in allowed:
                problems.append(f"{number}: {key}: `{value}` is not one of {', '.join(allowed)}")
        elif key in RUN_LISTS:
            if not isinstance(value, list):
                problems.append(f"{number}: {key}: must be a list of `- item` lines")
                continue
            for item in value:
                if item not in RUN_LISTS[key]:
                    problems.append(f"{number}: {key}: `{item}` is not one of {', '.join(RUN_LISTS[key])}")
            if key == "chain":
                message = check_chain(value)
                if message:
                    problems.append(f"{number}: chain: {message}")
        elif key in ROLE_KEYS:
            message = "must be a value, not a list" if isinstance(value, list) else check_role_line(value)
            if message:
                problems.append(f"{number}: {key}: {message}")
        else:
            problems.append(f"{number}: {key}: unknown key")
    for key in list(RUN_SCALARS) + list(RUN_LISTS):
        if key not in seen:
            problems.append(f"0: {key}: missing key")
    stops = dict((k, v) for _n, k, v in entries if k in ("stops", "chain") and isinstance(v, list))
    if "stops" in stops and "chain" in stops:
        for item in stops["stops"]:
            if item in ALL_STAGES and item not in stops["chain"]:
                problems.append(f"{seen['stops']}: stops: `{item}` is not a stage of the chain")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate a run profile file")
    validate.add_argument("file")
    args = parser.parse_args(argv)
    path = Path(args.file)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"run_profile: cannot read {path}: {error.strerror}", file=sys.stderr)
        return BAD_INPUT
    problems = validate_text(text)
    for problem in problems:
        print(f"{path}:{problem}")
    if problems:
        print(f"run_profile: {len(problems)} problem(s) in {path}", file=sys.stderr)
        return INVALID
    print(f"run_profile: {path} is valid")
    return OK


if __name__ == "__main__":
    sys.exit(main())
