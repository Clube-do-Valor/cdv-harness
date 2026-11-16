#!/usr/bin/env python3
"""The browser QA steps of a run, one per call, and the Markdown list the final report carries.

    qa_report.py add --what <text> --expected <text> --result pass|fail --screenshot <path>
                     [--note <text>] [--root <repo>] [--dir <folder>] [--run <run profile>]
    qa_report.py render [--root <repo>] [--dir <folder>] [--run <run profile>]

The steps live in `qa-report.json` in the run's work folder. `add` refuses a step without one of
the four fields, a result other than `pass` or `fail`, or a screenshot that is not a file (paths
are relative to the root, or absolute). `render` prints one line per step in the order added.
Exit 0, 2 on a missing or bad field or when no work folder is found.
"""

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa_common import (  # noqa: E402
    BAD_INPUT,
    OK,
    ScriptError,
    add_location_args,
    read_list,
    required,
    work_folder,
    write_list,
)

REPORT = "qa-report.json"
FIELDS = ["what", "expected", "result", "screenshot"]
RESULTS = ("pass", "fail")


def one_line(text):
    return " ".join(str(text).split())


def add(args):
    required(args, FIELDS)
    if args.result not in RESULTS:
        raise ScriptError(f"field `result` is `{args.result}`: one of {', '.join(RESULTS)}")
    shot = Path(args.screenshot)
    if not (shot if shot.is_absolute() else Path(args.root) / shot).is_file():
        raise ScriptError(f"field `screenshot`: no file at {args.screenshot}")
    path = work_folder(args.root, args.dir, args.run) / REPORT
    steps = read_list(path)
    step = {key: one_line(getattr(args, key)) for key in FIELDS}
    if args.note:
        step["note"] = one_line(args.note)
    steps.append(step)
    write_list(path, steps)
    print(f"step {len(steps)} recorded: {step['result']} - {step['what']}")


def render(args):
    steps = read_list(work_folder(args.root, args.dir, args.run) / REPORT)
    for number, step in enumerate(steps, start=1):
        note = f" ({step['note']})" if step.get("note") else ""
        print(
            f"{number}. {step['what']} - expected: {step['expected']} - result: **{step['result']}**{note} "
            f"![step {number}]({step['screenshot']})"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="qa_report.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("add")
    for field in FIELDS:
        p.add_argument(f"--{field}")
    p.add_argument("--note")
    add_location_args(p)
    add_location_args(sub.add_parser("render"))
    args = parser.parse_args(argv)
    try:
        (add if args.command == "add" else render)(args)
    except ScriptError as error:
        print(f"qa_report.py: {error}", file=sys.stderr)
        return error.code
    return OK


if __name__ == "__main__":
    sys.exit(main())
