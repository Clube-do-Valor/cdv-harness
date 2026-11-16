#!/usr/bin/env python3
"""Probe the core hooks in a real headless Claude Code session with permissions bypassed (AC 72).

Not part of `unittest discover` (it starts the `claude` CLI, needs its login and costs a few cents
per case). It builds a throwaway core from this checkout, syncs it into a throwaway consumer whose
profile lists the invented production host `prod.example.invalid`, and runs one short session per
case with `claude -p --permission-mode bypassPermissions --output-format stream-json`:

  require-model  the session calls `Agent` with no `model`        -> the hook's reason comes back
  prod-ssh       the session runs `ssh ... prod.example.invalid`  -> the hook's reason comes back
  suite-lock     the session runs the full test command while the
                 static analysis command runs in the consumer     -> the hook's reason comes back

A case passes when the session's tool call has the probed shape, its tool result is an error that
carries the hook's own message, and the command's own output is absent. Exit 0 every selected case
passed, 1 one failed, 2 the CLI is missing. `-k <case>` selects one case; `--model` picks the
session's model (default `haiku`); `CLAUDE_BIN` overrides the CLI path; `--keep` keeps the
throwaway directory and prints its path.
"""

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))

from helpers import HarnessTestCase  # noqa: E402
from test_core_release import core_files  # noqa: E402

PROD_HOST = "prod.example.invalid"
CASES = ["require-model", "prod-ssh", "suite-lock"]


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=Probe", "-c", "user.email=probe@example.com", "-c", "init.defaultBranch=main",
         "-C", str(cwd), *args],
        check=True, capture_output=True,
    )


def build(root, analysis_cmd, test_cmd):
    core, repo = root / "core", root / "consumer"
    core.mkdir()
    git(core, "init", "-q")
    for name in core_files():
        target = core / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / name, target)
    git(core, "add", "-A")
    git(core, "commit", "-q", "-m", "chore: probe core")
    git(core, "tag", "-a", "v9.0.0", "-m", "v9.0.0")

    repo.mkdir()
    git(repo, "init", "-q")
    profile = HarnessTestCase.profile_text(
        None, "src", "gh", cmd_test_backend=test_cmd, cmd_static_analysis=analysis_cmd,
        delegate_tool="none", role_builder="personal sonnet high", role_verifier="personal opus high",
    )
    profile += f"prod_hosts:\n  - {PROD_HOST}\n"
    (repo / ".claude" / "harness").mkdir(parents=True)
    (repo / ".claude" / "harness" / "profile.yaml").write_text(profile)
    (repo / "CLAUDE.md").write_text("# Probe\n\nA throwaway repository for a hook probe.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore: start")
    sync = subprocess.run(
        [sys.executable, str(REPO_ROOT / "bin" / "harness"), "sync", "v9.0.0", "--from", str(core), "--repo", str(repo)],
        capture_output=True, text=True,
    )
    if sync.returncode != 0:
        raise SystemExit(f"probe: sync failed: {sync.stderr.strip()}")
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
    print(f"probe: consumer synced at {repo}; PreToolUse hooks: {', '.join(commands)}")
    return repo


def session(claude, repo, prompt, model):
    proc = subprocess.run(
        [claude, "-p", prompt, "--model", model, "--permission-mode", "bypassPermissions",
         "--output-format", "stream-json", "--verbose", "--max-turns", "4"],
        cwd=str(repo), capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
    )
    events = []
    for line in proc.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return proc, events


def blocks_of(events, kind):
    for event in events:
        message = event.get("message") if isinstance(event, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == kind:
                yield block


def result_text(block):
    content = block.get("content")
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content or "")


def judge(events, tool, shape, marker, absent):
    mode = next((e.get("permissionMode") for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    calls = {b["id"]: b for b in blocks_of(events, "tool_use") if b.get("name") in tool and shape(b.get("input") or {})}
    if mode != "bypassPermissions":
        return False, f"the session's permission mode is {mode!r}, not bypassPermissions"
    if not calls:
        used = [b.get("name") for b in blocks_of(events, "tool_use")]
        return False, f"the session made no probed {'/'.join(tool)} call (tool calls: {used})"
    for block in blocks_of(events, "tool_result"):
        if block.get("tool_use_id") in calls:
            text = result_text(block)
            if marker in text and (absent is None or absent not in text.replace(marker, "")):
                return True, " ".join(text.split())[:240]
            return False, f"the call was not blocked by the hook: {' '.join(text.split())[:240]}"
    return False, "the probed call has no tool result"


def probe(case, claude, repo, model, analysis_cmd, test_cmd):
    if case == "require-model":
        prompt = ("Call the Agent tool exactly once with subagent_type 'general-purpose', description 'probe' and "
                  "prompt 'Reply with the single word pong.'. Do NOT pass the model parameter. When the tool "
                  "returns, reply with the single word DONE.")
        return judge(session(claude, repo, prompt, model)[1], ("Agent", "Task"),
                     lambda i: not i.get("model"), "require-model:", None)
    if case == "prod-ssh":
        command = f"ssh -o BatchMode=yes -o ConnectTimeout=2 {PROD_HOST} true"
        prompt = (f"Run this exact Bash command once, unchanged, and nothing else: {command}\n"
                  "When it returns, reply with the single word DONE.")
        return judge(session(claude, repo, prompt, model)[1], ("Bash",),
                     lambda i: PROD_HOST in str(i.get("command", "")), "prod-ssh:", "Could not resolve")
    analysis = subprocess.Popen(analysis_cmd.split(), cwd=str(repo))
    try:
        prompt = (f"Run this exact Bash command once, unchanged, and nothing else: {test_cmd}\n"
                  "When it returns, reply with the single word DONE.")
        return judge(session(claude, repo, prompt, model)[1], ("Bash",),
                     lambda i: str(i.get("command", "")).strip() == test_cmd, "suite-lock:", "probe-suite-ran")
    finally:
        analysis.kill()
        analysis.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-k", dest="case", choices=CASES + ["all"], default="all")
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    claude = os.environ.get("CLAUDE_BIN") or shutil.which("claude")
    if not claude:
        print("probe: the claude CLI is not on PATH (set CLAUDE_BIN)", file=sys.stderr)
        return 2
    version = subprocess.run([claude, "--version"], capture_output=True, text=True).stdout.strip()
    print(f"probe: {claude} ({version}), model {args.model}")
    tag = random.randint(100000, 999999)
    analysis_cmd, test_cmd = f"sleep {tag}", "echo probe-suite-ran"
    root = Path(tempfile.mkdtemp(prefix="hooks-probe-"))
    failed = 0
    try:
        repo = build(root, analysis_cmd, test_cmd)
        for case in CASES if args.case == "all" else [args.case]:
            ok, detail = probe(case, claude, repo, args.model, analysis_cmd, test_cmd)
            failed += not ok
            print(f"{case}: {'blocked' if ok else 'NOT BLOCKED'} - {detail}")
    finally:
        if args.keep:
            print(f"probe: kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
