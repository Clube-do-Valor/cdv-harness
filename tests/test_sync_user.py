import json
import os
import subprocess
import unittest

from helpers import REPO_ROOT, HarnessTestCase, load_tool, sha256_file, skill_text

SKILLS = ["cdv-grilling", "cdv-grill-me", "cdv-research-round", "cdv-notion", "cdv-notion-ticket", "cdv-notion-project"]
NOTION_CLIENT = "skills/cdv-notion/scripts/notion"
USER_EXTRA = {
    "skills/cdv-notion/SKILL.md": skill_text("cdv-notion"),
    NOTION_CLIENT: ("#!/usr/bin/env python3\nprint('notion')\n", True),
    "skills/cdv-notion-ticket/SKILL.md": skill_text("cdv-notion-ticket"),
    "skills/cdv-notion-project/SKILL.md": skill_text("cdv-notion-project"),
}


class SyncUserTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.core = self.make_core(extra=USER_EXTRA)
        self.skills = self.home / ".claude" / "skills"

    def sync_user(self, tag="v0.1.0", *extra):
        return self.harness("sync", "--user", tag, "--from", str(self.core), *extra)

    def test_installs_copies_and_a_user_lock(self):
        result = self.sync_user()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in SKILLS:
            target = self.skills / name
            self.assertTrue(target.is_dir() and not target.is_symlink(), name)
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertFalse((target / "SKILL.md").is_symlink())
        self.assertFalse((self.skills / "cdv-debug").exists())
        lock = json.loads((self.home / ".claude/harness-user.lock").read_text())
        self.assertEqual(lock["schema"], 1)
        self.assertEqual(lock["ref"], "v0.1.0")
        self.assertEqual(lock["paths"], sorted(f"skills/{n}" for n in SKILLS))
        self.assertEqual(
            sorted(lock["files"]), sorted([f"skills/{n}/SKILL.md" for n in SKILLS] + [NOTION_CLIENT])
        )
        for path, digest in lock["files"].items():
            self.assertEqual(sha256_file(self.home / ".claude" / path), digest)
        self.assertEqual(lock["commit"], self.git(self.core, "rev-parse", "v0.1.0^{commit}").stdout.strip())

    def test_executable_bit_is_preserved(self):
        self.commit_core(
            self.core, {"skills/cdv-grilling/scripts/go.sh": ("#!/bin/sh\n", True)}, message="feat: script", tag="v0.2.0"
        )
        self.sync_user("v0.2.0")
        self.assertTrue(os.access(self.skills / "cdv-grilling/scripts/go.sh", os.X_OK))

    def test_notion_client_is_installed_executable(self):
        result = self.sync_user()
        self.assertEqual(result.returncode, 0, result.stderr)
        client = self.home / ".claude" / NOTION_CLIENT
        self.assertTrue(client.is_file())
        self.assertTrue(os.access(client, os.X_OK))
        lock = json.loads((self.home / ".claude/harness-user.lock").read_text())
        self.assertIn("skills/cdv-notion", lock["paths"])

    def test_refuses_when_a_symlink_exists_and_touches_nothing(self):
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "SKILL.md").write_text("mine\n")
        self.skills.mkdir(parents=True)
        os.symlink(elsewhere, self.skills / "cdv-grill-me")
        result = self.sync_user()
        self.assertEqual(result.returncode, 1)
        self.assertIn("cdv-grill-me", result.stderr)
        self.assertTrue((self.skills / "cdv-grill-me").is_symlink())
        self.assertEqual((elsewhere / "SKILL.md").read_text(), "mine\n")
        self.assertFalse((self.skills / "cdv-grilling").exists())
        self.assertFalse((self.home / ".claude/harness-user.lock").exists())

    def test_refuses_a_hand_made_directory_that_the_lock_does_not_record(self):
        (self.skills / "cdv-grilling").mkdir(parents=True)
        (self.skills / "cdv-grilling/SKILL.md").write_text("hand made\n")
        result = self.sync_user()
        self.assertEqual(result.returncode, 1)
        self.assertIn("cdv-grilling", result.stderr)
        self.assertEqual((self.skills / "cdv-grilling/SKILL.md").read_text(), "hand made\n")
        self.assertFalse((self.skills / "cdv-research-round").exists())

    def test_refuses_a_recorded_path_that_became_a_symlink(self):
        self.sync_user()
        target = self.skills / "cdv-grilling"
        for child in sorted(target.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        target.rmdir()
        os.symlink(self.tmp, target)
        result = self.sync_user()
        self.assertEqual(result.returncode, 1)
        self.assertIn("cdv-grilling", result.stderr)

    def test_rerun_replaces_what_the_lock_recorded(self):
        self.sync_user()
        stale = self.skills / "cdv-grilling" / "stale.md"
        stale.write_text("local junk\n")
        self.commit_core(
            self.core,
            {"skills/cdv-grilling/SKILL.md": "---\nname: cdv-grilling\n---\nnew\n"},
            message="feat: change",
            tag="v0.2.0",
        )
        result = self.sync_user("v0.2.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(stale.exists())
        self.assertIn("new", (self.skills / "cdv-grilling/SKILL.md").read_text())
        self.assertEqual(json.loads((self.home / ".claude/harness-user.lock").read_text())["ref"], "v0.2.0")
        again = self.sync_user("v0.2.0")
        self.assertEqual(again.returncode, 0)

    def test_other_user_skills_are_left_alone(self):
        (self.skills / "my-own-skill").mkdir(parents=True)
        (self.skills / "my-own-skill/SKILL.md").write_text("mine\n")
        self.sync_user()
        self.assertEqual((self.skills / "my-own-skill/SKILL.md").read_text(), "mine\n")

    def test_missing_skill_in_the_tag_is_an_error(self):
        self.commit_core(
            self.core,
            {},
            remove=["skills/cdv-research-round/SKILL.md"],
            message="feat: drop one",
            tag="v0.2.0",
        )
        result = self.sync_user("v0.2.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("cdv-research-round", result.stderr)
        self.assertFalse((self.skills / "cdv-grilling").exists())

    def test_needs_a_source(self):
        result = self.harness("sync", "--user", "v0.1.0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--from", result.stderr)

    def test_no_profile_is_needed_and_the_cwd_is_not_touched(self):
        workdir = self.tmp / "elsewhere"
        workdir.mkdir()
        result = self.harness("sync", "--user", "v0.1.0", "--from", str(self.core), cwd=workdir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(workdir.iterdir()), [])


USER_PREFIX = '"${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/harness/hooks/'
OTHER_TOOL = {"matcher": "*", "hooks": [{"type": "command", "command": "other-tool hook post"}]}


def core_hook_files():
    files = {}
    for path in sorted((REPO_ROOT / "hooks").iterdir()):
        if path.is_file() and not path.name.endswith(".pyc"):
            files[f"hooks/{path.name}"] = (path.read_text(), bool(path.stat().st_mode & 0o111))
    files["settings/hooks-core.json"] = (REPO_ROOT / "settings" / "hooks-core.json").read_text()
    return files


def user_entries():
    """The core's card-check entries as the user level writes them (door 3)."""
    doc = json.loads((REPO_ROOT / "settings" / "hooks-core.json").read_text())
    out = {}
    for event in ("PostToolUse", "PostToolUseFailure"):
        entries = json.loads(json.dumps(doc[event]))
        for entry in entries:
            for hook in entry["hooks"]:
                hook["command"] = USER_PREFIX + hook["command"].rsplit("/", 1)[1]
        out[event] = entries
    return out


class UserHookTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.core = self.make_core(extra={**USER_EXTRA, **core_hook_files()})
        self.config = self.home / ".claude"

    def sync_user(self, tag="v0.1.0", *extra, env=None):
        return self.harness("sync", "--user", tag, "--from", str(self.core), *extra, env=env)

    def write_settings(self, value):
        self.config.mkdir(parents=True, exist_ok=True)
        (self.config / "settings.json").write_text(value if isinstance(value, str) else json.dumps(value, indent=4))

    def settings(self):
        return json.loads((self.config / "settings.json").read_text())

    def test_user_sync_installs_the_card_skills_and_the_hook(self):
        result = self.sync_user()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("cdv-notion", "cdv-notion-ticket", "cdv-notion-project"):
            self.assertTrue((self.config / "skills" / name / "SKILL.md").is_file(), name)
        hooks = self.config / "harness" / "hooks"
        self.assertEqual(sorted(p.name for p in hooks.iterdir()), ["card-check", "harness_hook.py"])
        self.assertTrue(os.access(hooks / "card-check", os.X_OK))
        expected = user_entries()
        self.assertEqual(self.settings(), {"hooks": expected})
        self.assertEqual(expected["PostToolUse"][0]["matcher"], "^(Bash|mcp__.+__notion-(update-page|create-pages))$")
        self.assertEqual(expected["PostToolUse"][0]["hooks"][0],
                         {"type": "command", "command": USER_PREFIX + "card-check", "timeout": 30})
        lock = json.loads((self.config / "harness-user.lock").read_text())
        self.assertEqual(lock["hooks"], [])
        self.assertEqual(lock["hooks_by_event"], expected)
        self.assertIn("harness/hooks", lock["paths"])
        self.assertIn("harness/hooks/card-check", lock["files"])

    def test_user_settings_keep_other_keys_and_entries(self):
        original = {"permissions": {"allow": ["Bash(ls:*)"], "deny": ["Read(.env)"]}, "model": "opus",
                    "hooks": {"PostToolUse": [OTHER_TOOL], "PreToolUse": [OTHER_TOOL]}}
        self.write_settings(original)
        self.assertEqual(self.sync_user().returncode, 0)
        self.assertEqual(self.sync_user().returncode, 0)
        data = self.settings()
        self.assertEqual(data["permissions"], original["permissions"])
        self.assertEqual(data["model"], "opus")
        self.assertEqual(data["hooks"]["PreToolUse"], [OTHER_TOOL])
        expected = user_entries()
        self.assertEqual(data["hooks"]["PostToolUse"], [OTHER_TOOL, *expected["PostToolUse"]])
        self.assertEqual(data["hooks"]["PostToolUseFailure"], expected["PostToolUseFailure"])

    def test_user_settings_are_created_when_missing(self):
        self.assertFalse((self.config / "settings.json").exists())
        self.assertEqual(self.sync_user().returncode, 0)
        self.assertEqual(self.settings(), {"hooks": user_entries()})

    def test_invalid_user_settings_exit_1_and_nothing_is_written(self):
        self.write_settings("{ not json")
        result = self.sync_user()
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(self.config / "settings.json"), result.stderr)
        self.assertEqual((self.config / "settings.json").read_text(), "{ not json")
        self.assertEqual(sorted(p.name for p in self.config.iterdir()), ["settings.json"])

    def test_config_dir_from_the_flag_the_variable_or_home(self):
        flag, variable = self.tmp / "x", self.tmp / "y"
        self.assertEqual(self.sync_user("v0.1.0", "--config-dir", str(flag)).returncode, 0)
        self.assertTrue((flag / "harness" / "hooks" / "card-check").is_file())
        self.assertTrue((flag / "skills" / "cdv-notion-ticket" / "SKILL.md").is_file())
        self.assertEqual(json.loads((flag / "settings.json").read_text()), {"hooks": user_entries()})
        self.assertFalse(self.config.exists())
        env = dict(self.env, CLAUDE_CONFIG_DIR=str(variable))
        self.assertEqual(self.sync_user(env=env).returncode, 0)
        self.assertTrue((variable / "harness-user.lock").is_file())
        self.assertTrue((variable / "harness" / "hooks" / "card-check").is_file())
        self.assertFalse(self.config.exists())
        self.assertEqual(self.sync_user().returncode, 0)
        self.assertTrue((self.config / "harness" / "hooks" / "card-check").is_file())
        self.assertTrue((self.config / "settings.json").is_file())

    def test_a_dropped_hook_is_removed_and_nothing_else_changes(self):
        original = {"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {"PostToolUse": [OTHER_TOOL]}, "env": {"A": "1"}}
        self.write_settings(original)
        self.assertEqual(self.sync_user().returncode, 0)
        doc = json.loads((REPO_ROOT / "settings" / "hooks-core.json").read_text())
        smaller = {"PreToolUse": doc["PreToolUse"]}
        self.commit_core(self.core, {"settings/hooks-core.json": json.dumps(smaller, indent=2) + "\n"},
                         remove=["hooks/card-check"], message="feat: drop the card hook", tag="v0.2.0")
        result = self.sync_user("v0.2.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.settings(), original)
        self.assertFalse((self.config / "harness").exists())
        lock = json.loads((self.config / "harness-user.lock").read_text())
        self.assertEqual(lock["hooks_by_event"], {"PostToolUse": [], "PostToolUseFailure": []})
        self.assertNotIn("harness/hooks", lock["paths"])
        self.assertTrue((self.config / "skills" / "cdv-notion-ticket").is_dir())


class UserSkillsListTest(unittest.TestCase):
    def test_user_skills_name_cdv_notion_and_its_client_is_executable(self):
        self.assertIn("cdv-notion", load_tool().USER_SKILLS)
        listed = subprocess.run(
            ["git", "ls-files", "-s", NOTION_CLIENT], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.split()
        self.assertEqual(listed[:1], ["100755"])
        self.assertTrue(os.access(REPO_ROOT / NOTION_CLIENT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
