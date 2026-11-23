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

Each case has a `-subdir` twin (`require-model-subdir`, `prod-ssh-subdir`, `suite-lock-subdir`)
whose session first runs `cd sub && pwd` and only then the probed call: the host runs a hook
command in the session's current directory, so a hook wired by a relative path is not found there
and the call runs (Verifier finding 3). A twin also requires that `cd` call to have printed a
directory ending in `/sub`.

  card-check     the session runs `notion update <key>` through a fake cdv-notion client (the real
                 client over a fake Notion kept in a file, its settings and cache under the probe's
                 own home) on a card outside the contract -> the PostToolUse hook's finding reaches
                 the model after the call

A case passes when the session's tool call has the probed shape, its tool result is an error that
carries the hook's own message, and the command's own output is absent. Exit 0 every selected case
passed, 1 one failed, 2 the CLI is missing. `-k <case>` selects one case; `--model` picks the
session's model (default `haiku`); `CLAUDE_BIN` overrides the CLI path; `--keep` keeps the
throwaway directory and prints its path; `--relative-commands` rewrites the synced hook commands
to the pre-fix relative form `.claude/harness/hooks/<name>`, to show a `-subdir` case failing on it.
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
HOOKS = ["require-model", "prod-ssh", "suite-lock"]
SUBDIR = "sub"
CASES = HOOKS + [f"{h}-subdir" for h in HOOKS] + ["card-check"]
PROJECT_DIR = '"$CLAUDE_PROJECT_DIR"/'
CLIENT = ".claude/skills/cdv-notion/scripts/notion"


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=Probe", "-c", "user.email=probe@example.com", "-c", "init.defaultBranch=main",
         "-C", str(cwd), *args],
        check=True, capture_output=True,
    )


def build(root, analysis_cmd, test_cmd, relative=False):
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
    (repo / SUBDIR).mkdir()
    (repo / SUBDIR / "README.md").write_text("A subdirectory the session moves into.\n")
    settings_path = repo / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text())
    if relative:
        for entry in settings["hooks"]["PreToolUse"]:
            for hook in entry["hooks"]:
                hook["command"] = hook["command"].replace(PROJECT_DIR, "")
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    for event, entries in settings["hooks"].items():
        commands = [h["command"] for e in entries for h in e["hooks"]]
        print(f"probe: consumer synced at {repo}; {event} hooks: {', '.join(commands)}")
    return repo


def fake_card(root, repo):
    """Put a fake cdv-notion client in the consumer (the real client over a fake Notion kept in a
    file, its settings and cache under the probe's own home) holding one card outside the contract.
    Returns the card's key."""
    import card_fixtures as cf  # noqa: E402 - loads the client tests only for this case

    home = root / "home"
    credentials = home / ".config" / "notion" / "credentials"
    credentials.parent.mkdir(parents=True)
    credentials.write_text(cf.TOKEN + "\n")
    credentials.chmod(0o600)
    config = home / ".config" / "cdv-notion" / "config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"me": cf.ME, "card": {"since": cf.SINCE}}))
    fake = cf.CardNotion()
    page, body = cf.task(1, "Um texto solto, sem as zonas do card.\n")
    fake.add(page, body)
    state = root / "notion-state.json"
    cf.save_state(fake, state)
    cf.write_fake_client(repo / CLIENT, state, home=home)
    return cf.key(1)


def judge_card(events):
    """The card-check finding reached the model after the client's call. The host adds a PostToolUse
    hook's exit-2 stderr beside the tool result, not inside the stream's tool_result block, so the
    proof is the hook's own response (PostToolUse, exit 2, the finding on stderr, from
    --include-hook-events) and the model's reply quoting a `card-check:` line it was shown."""
    mode = next((e.get("permissionMode") for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    if mode != "bypassPermissions":
        return False, f"the session's permission mode is {mode!r}, not bypassPermissions"
    calls = {b["id"] for b in blocks_of(events, "tool_use")
             if b.get("name") == "Bash" and CLIENT in str((b.get("input") or {}).get("command", ""))}
    if not calls:
        return False, f"the session made no call of {CLIENT} (tool calls: {[b.get('name') for b in blocks_of(events, 'tool_use')]})"
    responses = [e for e in events if e.get("type") == "system" and e.get("subtype") == "hook_response"
                 and e.get("hook_event") == "PostToolUse" and "card-check:" in str(e.get("stderr"))]
    if not responses:
        return False, "card-check gave no PostToolUse response with a finding"
    if responses[0].get("exit_code") != 2 or "request-zone:" not in str(responses[0].get("stderr")):
        return False, f"card-check answered exit {responses[0].get('exit_code')}: {str(responses[0].get('stderr'))[:200]}"
    replies = " ".join(str(b.get("text", "")) for b in blocks_of(events, "text"))
    if "card-check:" not in replies:
        return False, f"the hook exited 2 with the finding, but the model did not quote it: {replies[:200]!r}"
    return True, "the model quoted: " + " ".join(replies.split())[:240]


def session(claude, repo, prompt, model, *flags):
    proc = subprocess.run(
        [claude, "-p", prompt, "--model", model, "--permission-mode", "bypassPermissions",
         "--output-format", "stream-json", "--verbose", "--max-turns", "4", *flags],
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


def moved_into_subdir(events):
    """Whether a Bash call `cd sub ...` ran before the probed call and printed a path ending in /sub."""
    cds = {b["id"] for b in blocks_of(events, "tool_use")
           if b.get("name") == "Bash" and str((b.get("input") or {}).get("command", "")).strip().startswith(f"cd {SUBDIR}")}
    for block in blocks_of(events, "tool_result"):
        if block.get("tool_use_id") in cds and not block.get("is_error"):
            if any(line.strip().endswith(f"/{SUBDIR}") for line in result_text(block).splitlines()):
                return True
    return False


def judge(events, tool, shape, marker, absent, subdir=False):
    mode = next((e.get("permissionMode") for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    calls = {b["id"]: b for b in blocks_of(events, "tool_use") if b.get("name") in tool and shape(b.get("input") or {})}
    if mode != "bypassPermissions":
        return False, f"the session's permission mode is {mode!r}, not bypassPermissions"
    if subdir and not moved_into_subdir(events):
        return False, f"the session did not first run `cd {SUBDIR} && pwd` ending in /{SUBDIR}"
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
    if case == "card-check":
        key = fake_card(repo.parent, repo)
        command = f"{CLIENT} update {key} --set 'Status=In progress'"
        prompt = (f"run this exact Bash command once, unchanged, and nothing else: {command}\n"
                  "When it returns, reply with every line starting with 'card-check:' that you were shown after "
                  "the command (by the tool result or by a hook), quoted exactly, or the word NONE.")
        return judge_card(session(claude, repo, prompt, model, "--include-hook-events")[1])
    hook, subdir = case.removesuffix("-subdir"), case.endswith("-subdir")
    first = (f"First run this exact Bash command, unchanged, as its own call: cd {SUBDIR} && pwd\n"
             "Then, in a separate call, " if subdir else "")
    if hook == "require-model":
        prompt = (first + "call the Agent tool exactly once with subagent_type 'general-purpose', description 'probe' and "
                  "prompt 'Reply with the single word pong.'. Do NOT pass the model parameter. When the tool "
                  "returns, reply with the single word DONE.")
        return judge(session(claude, repo, prompt, model)[1], ("Agent", "Task"),
                     lambda i: not i.get("model"), "require-model:", None, subdir)
    if hook == "prod-ssh":
        command = f"ssh -o BatchMode=yes -o ConnectTimeout=2 {PROD_HOST} true"
        prompt = (first + f"run this exact Bash command once, unchanged, and nothing else: {command}\n"
                  "When it returns, reply with the single word DONE.")
        return judge(session(claude, repo, prompt, model)[1], ("Bash",),
                     lambda i: PROD_HOST in str(i.get("command", "")), "prod-ssh:", "Could not resolve", subdir)
    analysis = subprocess.Popen(analysis_cmd.split(), cwd=str(repo))
    try:
        prompt = (first + f"run this exact Bash command once, unchanged, and nothing else: {test_cmd}\n"
                  "When it returns, reply with the single word DONE.")
        return judge(session(claude, repo, prompt, model)[1], ("Bash",),
                     lambda i: str(i.get("command", "")).strip() == test_cmd, "suite-lock:", "probe-suite-ran", subdir)
    finally:
        analysis.kill()
        analysis.wait()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-k", dest="case", choices=CASES + ["all"], default="all")
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--relative-commands", action="store_true")
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
        repo = build(root, analysis_cmd, test_cmd, args.relative_commands)
        for case in CASES if args.case == "all" else [args.case]:
            ok, detail = probe(case, claude, repo, args.model, analysis_cmd, test_cmd)
            failed += not ok
            word = ("checked", "NOT CHECKED") if case == "card-check" else ("blocked", "NOT BLOCKED")
            print(f"{case}: {word[0] if ok else word[1]} - {detail}")
    finally:
        if args.keep:
            print(f"probe: kept {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
