#!/usr/bin/env python3
"""Keep the status of a kickoff run: one line per stage of the run profile's chain.

    run_status.py [--root <repo>] [--run <run profile>] start <stage> [--child <name>]
    run_status.py [--root <repo>] [--run <run profile>] done <stage> [--child <name>]
    run_status.py [--root <repo>] [--run <run profile>] retry <stage> [--child <name>]
    run_status.py [--root <repo>] [--run <run profile>] show

`start` opens the next pending stage of the chain and refuses (exit 3, nothing changed) any other;
`verify` (the Review phase of `tlc-spec-lean`) runs `verify_rounds` times, which is 0 or 1: a start
after its one round is done exits 3 and marks it `capped`, because there is no second review.
A stage whose run profile value is `none` or `0` is `skipped` and never starts. `retry` hands a
`running` stage whose child died to a new child, at most twice per stage; on a stage in any other
state it exits 3 with nothing changed, so it never reopens a `done` stage nor adds a second review.
`show` prints, per stage: name, state (`pending`, `running`, `done`, `skipped`, `capped`), start and
end time (UTC), the child that ran it, its role.

The status is `status.json` in the feature's work folder, beside `run.yaml` (or in `RUN-<slug>/`
for a `RUN-<slug>.yaml` at the root). Exit 0 ok, 2 an unknown stage or no valid run profile, 3
refused.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_common import (  # noqa: E402
    BAD_INPUT,
    OK,
    REFUSED,
    ScriptError,
    find_run_profile,
    load_run_profile,
    run_folder,
    stage_role,
    stage_skipped,
)

MAX_RETRIES = 2
STATES = ("pending", "running", "done", "skipped", "capped")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Run:
    def __init__(self, root, explicit):
        self.root = Path(root)
        self.profile_path = find_run_profile(self.root, explicit)
        self.profile = load_run_profile(self.profile_path)
        self.chain = list(self.profile["chain"])
        self.path = run_folder(self.root, self.profile_path) / "status.json"
        self.stages = {}
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError as error:
                raise ScriptError(f"{self.path}: not JSON ({error})") from error
            self.stages = data.get("stages", {}) if isinstance(data, dict) else {}

    def record(self, stage):
        return self.stages.setdefault(stage, {"state": "pending", "rounds": 0, "retries": 0})

    def state(self, stage):
        stored = self.stages.get(stage, {}).get("state")
        if stored and stored != "pending":
            return stored
        return "skipped" if stage_skipped(stage, self.profile) else "pending"

    def check_stage(self, stage):
        if stage not in self.chain:
            raise ScriptError(f"unknown stage `{stage}`: the chain of {self.profile_path.name} is {', '.join(self.chain)}")

    def next_pending(self):
        for stage in self.chain:
            if self.state(stage) in ("pending", "running"):
                return stage
        return None

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"run_profile": str(self.profile_path), "stages": self.stages}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    # -- commands --------------------------------------------------------------------------

    def start(self, stage, child):
        self.check_stage(stage)
        state = self.state(stage)
        if state == "skipped":
            raise ScriptError(f"`{stage}` is skipped by the run profile and never starts", REFUSED)
        if state == "capped":
            raise ScriptError(f"`{stage}` is capped; go on to the next stage", REFUSED)
        if state == "running":
            raise ScriptError(f"`{stage}` is already running", REFUSED)
        running = [s for s in self.chain if self.state(s) == "running"]
        if running:
            raise ScriptError(f"`{running[0]}` is still running: mark it done first", REFUSED)
        if stage == "verify" and state == "done":
            later = self.chain[self.chain.index(stage) + 1 :]
            if any(self.state(s) not in ("pending", "skipped") for s in later):
                raise ScriptError("`verify` cannot start again once a later stage has started", REFUSED)
        elif stage != self.next_pending():
            raise ScriptError(f"`{stage}` is not the next pending stage (next: {self.next_pending() or 'none'})", REFUSED)
        record = self.record(stage)
        if stage == "verify":
            cap = int(self.profile["verify_rounds"])
            if record.get("rounds", 0) >= cap:
                record["state"] = "capped"
                record["end"] = record.get("end") or now()
                self.save()
                raise ScriptError(
                    f"`verify` already ran its {cap} review round: there is no second review; write each finding left "
                    "open, with its reason, into the pull request description and go on to the next stage",
                    REFUSED,
                )
            record["rounds"] = record.get("rounds", 0) + 1
        record.update({"state": "running", "start": now(), "end": None})
        if child:
            record["child"] = child
        self.save()
        extra = f" (round {record['rounds']} of {self.profile['verify_rounds']})" if stage == "verify" else ""
        print(f"run_status: {stage} running{extra}")

    def done(self, stage, child):
        self.check_stage(stage)
        if self.state(stage) != "running":
            raise ScriptError(f"`{stage}` is {self.state(stage)}, not running", REFUSED)
        record = self.record(stage)
        record.update({"state": "done", "end": now()})
        if child:
            record["child"] = child
        self.save()
        nxt = self.next_pending()
        print(f"run_status: {stage} done; next: {nxt or 'none - the chain is complete'}")

    def retry(self, stage, child):
        self.check_stage(stage)
        state = self.state(stage)
        if state != "running":
            raise ScriptError(
                f"`{stage}` is {state}: only a running stage (its child died) can be retried", REFUSED
            )
        record = self.record(stage)
        if record.get("retries", 0) >= MAX_RETRIES:
            raise ScriptError(f"`{stage}` was retried {MAX_RETRIES} times already: stop and report", REFUSED)
        record["retries"] = record.get("retries", 0) + 1
        record.update({"state": "running", "start": now(), "end": None})
        if child:
            record["child"] = child
        self.save()
        print(f"run_status: {stage} running again (retry {record['retries']} of {MAX_RETRIES})")

    def show(self):
        for stage in self.chain:
            record = self.stages.get(stage, {})
            fields = [
                stage,
                self.state(stage),
                record.get("start") or "-",
                record.get("end") or "-",
                record.get("child") or "-",
                f"role={stage_role(stage, self.profile) or '-'}",
            ]
            if stage == "verify":
                fields.append(f"rounds={record.get('rounds', 0)}/{self.profile['verify_rounds']}")
            if record.get("retries"):
                fields.append(f"retries={record['retries']}/{MAX_RETRIES}")
            print(" ".join(fields))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository root (default: the current directory)")
    parser.add_argument("--run", help="the run profile file (default: the only one under the root)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "done", "retry"):
        p = sub.add_parser(name)
        p.add_argument("stage")
        p.add_argument("--child", help="the child that runs the stage (thread, task or agent id)")
    sub.add_parser("show")
    args = parser.parse_args(argv)
    if getattr(args, "child", None) and any(c.isspace() for c in args.child):
        print("run_status: --child takes one word", file=sys.stderr)
        return BAD_INPUT
    try:
        run = Run(args.root, args.run)
        if args.command == "start":
            run.start(args.stage, args.child)
        elif args.command == "done":
            run.done(args.stage, args.child)
        elif args.command == "retry":
            run.retry(args.stage, args.child)
        else:
            run.show()
    except ScriptError as error:
        print(f"run_status: {error}", file=sys.stderr)
        return error.code
    return OK


if __name__ == "__main__":
    sys.exit(main())
