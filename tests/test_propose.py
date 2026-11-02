import unittest

from helpers import HOUSE_V1, HarnessTestCase

TITLE = "chore(harness): propose changes from a consumer repository"


class ProposeTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.core = self.make_core(with_remote=True)
        self.consumer = self.make_consumer(app_dir="src")
        self.sync(self.consumer, self.core, "v0.1.0")
        self.commit_all(self.consumer)
        self.gh = self.make_cli("gh-propose")
        self.private = self.home / ".config" / "cdv-harness" / "private-patterns.txt"
        self.private.parent.mkdir(parents=True)
        self.private.write_text("# private\nSecretCorp\n")

    def branch(self, date="20260115"):
        names = self.git(self.core, "branch", "--list", f"propose/{date}-*", "--format=%(refname:short)").stdout.split()
        self.assertEqual(len(names), 1, names)
        self.assertRegex(names[0], rf"^propose/{date}-[0-9a-f]{{8}}$")
        return names[0]

    def propose(self, *extra, check=False):
        env = dict(self.env, HARNESS_GH=str(self.gh))
        return self.harness(
            "propose", "--from", str(self.core), "--repo", str(self.consumer), "--date", "20260115", *extra,
            env=env, check=check,
        )

    def core_show(self, ref, path):
        return self.git(self.core, "show", f"{ref}:{path}").stdout

    def test_edit_in_a_skill_lands_at_the_core_path(self):
        skill = self.consumer / ".claude/skills/cdv-debug/SKILL.md"
        skill.write_text(skill.read_text() + "A local improvement.\n")
        result = self.propose("--no-pr")
        self.assertEqual(result.returncode, 0, result.stderr)
        branch = self.branch()
        self.assertIn("A local improvement.", self.core_show(branch, "skills/cdv-debug/SKILL.md"))
        subject = self.git(self.core, "log", "-1", "--format=%s", branch).stdout.strip()
        self.assertEqual(subject, TITLE)
        base = self.git(self.core, "rev-parse", "v0.1.0^{commit}").stdout.strip()
        self.assertEqual(self.git(self.core, "rev-parse", f"{branch}~1").stdout.strip(), base)
        self.assertEqual(self.git(self.core, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), "main")
        self.assertEqual(self.status(self.core), "")
        self.assertEqual(self.cli_calls("gh-propose"), [])

    def test_rule_edit_gets_app_dir_restored(self):
        rule = self.consumer / ".claude/rules/core/testing.md"
        text = rule.read_text()
        self.assertIn('  - "src/app/**"', text)
        rule.write_text(text.replace("  - docs/**\n", "  - docs/**\n  - src/resources/**\n") + "\nSee also `src/app` is special.\n")
        self.propose("--no-pr")
        proposed = self.core_show(self.branch(), "rules/core/testing.md")
        self.assertIn('  - "{app_dir}/app/**"', proposed)
        self.assertIn("  - {app_dir}/resources/**", proposed)
        self.assertIn("  - docs/**", proposed)
        self.assertIn("Work from `{app_dir}/` when editing", proposed)
        self.assertIn("See also `src/app` is special.", proposed)
        self.assertNotIn('"src/app/**"', proposed)

    def test_rule_edit_with_app_dir_at_the_root_restores_the_original_lines(self):
        root = self.make_consumer("at-root", app_dir=".")
        self.sync(root, self.core, "v0.1.0")
        self.commit_all(root)
        rule = root / ".claude/rules/core/testing.md"
        rule.write_text(rule.read_text() + "More.\n")
        env = dict(self.env, HARNESS_GH=str(self.gh))
        result = self.harness(
            "propose", "--from", str(self.core), "--repo", str(root), "--date", "20260116", "--no-pr", env=env
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        proposed = self.core_show(self.branch("20260116"), "rules/core/testing.md")
        self.assertIn('  - "{app_dir}/app/**"', proposed)
        self.assertIn("`{app_dir}/`", proposed)
        self.assertTrue(proposed.endswith("More.\n"))

    def test_house_block_edit_lands_in_instructions_house(self):
        text = (self.consumer / "CLAUDE.md").read_text()
        self.assertIn("Keep changes small.", text)
        (self.consumer / "CLAUDE.md").write_text(text.replace("Keep changes small.", "Keep changes tiny."))
        self.propose("--no-pr")
        self.assertEqual(
            self.core_show(self.branch(), "instructions/house.md"), HOUSE_V1.replace("small", "tiny")
        )
        changed = self.git(self.core, "show", "--name-only", "--format=", self.branch()).stdout.split()
        self.assertEqual(changed, ["instructions/house.md"])

    def test_edits_outside_the_house_block_do_not_count(self):
        (self.consumer / "CLAUDE.md").write_text("Preface.\n\n" + (self.consumer / "CLAUDE.md").read_text())
        result = self.propose("--no-pr")
        self.assertIn("nothing to propose", result.stdout)

    def test_created_and_deleted_files_are_proposed(self):
        (self.consumer / ".claude/skills/cdv-debug/references/added.md").write_text("added\n")
        (self.consumer / ".claude/rules/core/legacy.md").unlink()
        self.propose("--no-pr")
        branch = self.branch()
        self.assertEqual(self.core_show(branch, "skills/cdv-debug/references/added.md"), "added\n")
        status = self.git(self.core, "show", "--name-status", "--format=", branch).stdout
        self.assertIn("D\trules/core/legacy.md", status)
        self.assertIn("A\tskills/cdv-debug/references/added.md", status)

    def test_verify_script_edit_keeps_its_exec_bit(self):
        script = self.consumer / ".claude/harness/bin/verify.sh"
        script.write_text(script.read_text() + "\n# local note\n")
        self.propose("--no-pr")
        listing = self.git(self.core, "ls-tree", self.branch(), "bin/verify.sh").stdout
        self.assertTrue(listing.startswith("100755"), listing)
        self.assertIn("# local note", self.core_show(self.branch(), "bin/verify.sh"))

    def test_nothing_diverged_creates_no_branch(self):
        result = self.propose()
        self.assertEqual(result.returncode, 0)
        self.assertIn("nothing to propose", result.stdout)
        self.assertEqual(self.git(self.core, "branch", "--list", "propose/*").stdout.strip(), "")
        self.assertEqual(self.cli_calls("gh-propose"), [])

    def test_push_and_pr_with_gh_override(self):
        skill = self.consumer / ".claude/skills/cdv-debug/SKILL.md"
        skill.write_text(skill.read_text() + "Shared improvement.\n")
        result = self.propose()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(self.branch(), self.git(self.core_remote, "branch", "--list").stdout)
        argv = self.cli_calls("gh-propose")[0]
        self.assertEqual(argv[:2], ["pr", "create"])
        self.assertEqual(argv[argv.index("--base") + 1], "main")
        self.assertEqual(argv[argv.index("--head") + 1], self.branch())
        self.assertEqual(argv[argv.index("--title") + 1], TITLE)
        self.assertNotIn("`app`", (self.bin_dir / "gh-propose.log.body").read_text())
        self.assertIn("skills/cdv-debug/SKILL.md", (self.bin_dir / "gh-propose.log.body").read_text())

    def test_from_is_required(self):
        result = self.harness("propose", "--repo", str(self.consumer))
        self.assertEqual(result.returncode, 2)
        self.assertIn("--from", result.stderr)

    def test_dirty_core_checkout_is_refused(self):
        skill = self.consumer / ".claude/skills/cdv-debug/SKILL.md"
        skill.write_text(skill.read_text() + "x\n")
        (self.core / "bin/verify.sh").write_text("dirty\n")
        result = self.propose("--no-pr")
        self.assertEqual(result.returncode, 1)
        self.assertIn("uncommitted changes", result.stderr)

    def assert_nothing_proposed(self):
        self.assertEqual(self.git(self.core, "branch", "--list", "propose/*").stdout.strip(), "")
        self.assertEqual(self.git(self.core, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), "main")
        self.assertEqual(self.status(self.core), "")
        self.assertEqual(self.cli_calls("gh-propose"), [])

    def test_a_private_pattern_in_a_proposed_file_refuses_everything(self):
        patterns = self.tmp / "other-patterns.txt"
        patterns.write_text("OtherCorp\n")
        skill = self.consumer / ".claude/skills/cdv-debug/SKILL.md"
        skill.write_text(skill.read_text() + "Ask OtherCorp ops.\n")
        result = self.propose("--extra-patterns", str(patterns))
        self.assertEqual(result.returncode, 1)
        self.assertIn("skills/cdv-debug/SKILL.md:", result.stdout)
        self.assertIn("OtherCorp", result.stdout)
        self.assertIn("nothing was proposed", result.stderr)
        self.assert_nothing_proposed()

    def test_private_patterns_default_to_the_machine_file(self):
        rule = self.consumer / ".claude/rules/core/testing.md"
        rule.write_text(rule.read_text() + "SecretCorp only.\n")
        result = self.propose("--no-pr")
        self.assertEqual(result.returncode, 1)
        self.assertIn("rules/core/testing.md:", result.stdout)
        self.assert_nothing_proposed()

    def test_a_private_name_in_a_new_file_path_is_refused(self):
        (self.consumer / ".claude/skills/cdv-debug/references/secretcorp-SecretCorp.md").write_text("plain\n")
        result = self.propose("--no-pr")
        self.assertEqual(result.returncode, 1)
        self.assertIn("secretcorp-SecretCorp.md:0:", result.stdout)
        self.assert_nothing_proposed()

    def test_without_private_patterns_it_refuses(self):
        self.private.unlink()
        skill = self.consumer / ".claude/skills/cdv-debug/SKILL.md"
        skill.write_text(skill.read_text() + "Plain improvement.\n")
        result = self.propose("--no-pr")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no private scan patterns", result.stderr)
        self.assert_nothing_proposed()

    def test_public_patterns_only_is_an_explicit_choice(self):
        self.private.unlink()
        skill = self.consumer / ".claude/skills/cdv-debug/SKILL.md"
        skill.write_text(skill.read_text() + "Plain improvement.\n")
        result = self.propose("--no-pr", "--public-patterns-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Plain improvement.", self.core_show(self.branch(), "skills/cdv-debug/SKILL.md"))

    def test_a_private_git_identity_is_refused(self):
        skill = self.consumer / ".claude/skills/cdv-debug/SKILL.md"
        skill.write_text(skill.read_text() + "Plain improvement.\n")
        env = dict(self.env, HARNESS_GH=str(self.gh), GIT_AUTHOR_NAME="SecretCorp Dev",
                   GIT_COMMITTER_NAME="SecretCorp Dev")
        result = self.harness(
            "propose", "--from", str(self.core), "--repo", str(self.consumer), "--date", "20260115", "--no-pr",
            env=env,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("git identity", result.stdout + result.stderr)
        self.assert_nothing_proposed()

    def test_two_proposals_from_one_repository_do_not_share_a_label(self):
        skill = self.consumer / ".claude/skills/cdv-debug/SKILL.md"
        skill.write_text(skill.read_text() + "One.\n")
        self.propose("--no-pr")
        first = self.branch()
        self.git(self.core, "branch", "-q", "-D", first)
        self.propose("--no-pr")
        self.assertNotEqual(self.branch(), first)

if __name__ == "__main__":
    unittest.main()
