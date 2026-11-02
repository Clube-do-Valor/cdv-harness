import json
import os
import unittest

from helpers import HarnessTestCase, sha256_file

SKILLS = ["cdv-grilling", "cdv-grill-me", "cdv-research-round"]


class SyncUserTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.core = self.make_core()
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
        self.assertEqual(lock["paths"], sorted(f".claude/skills/{n}" for n in SKILLS))
        self.assertEqual(sorted(lock["files"]), sorted(f".claude/skills/{n}/SKILL.md" for n in SKILLS))
        for path, digest in lock["files"].items():
            self.assertEqual(sha256_file(self.home / path), digest)
        self.assertEqual(lock["commit"], self.git(self.core, "rev-parse", "v0.1.0^{commit}").stdout.strip())

    def test_executable_bit_is_preserved(self):
        self.commit_core(
            self.core, {"skills/cdv-grilling/scripts/go.sh": ("#!/bin/sh\n", True)}, message="feat: script", tag="v0.2.0"
        )
        self.sync_user("v0.2.0")
        self.assertTrue(os.access(self.skills / "cdv-grilling/scripts/go.sh", os.X_OK))

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


if __name__ == "__main__":
    unittest.main()
