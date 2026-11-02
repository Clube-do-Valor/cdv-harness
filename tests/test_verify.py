import shutil
import unittest

from helpers import HarnessTestCase


class VerifyTest(HarnessTestCase):
    def synced(self):
        core = self.make_core()
        repo = self.make_consumer()
        self.sync(repo, core, "v0.1.0")
        self.commit_all(repo)
        return core, repo

    def test_exit_0_after_sync(self):
        _core, repo = self.synced()
        result = self.verify(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "harness: vendored core matches v0.1.0")

    def test_exit_1_lists_changed_created_and_deleted_files(self):
        _core, repo = self.synced()
        (repo / ".claude/skills/cdv-debug/SKILL.md").write_text("edited\n")
        (repo / ".claude/skills/cdv-debug/references/new.md").write_text("new\n")
        (repo / ".claude/rules/core/legacy.md").unlink()
        result = self.verify(repo)
        self.assertEqual(result.returncode, 1)
        lines = result.stdout.splitlines()
        self.assertIn("changed: .claude/skills/cdv-debug/SKILL.md", lines)
        self.assertIn("created: .claude/skills/cdv-debug/references/new.md", lines)
        self.assertIn("deleted: .claude/rules/core/legacy.md", lines)
        self.assertEqual(len([line for line in lines if line.split(":")[0] in ("changed", "created", "deleted")]), 3)
        self.assertRegex(result.stdout, r"tree_sha256: recomputed [0-9a-f]{64}, locked [0-9a-f]{64}")

    def test_files_outside_the_locked_paths_are_ignored(self):
        _core, repo = self.synced()
        (repo / ".claude/skills/own-skill").mkdir()
        (repo / ".claude/skills/own-skill/SKILL.md").write_text("mine\n")
        (repo / ".claude/rules/mine.md").write_text("mine\n")
        self.assertEqual(self.verify(repo).returncode, 0)

    def test_exit_2_without_a_lock(self):
        repo = self.make_consumer()
        result = self.verify(repo)
        self.assertEqual(result.returncode, 2)
        self.assertIn("lock not found", result.stderr)

    def test_exit_2_with_a_garbage_lock(self):
        repo = self.make_consumer()
        (repo / ".claude/harness.lock").write_text("this is not a lock\n")
        result = self.verify(repo)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a schema 1 lock", result.stderr)

    def test_exit_2_when_the_lock_lacks_files_or_paths(self):
        repo = self.make_consumer()
        (repo / ".claude/harness.lock").write_text('{\n  "schema": 1,\n  "paths": [\n  ]\n}\n')
        self.assertEqual(self.verify(repo).returncode, 2)
        (repo / ".claude/harness.lock").write_text('{\n  "schema": 2,\n  "paths": [\n  ],\n  "files": {\n  }\n}\n')
        self.assertEqual(self.verify(repo).returncode, 2)

    def test_unknown_argument_is_a_usage_error(self):
        repo = self.make_consumer()
        self.assertEqual(self.verify(repo, "--nope").returncode, 2)

    def test_skip_trailer_with_a_reason_passes(self):
        _core, repo = self.synced()
        base = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / ".claude/skills/cdv-debug/SKILL.md").write_text("edited\n")
        self.git(repo, "commit", "-q", "-am", "fix: tweak\n\nHarness-skip: urgent hotfix, proposed upstream later")
        result = self.verify(repo, "--skip-trailer-range", f"{base}..HEAD")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("harness: skipped by trailer: urgent hotfix, proposed upstream later", result.stdout)

    def test_skip_trailer_without_a_reason_or_absent_still_fails(self):
        _core, repo = self.synced()
        base = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / ".claude/skills/cdv-debug/SKILL.md").write_text("edited\n")
        self.git(repo, "commit", "-q", "-am", "fix: tweak\n\nHarness-skip:   ")
        empty = self.verify(repo, "--skip-trailer-range", f"{base}..HEAD")
        self.assertEqual(empty.returncode, 1)
        self.git(repo, "commit", "-q", "--allow-empty", "-m", "chore: unrelated")
        absent = self.verify(repo, "--skip-trailer-range", f"{base}..HEAD")
        self.assertEqual(absent.returncode, 1)
        self.assertNotIn("skipped by trailer", absent.stdout)

    def test_skip_trailer_is_not_consulted_when_everything_matches(self):
        _core, repo = self.synced()
        result = self.verify(repo, "--skip-trailer-range", "no-such-ref..HEAD")
        self.assertEqual(result.returncode, 0)
        self.assertIn("matches v0.1.0", result.stdout)

    def test_runs_under_dash_and_sh_and_via_the_subcommand(self):
        _core, repo = self.synced()
        for shell in {shutil.which("dash") or "sh", "sh"}:
            with self.subTest(shell=shell):
                self.assertEqual(self.verify(repo, shell=shell).returncode, 0)
        result = self.harness("verify", "--repo", str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("matches v0.1.0", result.stdout)
        (repo / ".claude/rules/core/testing.md").write_text("edited\n")
        self.assertEqual(self.harness("verify", "--repo", str(repo)).returncode, 1)

    def test_verify_subcommand_falls_back_to_the_core_script(self):
        repo = self.make_consumer()
        result = self.harness("verify", "--repo", str(repo))
        self.assertEqual(result.returncode, 2)
        self.assertIn("lock not found", result.stderr)

    def test_a_tampered_lock_files_section_is_caught_by_the_tree_hash(self):
        _core, repo = self.synced()
        lock = repo / ".claude/harness.lock"
        text = lock.read_text()
        lock.write_text(text.replace('"tree_sha256": "', '"tree_sha256": "0'))
        result = self.verify(repo)
        self.assertEqual(result.returncode, 1)
        self.assertIn("tree_sha256: recomputed", result.stdout)


if __name__ == "__main__":
    unittest.main()
