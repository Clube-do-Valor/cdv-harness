#!/usr/bin/env python3
"""Propose the run profile of a request from its signals (step 2 of cdv-kickoff).

    propose_profile.py --signals <json | file | -> [--answer key=value ...]

The signals are a JSON object the kickoff fills from the request and the repository; every key
below is required, and an unknown key, a missing key or a value outside its set exits 2 naming
the key, with nothing on stdout. Each `--answer` is the developer's answer on the question screen:
it sets that run profile key, and every key that follows from it is derived again (an answer
`track=big` also changes the mode, the rounds, the review...). The run profile goes to stdout in
the flat format of door 1; `run_profile.py validate` accepts it.
"""

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_common import (  # noqa: E402
    BAD_INPUT,
    INVESTIGATE,
    OK,
    OPTIONAL_STEPS,
    RUN_LISTS,
    RUN_SCALARS,
    SLUG_RE,
    STAGES,
    ScriptError,
    render,
)

BOOL = "bool"
COUNT = "count"
# Signal -> its set. A tuple is an enum; `count` a whole number >= its minimum.
SIGNALS = {
    "feature": "slug",
    "intent": ("build", "investigate"),
    "files_estimate": (COUNT, 0),
    "migration": ("none", "schema", "data"),
    "new_screen": BOOL,
    "screen_audience_other": BOOL,
    "changes_existing_screen": BOOL,
    "appearance_decision": BOOL,
    "external_integration": "list",
    "access_kernel": BOOL,
    "money_or_contract": BOOL,
    "one_way_door": BOOL,
    "repositories": (COUNT, 1),
    "main_checkout_free": BOOL,
    "origin": ("card", "chat-thread", "brief", "direct"),
    "waiting_reply": BOOL,
    "owner_must_validate": BOOL,
    "no_precedent": BOOL,
}

# The keys an answer on the screen may set; the others follow from them.
ANSWERABLE = [
    "track",
    "mode",
    "planner",
    "workspace",
    "builder",
    "builder_role",
    "verify_rounds",
    "fault_injection",
    "review",
    "qa",
    "optional",
]


def check_signals(signals):
    if not isinstance(signals, dict):
        raise ScriptError("signals: must be a JSON object")
    for key in signals:
        if key not in SIGNALS:
            raise ScriptError(f"signals: unknown key `{key}` (known: {', '.join(SIGNALS)})")
    for key, kind in SIGNALS.items():
        if key not in signals:
            raise ScriptError(f"signals: missing key `{key}`")
        value = signals[key]
        if kind == BOOL:
            ok = isinstance(value, bool)
        elif kind == "list":
            ok = isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
        elif kind == "slug":
            ok = isinstance(value, str) and bool(SLUG_RE.match(value))
        elif kind[0] == COUNT:
            ok = isinstance(value, int) and not isinstance(value, bool) and value >= kind[1]
        else:
            ok = value in kind
        if not ok:
            raise ScriptError(f"signals: `{key}` has the value {json.dumps(value)}, outside its set ({describe(kind)})")


def describe(kind):
    if kind == BOOL:
        return "true or false"
    if kind == "list":
        return "a list of names"
    if kind == "slug":
        return "a kebab-case slug"
    if kind[0] == COUNT:
        return f"a whole number from {kind[1]}"
    return ", ".join(kind)


def parse_answers(pairs):
    answers = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or key not in ANSWERABLE:
            raise ScriptError(f"answer: `{key}` cannot be answered (answerable: {', '.join(ANSWERABLE)})")
        if key == "optional":
            items = [v.strip() for v in value.split(",") if v.strip()]
            for item in items:
                if item not in OPTIONAL_STEPS:
                    raise ScriptError(f"answer: optional step `{item}` is not one of {', '.join(OPTIONAL_STEPS)}")
            answers[key] = items
        else:
            if value not in RUN_SCALARS[key]:
                raise ScriptError(f"answer: `{key}={value}` is outside its set ({', '.join(RUN_SCALARS[key])})")
            answers[key] = value
    return answers


def big_signal(s):
    return (
        (s["new_screen"] and s["screen_audience_other"])
        or bool(s["external_integration"])
        or s["access_kernel"]
        or s["repositories"] > 1
        or s["migration"] == "data"
    )


def propose(s, answers=None):
    """The run profile values for the signals, with the screen's answers applied."""
    answers = answers or {}

    def pick(key, derived):
        return answers.get(key, derived)

    if big_signal(s):
        track = "big"
    elif s["files_estimate"] <= 3 and s["migration"] == "none" and not s["new_screen"]:
        track = "small"
    else:
        track = "medium"
    track = pick("track", track)
    small = track == "small"

    if s["intent"] == "investigate":
        mode = "investigate"
    else:
        mode = "autonomous" if small else "plan-then-build"
    mode = pick("mode", mode)
    planner = pick("planner", "none" if small else "tlc-spec-lean")
    risk = s["access_kernel"] or s["money_or_contract"] or s["one_way_door"]
    screen = s["new_screen"] or s["changes_existing_screen"]
    if not screen:
        qa = "none"
    elif s["external_integration"]:
        qa = "browser-external-test-records"
    else:
        qa = "browser-local"

    optional = []
    if s["origin"] == "chat-thread" or s["waiting_reply"]:
        optional.append("slack-draft")
    if s["appearance_decision"] or s["changes_existing_screen"]:
        optional.append("mock-before-after")
    if s["new_screen"] and s["screen_audience_other"]:
        optional.append("blind-judges")
    if s["owner_must_validate"]:
        optional.append("validation-page")

    values = {
        "schema": "1",
        "feature": s["feature"],
        "track": track,
        "mode": mode,
        "planner": planner,
        "workspace": pick("workspace", "main" if s["main_checkout_free"] and track != "big" else "worktree"),
        "builder": pick("builder", "inline" if small else "child"),
        "builder_role": pick("builder_role", "builder_risk" if risk else "builder"),
        "verify_rounds": pick("verify_rounds", {"small": "0", "medium": "2", "big": "3"}[track]),
        "fault_injection": pick("fault_injection", "true" if risk else "false"),
        "review": pick("review", "none" if small else "bugs-and-regressions"),
        "qa": pick("qa", qa),
        "unattended": "own-test-records",
        "optional": pick("optional", optional),
    }
    if mode == INVESTIGATE:
        chain = [INVESTIGATE]
    else:
        chain = [stage for stage in STAGES if stage != "research"]
        if track == "big" and s["no_precedent"]:
            chain.insert(0, "research")
    values["chain"] = chain
    values["stops"] = {
        "plan-then-build": ["plan-approval", "external-write", "production-write"],
        "autonomous": ["external-write", "production-write"],
        "step-by-step": list(chain),
        "investigate": ["report"],
    }[mode]
    return values


def read_signals(arg):
    if arg == "-":
        text = sys.stdin.read()
    elif arg.lstrip().startswith("{"):
        text = arg
    else:
        try:
            text = Path(arg).read_text(encoding="utf-8")
        except OSError as error:
            raise ScriptError(f"signals: cannot read {arg}: {error.strerror}") from error
    try:
        return json.loads(text)
    except ValueError as error:
        raise ScriptError(f"signals: not JSON ({error})") from error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--signals", required=True, help="the signals object: inline JSON, a file, or - for stdin")
    parser.add_argument("--answer", action="append", metavar="KEY=VALUE", help="an answer of the question screen")
    args = parser.parse_args(argv)
    try:
        signals = read_signals(args.signals)
        check_signals(signals)
        answers = parse_answers(args.answer)
        values = propose(signals, answers)
    except ScriptError as error:
        print(f"propose_profile: {error}", file=sys.stderr)
        return BAD_INPUT
    sys.stdout.write(render(values, list(RUN_SCALARS), list(RUN_LISTS)))
    return OK


if __name__ == "__main__":
    sys.exit(main())
