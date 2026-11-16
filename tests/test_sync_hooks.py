import json
import random
import subprocess
import unittest

from helpers import REPO_ROOT, HarnessTestCase, is_executable

HOOK_NAMES = ["require-model", "prod-ssh", "suite-lock"]
PROJECT_DIR_PREFIX = '"$CLAUDE_PROJECT_DIR"/.claude/harness/hooks/'
PROD_HOST = "prod.example.invalid"
OWN_BASH_HOOK = {"matcher": "Bash", "hooks": [{"type": "command", "command": "./scripts/own-check.sh"}]}
OWN_POST_HOOK = {"matcher": "Edit", "hooks": [{"type": "command", "command": "./scripts/after-edit.sh"}]}


def real_hooks_core():
    return json.loads((REPO_ROOT / "settings" / "hooks-core.json").read_text())


def hook_files():
    files = {}
    for path in sorted((REPO_ROOT / "hooks").iterdir()):
        if path.is_file() and not path.name.endswith(".pyc"):
            files[f"hooks/{path.name}"] = (path.read_text(), bool(path.stat().st_mode & 0o111))
    return files


class SyncHooksTest(HarnessTestCase):
    def add_hooks(self, core, tag, entries=None, remove=()):
        files = hook_files()
        for relative in remove:
            files.pop(relative, None)
        doc = {"PreToolUse": entries if entries is not None else real_hooks_core()["PreToolUse"]}
        files["settings/hooks-core.json"] = json.dumps(doc, indent=2) + "\n"
        self.commit_core(core, files, message="feat: core hooks", tag=tag)

    def settings(self, repo):
        return json.loads((repo / ".claude/settings.json").read_text())

    def consumer_with_own_hooks(self):
        repo = self.make_consumer()
        (repo / ".claude/settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [OWN_BASH_HOOK], "PostToolUse": [OWN_POST_HOOK]}}, indent=2) + "\n"
        )
        return repo

    def test_sync_merges_the_core_hooks_and_locks_them(self):
        core = self.make_core()
        self.add_hooks(core, "v0.2.0")
        repo = self.consumer_with_own_hooks()
        result = self.sync(repo, core, "v0.2.0")
        self.assertEqual(result.returncode, 0, result.stderr)

        core_entries = real_hooks_core()["PreToolUse"]
        self.assertEqual(len(core_entries), 3)
        commands = [h["command"] for e in core_entries for h in e["hooks"]]
        self.assertEqual(sorted(commands), sorted(f"{PROJECT_DIR_PREFIX}{n}" for n in HOOK_NAMES))

        settings = self.settings(repo)
        pre = settings["hooks"]["PreToolUse"]
        self.assertEqual(pre[0], OWN_BASH_HOOK)
        for entry in core_entries:
            self.assertEqual(pre.count(entry), 1, entry)
        self.assertEqual(len(pre), 4)
        self.assertEqual(settings["hooks"]["PostToolUse"], [OWN_POST_HOOK])
        for name in HOOK_NAMES:
            self.assertTrue(is_executable(repo / ".claude/harness/hooks" / name), name)

        lock = self.read_lock(repo)
        self.assertEqual(lock["schema"], 1)
        self.assertEqual(lock["hooks"], core_entries)
        self.assertIn(".claude/harness/hooks", lock["paths"])
        self.assertIn("deny", lock)
        verified = self.verify(repo)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

    def test_second_sync_adds_no_duplicate_hook(self):
        core = self.make_core()
        self.add_hooks(core, "v0.2.0")
        self.commit_core(core, {"notes.txt": "a later change\n"}, message="fix: later", tag="v0.2.1")
        repo = self.consumer_with_own_hooks()
        self.sync(repo, core, "v0.2.0")
        self.commit_all(repo)
        again = self.sync(repo, core, "v0.2.0")
        self.assertIn("already at v0.2.0", again.stdout)
        self.sync(repo, core, "v0.2.1")
        pre = self.settings(repo)["hooks"]["PreToolUse"]
        self.assertEqual(len(pre), 4)
        for entry in real_hooks_core()["PreToolUse"]:
            self.assertEqual(pre.count(entry), 1, entry)
        self.assertEqual(self.read_lock(repo)["hooks"], real_hooks_core()["PreToolUse"])

    def test_hook_dropped_by_the_core_is_removed_on_the_next_sync(self):
        core = self.make_core()
        self.add_hooks(core, "v0.2.0")
        entries = real_hooks_core()["PreToolUse"]
        kept = [e for e in entries if not any(h["command"].endswith("/suite-lock") for h in e["hooks"])]
        dropped = [e for e in entries if e not in kept]
        self.assertEqual(len(dropped), 1)
        self.commit_core(core, {}, remove=["hooks/suite-lock"], message="feat: drop a hook")
        self.add_hooks(core, "v0.3.0", entries=kept, remove=["hooks/suite-lock"])
        repo = self.consumer_with_own_hooks()
        self.sync(repo, core, "v0.2.0")
        self.commit_all(repo)
        self.sync(repo, core, "v0.3.0")
        pre = self.settings(repo)["hooks"]["PreToolUse"]
        self.assertNotIn(dropped[0], pre)
        self.assertEqual(pre, [OWN_BASH_HOOK, *kept])
        self.assertEqual(self.read_lock(repo)["hooks"], kept)
        self.assertFalse((repo / ".claude/harness/hooks/suite-lock").exists())

    def test_consumer_hook_on_the_same_matcher_stays(self):
        core = self.make_core()
        self.add_hooks(core, "v0.2.0")
        bash_core = [e for e in real_hooks_core()["PreToolUse"] if e["matcher"] == "Bash"]
        self.assertTrue(bash_core, "the core has a hook on the matcher Bash")
        self.commit_core(core, {"notes.txt": "x\n"}, message="fix: later", tag="v0.2.1")
        repo = self.consumer_with_own_hooks()
        self.sync(repo, core, "v0.2.0")
        self.sync(repo, core, "v0.2.1")
        pre = self.settings(repo)["hooks"]["PreToolUse"]
        self.assertEqual(pre.count(OWN_BASH_HOOK), 1)
        self.assertEqual(pre[0], OWN_BASH_HOOK)
        for entry in bash_core:
            self.assertIn(entry, pre)

    def test_core_bin_scripts_but_harness_are_vendored(self):
        core = self.make_core()
        self.commit_core(
            core,
            {"bin/prod-read": ("#!/bin/sh\necho read\n", True), "bin/harness": ("#!/bin/sh\necho tool\n", True)},
            message="feat: bin scripts",
            tag="v0.2.0",
        )
        repo = self.make_consumer()
        self.sync(repo, core, "v0.2.0")
        self.assertTrue(is_executable(repo / ".claude/harness/bin/prod-read"))
        self.assertTrue((repo / ".claude/harness/bin/verify.sh").is_file())
        self.assertFalse((repo / ".claude/harness/bin/harness").exists())
        self.assertIn(".claude/harness/bin/prod-read", self.read_lock(repo)["files"])

    def test_core_without_hooks_leaves_settings_without_a_hooks_key(self):
        core = self.make_core()
        repo = self.make_consumer()
        self.sync(repo, core, "v0.1.0")
        self.assertNotIn("hooks", self.settings(repo))
        self.assertEqual(self.read_lock(repo)["hooks"], [])

    def test_a_core_hook_command_outside_the_vendored_directory_is_refused(self):
        core = self.make_core()
        bad = [{"matcher": "Bash", "hooks": [{"type": "command", "command": "scripts/elsewhere"}]}]
        self.add_hooks(core, "v0.2.0", entries=bad)
        repo = self.make_consumer()
        result = self.sync(repo, core, "v0.2.0", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn(".claude/harness/hooks/", result.stderr)
        self.assertFalse((repo / ".claude/skills").exists())


    def test_core_hook_command_other_than_the_project_dir_form_is_refused(self):
        for command in (
            ".claude/harness/hooks/prod-ssh",
            "./.claude/harness/hooks/prod-ssh",
            "${CLAUDE_PROJECT_DIR}/.claude/harness/hooks/prod-ssh",
            "$CLAUDE_PROJECT_DIR/.claude/harness/hooks/prod-ssh",
            f"{PROJECT_DIR_PREFIX}prod-ssh; true",
            f"{PROJECT_DIR_PREFIX}prod-ssh --flag",
            f"{PROJECT_DIR_PREFIX}../bin/prod-read",
            PROJECT_DIR_PREFIX,
        ):
            with self.subTest(command=command):
                core = self.make_core(name=f"core-{abs(hash(command))}")
                bad = [{"matcher": "Bash", "hooks": [{"type": "command", "command": command}]}]
                self.add_hooks(core, "v0.2.0", entries=bad)
                repo = self.make_consumer(name=f"consumer-{abs(hash(command))}")
                result = self.sync(repo, core, "v0.2.0", check=False)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(PROJECT_DIR_PREFIX, result.stderr)
                self.assertNotIn("hooks", json.loads((repo / ".claude/settings.json").read_text())
                                 if (repo / ".claude/settings.json").exists() else {})

    def test_resync_replaces_a_changed_core_entry_and_keeps_consumer_hooks(self):
        own_project_dir_hook = {"matcher": "Bash", "hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/scripts/own-check.sh'}]}
        core = self.make_core()
        self.add_hooks(core, "v0.2.0")
        old = real_hooks_core()["PreToolUse"]
        new = [dict(e, matcher="^Bash$") if e["hooks"][0]["command"].endswith("/prod-ssh") else e for e in old]
        replaced = [e for e in old if e not in new]
        self.assertEqual(len(replaced), 1)
        self.add_hooks(core, "v0.2.1", entries=new)
        repo = self.make_consumer()
        (repo / ".claude/settings.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [OWN_BASH_HOOK, own_project_dir_hook], "PostToolUse": [OWN_POST_HOOK]}}, indent=2) + "\n"
        )
        self.sync(repo, core, "v0.2.0")
        self.commit_all(repo)
        self.sync(repo, core, "v0.2.1")
        settings = self.settings(repo)
        pre = settings["hooks"]["PreToolUse"]
        self.assertNotIn(replaced[0], pre)
        self.assertEqual(pre, [OWN_BASH_HOOK, own_project_dir_hook, *[e for e in old if e in new], *[e for e in new if e not in old]])
        for entry in new:
            self.assertEqual(pre.count(entry), 1, entry)
        self.assertEqual(settings["hooks"]["PostToolUse"], [OWN_POST_HOOK])
        self.assertEqual(self.read_lock(repo)["hooks"], new)

    def test_synced_hook_commands_block_from_a_subdirectory(self):
        tag = random.randint(100000, 999999)
        test_cmd, analysis_cmd = f"sleep {tag}1", f"sleep {tag}2"
        core = self.make_core()
        self.add_hooks(core, "v0.2.0")
        repo = self.make_consumer(cmd_test_backend=test_cmd, cmd_static_analysis=analysis_cmd)
        with (repo / ".claude/harness/profile.yaml").open("a") as profile:
            profile.write(f"prod_hosts:\n  - {PROD_HOST}\n")
        self.commit_all(repo)
        self.sync(repo, core, "v0.2.0")
        (repo / "sub" / "deeper").mkdir(parents=True)
        analysis = subprocess.Popen(analysis_cmd.split(), cwd=str(repo))
        self.addCleanup(analysis.wait)
        self.addCleanup(analysis.kill)

        payloads = {
            "require-model": ("Agent", {"subagent_type": "general-purpose", "description": "x", "prompt": "x"}),
            "prod-ssh": ("Bash", {"command": f"ssh {PROD_HOST} true"}),
            "suite-lock": ("Bash", {"command": test_cmd}),
        }
        commands = {h["command"].rsplit("/", 1)[1]: h["command"]
                    for e in self.settings(repo)["hooks"]["PreToolUse"] for h in e["hooks"]}
        self.assertEqual(sorted(commands), sorted(HOOK_NAMES))
        env = dict(self.env, CLAUDE_PROJECT_DIR=str(repo))
        for name, (tool, tool_input) in payloads.items():
            payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input})
            for where in (repo, repo / "sub", repo / "sub" / "deeper"):
                with self.subTest(hook=name, cwd=where.name):
                    proc = subprocess.run(["/bin/sh", "-c", commands[name]], input=payload, text=True,
                                          capture_output=True, cwd=str(where), env=env)
                    self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                    self.assertIn(f"{name}:", proc.stderr)
            with self.subTest(hook=name, wiring="relative, the pre-fix form"):
                relative = commands[name].replace('"$CLAUDE_PROJECT_DIR"/', "")
                proc = subprocess.run(["/bin/sh", "-c", relative], input=payload, text=True,
                                      capture_output=True, cwd=str(repo / "sub"), env=env)
                self.assertEqual(proc.returncode, 127, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
