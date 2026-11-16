#!/usr/bin/env python3
"""Watch the CI pipeline of a branch until it ends, through the repository's PR client.

    watch_pipeline.py --branch <branch> [--timeout <seconds>] [--interval <seconds>]
                      [--commit <sha>] [--root <repo>]

The client is `profile.pr_cli`: `gh` (GitHub Actions: `gh run list`, `gh run view --json jobs`), or a
client whose `--help` lists a `pipelines` command (the bundled Bitbucket client: `pipelines
--branch`, `pipelines --steps <build>`). Only the runs of `--commit` count (default: `git rev-parse
HEAD` in the root; with no git, the newest run). The last line printed is the status:
`green: ...`, `red: <failed step>`, or `timeout: ...`.

Exit 0 green, 1 red (the line names the failed step), 2 the client is not set or has no pipelines
command, 3 no terminal state before --timeout.
"""

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cdv-kickoff" / "scripts"))

from run_common import repo_profile, setting  # noqa: E402

GREEN, RED, NO_CLIENT, TIMEOUT = 0, 1, 2, 3


class WatchError(Exception):
    pass


def client_argv(root, value):
    argv = shlex.split(value)
    first = Path(argv[0])
    if not first.is_absolute() and len(first.parts) > 1 and (Path(root) / first).exists():
        argv[0] = str(Path(root) / first)
    return argv


def call(argv, root):
    proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise WatchError(f"`{' '.join(argv)}` exited {proc.returncode}: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout


def head_commit(root):
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=30)
    except OSError:
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def same_commit(a, b):
    a, b = a.lower(), b.lower()
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


class GitHub:
    """`gh`: every workflow run of the commit must succeed."""

    def __init__(self, argv, root):
        self.argv, self.root = argv, root

    def poll(self, branch, commit):
        fields = "databaseId,headSha,status,conclusion,workflowName"
        runs = json.loads(call(self.argv + ["run", "list", "--branch", branch, "--limit", "20", "--json", fields], self.root) or "[]")
        if not runs:
            return None, "no run yet"
        sha = commit or runs[0].get("headSha", "")
        runs = [r for r in runs if same_commit(r.get("headSha", ""), sha)]
        if not runs:
            return None, f"no run yet for {sha[:9]}"
        if any(r.get("status") != "completed" for r in runs):
            names = ", ".join(sorted({r.get("workflowName", "?") for r in runs if r.get("status") != "completed"}))
            return None, f"running: {names} ({sha[:9]})"
        failed = [r for r in runs if r.get("conclusion") not in ("success", "skipped", "neutral")]
        if not failed:
            return GREEN, f"green: {len(runs)} workflow run(s) of {sha[:9]} succeeded"
        run = failed[0]
        return RED, f"red: {self.failed_step(run)} ({run.get('workflowName', '?')} #{run.get('databaseId')}, {sha[:9]})"

    def failed_step(self, run):
        try:
            jobs = json.loads(call(self.argv + ["run", "view", str(run["databaseId"]), "--json", "jobs"], self.root)).get("jobs", [])
        except (WatchError, ValueError):
            return "step unknown"
        for job in jobs:
            if job.get("conclusion") in ("failure", "timed_out", "cancelled"):
                for step in job.get("steps", []):
                    if step.get("conclusion") in ("failure", "timed_out", "cancelled"):
                        return f"{job.get('name', '?')} / {step.get('name', '?')}"
                return f"{job.get('name', '?')}"
        return "step unknown"


class Pipelines:
    """A client with a `pipelines` command: `#<n> <STATE> [<RESULT>] <ref> <commit>` lines, newest first."""

    def __init__(self, argv, root):
        self.argv, self.root = argv, root

    def poll(self, branch, commit):
        runs = []
        for line in call(self.argv + ["pipelines", "--branch", branch], self.root).splitlines():
            parts = line.split()
            if len(parts) < 3 or not parts[0].startswith("#"):
                continue
            state = parts[1]
            result = parts[2] if state == "COMPLETED" and len(parts) >= 5 else ""
            runs.append({"build": parts[0][1:], "state": state, "result": result, "commit": parts[-1]})
        if not runs:
            return None, "no run yet"
        sha = commit or runs[0]["commit"]
        mine = [r for r in runs if same_commit(r["commit"], sha)]
        if not mine:
            return None, f"no run yet for {sha[:9]}"
        run = mine[0]
        if run["state"] != "COMPLETED":
            return None, f"running: #{run['build']} {run['state']} ({sha[:9]})"
        if run["result"] == "SUCCESSFUL":
            return GREEN, f"green: #{run['build']} of {sha[:9]} succeeded"
        return RED, f"red: {self.failed_step(run)} (#{run['build']} {run['result']}, {sha[:9]})"

    def failed_step(self, run):
        try:
            out = call(self.argv + ["pipelines", "--steps", run["build"]], self.root)
        except WatchError:
            return "step unknown"
        for line in out.splitlines():
            fields = line.split("\t")
            if len(fields) >= 3 and fields[1] and fields[1] != "SUCCESSFUL" and fields[0] == "COMPLETED":
                return fields[2].strip()
        return "step unknown"


def pick_client(root):
    value = setting(repo_profile(root), "pr_cli")
    if not value:
        raise WatchError("`pr_cli` is not set in the repository profile: no client to read the pipeline with")
    argv = client_argv(root, value)
    if Path(argv[0]).name == "gh":
        return GitHub(argv, root)
    try:
        proc = subprocess.run(argv + ["--help"], cwd=str(root), capture_output=True, text=True, timeout=60)
    except OSError as error:
        raise WatchError(f"cannot run `{value}`: {error}") from None
    if re.search(r"\bpipelines\b", proc.stdout + proc.stderr):
        return Pipelines(argv, root)
    raise WatchError(f"`{value}` (profile pr_cli) has no pipelines command: read the pipeline on the host's page")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="watch_pipeline.py", description=__doc__.splitlines()[0])
    parser.add_argument("--branch", required=True)
    parser.add_argument("--timeout", type=float, default=1800.0, help="seconds before giving up (default 1800)")
    parser.add_argument("--interval", type=float, default=30.0, help="seconds between two reads (default 30)")
    parser.add_argument("--commit", help="the commit whose runs count (default: HEAD of the root)")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        client = pick_client(root)
    except WatchError as error:
        print(f"watch_pipeline.py: {error}", file=sys.stderr)
        return NO_CLIENT
    commit = args.commit or head_commit(root)
    deadline = time.monotonic() + args.timeout
    last = None
    while True:
        try:
            code, line = client.poll(args.branch, commit)
        except (WatchError, ValueError, subprocess.TimeoutExpired) as error:
            code, line = None, f"read failed: {error}"
        if line != last:
            print(line, flush=True)
            last = line
        if code is not None:
            return code
        if time.monotonic() + args.interval > deadline:
            print(f"timeout: no terminal state after {args.timeout:g}s ({line})", flush=True)
            return TIMEOUT
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
