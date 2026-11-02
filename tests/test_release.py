import unittest

from helpers import HarnessTestCase


class ReleaseTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.core = self.make_core(with_remote=True)

    def release(self, *extra, now="2026-03-01", consumers=None):
        args = ["release", "--core", str(self.core), "--now", now]
        if consumers is not None:
            args += ["--consumers", str(consumers)]
        return self.harness(*args, *extra)

    def commit(self, subject, name="change.txt"):
        self.commit_core(self.core, {name: subject + "\n"}, message=subject)

    def tags(self):
        return set(self.git(self.core, "tag", "--list").stdout.split())

    def remote_tags(self):
        return set(self.git(self.core_remote, "tag", "--list").stdout.split())

    def test_no_change_since_the_last_tag_creates_no_tag(self):
        result = self.release("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "no change on main since v0.1.0")
        result = self.release()
        self.assertIn("no change on main since v0.1.0", result.stdout)
        self.assertEqual(self.tags(), {"v0.1.0"})

    def test_change_but_tag_younger_than_seven_days_creates_no_tag(self):
        self.commit("fix: a bug")
        result = self.release(now="2026-01-05")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "last tag v0.1.0 is younger than 7 days")
        self.assertEqual(self.tags(), {"v0.1.0"})
        old_enough = self.release("--dry-run", now="2026-01-09")
        self.assertIn("next version: v0.1.1", old_enough.stdout)

    def test_fix_only_is_a_patch_and_the_tag_is_pushed(self):
        self.commit("fix: one bug")
        self.commit("docs: a note", name="other.txt")
        result = self.release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tags(), {"v0.1.0", "v0.1.1"})
        self.assertEqual(self.remote_tags(), {"v0.1.0", "v0.1.1"})
        self.assertEqual(self.git(self.core, "cat-file", "-t", "v0.1.1").stdout.strip(), "tag")
        self.assertEqual(
            self.git(self.core, "rev-parse", "v0.1.1^{commit}").stdout, self.git(self.core, "rev-parse", "main").stdout
        )

    def test_a_private_git_identity_creates_no_tag(self):
        self.commit("fix: one bug")
        private = self.home / ".config" / "cdv-harness" / "private-patterns.txt"
        private.parent.mkdir(parents=True)
        private.write_text("SecretCorp\n")
        env = dict(self.env, GIT_COMMITTER_NAME="SecretCorp Dev")
        result = self.harness("release", "--core", str(self.core), "--now", "2026-03-01", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("git identity", result.stdout + result.stderr)
        self.assertEqual(self.tags(), {"v0.1.0"})
        self.assertEqual(self.remote_tags(), {"v0.1.0"})

    def test_a_feat_is_a_minor(self):
        self.commit("fix: one bug")
        self.commit("feat(skills): a new thing", name="other.txt")
        result = self.release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("v0.2.0", self.tags())
        self.assertIn("v0.2.0", self.remote_tags())

    def test_a_breaking_feat_with_a_scope_is_a_minor(self):
        self.commit("feat(api)!: change the thing")
        self.assertIn("next version: v0.2.0", self.release("--dry-run").stdout)

    def test_a_subject_that_only_mentions_feat_is_a_patch(self):
        self.commit("docs: describe the feat: convention")
        self.assertIn("next version: v0.1.1", self.release("--dry-run").stdout)

    def test_versions_are_ordered_numerically(self):
        self.git(self.core, "tag", "-a", "v0.10.0", "-m", "v0.10.0", env=dict(self.env, GIT_COMMITTER_DATE="2026-01-01T12:00:00 +0000"))
        self.git(self.core, "tag", "-a", "v0.9.0", "-m", "v0.9.0", env=dict(self.env, GIT_COMMITTER_DATE="2026-01-01T12:00:00 +0000"))
        self.commit("fix: one bug")
        self.assertIn("next version: v0.10.1", self.release("--dry-run").stdout)

    def test_dry_run_creates_nothing(self):
        self.commit("feat: something")
        result = self.release("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("next version: v0.2.0", result.stdout)
        self.assertEqual(self.tags(), {"v0.1.0"})
        self.assertEqual(self.remote_tags(), {"v0.1.0"})

    def test_consumers_get_their_sync_branch_pushed_and_a_pr_opened(self):
        gh = self.make_cli("gh")
        first = self.make_consumer("first", pr_cli=gh)
        second = self.make_consumer("second", pr_cli=gh)
        self.sync(first, self.core, "v0.1.0")
        self.commit_all(first)
        self.git(first, "push", "-q", "origin", "main")
        listing = self.tmp / "consumers.yaml"
        listing.write_text(f"consumers:\n  - {first}\n  - '{second}'\n")
        self.commit("feat: something new")
        result = self.release(consumers=listing)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ("first", "second"):
            remote = self.tmp / f"{name}-remote.git"
            self.assertIn("chore/harness-sync-v0.2.0", self.git(remote, "branch", "--list").stdout)
        calls = self.cli_calls("gh")
        self.assertEqual(len(calls), 2)
        for argv in calls:
            self.assertEqual(argv[argv.index("--title") + 1], "chore(harness): sync core v0.2.0")
            self.assertEqual(argv[argv.index("--head") + 1], "chore/harness-sync-v0.2.0")
        lock = self.git(first, "show", "chore/harness-sync-v0.2.0:.claude/harness.lock").stdout
        self.assertIn('"ref": "v0.2.0"', lock)
        self.assertEqual(self.git(first, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), "main")

    def test_missing_consumers_file_tags_only_with_a_warning(self):
        self.commit("fix: one bug")
        result = self.release(consumers=self.tmp / "absent.yaml")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning", result.stderr)
        self.assertIn("v0.1.1", self.tags())

    def test_default_consumers_file_lives_under_home(self):
        gh = self.make_cli("gh")
        repo = self.make_consumer("only", pr_cli=gh)
        config = self.home / ".config" / "cdv-harness"
        config.mkdir(parents=True)
        (config / "consumers.yaml").write_text(f"consumers:\n  - {repo}\n")
        self.commit("fix: one bug")
        result = self.release()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.cli_calls("gh")), 1)

    def test_a_failing_consumer_is_reported_and_the_others_continue(self):
        gh = self.make_cli("gh")
        good = self.make_consumer("good", pr_cli=gh)
        listing = self.tmp / "consumers.yaml"
        listing.write_text(f"consumers:\n  - {self.tmp / 'missing-repo'}\n  - {good}\n")
        self.commit("fix: one bug")
        result = self.release(consumers=listing)
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing-repo", result.stderr)
        self.assertEqual(len(self.cli_calls("gh")), 1)

    def test_first_release_when_there_is_no_tag(self):
        core = self.tmp / "fresh"
        core.mkdir()
        self.git(core, "init", "-q", "-b", "main")
        self.commit_core(core, {"a.txt": "a\n"}, message="feat: start")
        result = self.harness("release", "--core", str(core), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("next version: v0.1.0", result.stdout)


if __name__ == "__main__":
    unittest.main()
