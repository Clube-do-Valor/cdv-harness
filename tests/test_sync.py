import json
import os
import re
import unittest
from pathlib import Path

from helpers import (
    DENY_V1,
    DENY_V2,
    HOUSE_V1,
    HOUSE_V2,
    HarnessTestCase,
    is_executable,
    sha256_file,
)


class SyncTest(HarnessTestCase):
    def test_sync_into_a_fresh_consumer(self):
        core = self.make_core()
        repo = self.make_consumer()
        result = self.sync(repo, core, "v0.1.0")
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertTrue((repo / ".claude/skills/cdv-debug/SKILL.md").is_file())
        self.assertTrue((repo / ".claude/skills/cdv-debug/references/notes.md").is_file())
        self.assertTrue(is_executable(repo / ".claude/skills/cdv-debug/scripts/run.sh"))
        self.assertFalse(is_executable(repo / ".claude/skills/cdv-debug/SKILL.md"))
        self.assertTrue(is_executable(repo / ".claude/harness/bin/verify.sh"))
        self.assertTrue((repo / ".claude/rules/core/testing.md").is_file())
        settings = json.loads((repo / ".claude/settings.json").read_text())
        self.assertEqual(settings["permissions"]["deny"], DENY_V1)
        instructions = (repo / "CLAUDE.md").read_text()
        self.assertIn("Own instructions.", instructions)
        self.assertIn("<!-- cdv-harness:house v0.1.0 -->\n" + HOUSE_V1 + "<!-- /cdv-harness:house -->\n", instructions)
        self.assertIn("Own instructions.\n\n<!-- cdv-harness:house", instructions)

    def test_content_comes_from_the_tag_not_the_working_tree(self):
        core = self.make_core()
        (core / "instructions/house.md").write_text("uncommitted edit\n")
        (core / "skills/cdv-debug/SKILL.md").write_text("uncommitted edit\n")
        repo = self.make_consumer()
        self.sync(repo, core, "v0.1.0")
        self.assertNotIn("uncommitted", (repo / "CLAUDE.md").read_text())
        self.assertNotIn("uncommitted", (repo / ".claude/skills/cdv-debug/SKILL.md").read_text())

    def test_unknown_tag_is_an_error_and_touches_nothing(self):
        core = self.make_core()
        repo = self.make_consumer()
        result = self.sync(repo, core, "v9.9.9", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown ref", result.stderr)
        self.assertEqual(self.status(repo), "")

    def test_second_run_changes_nothing(self):
        core = self.make_core()
        repo = self.make_consumer()
        self.sync(repo, core, "v0.1.0")
        self.commit_all(repo)
        again = self.sync(repo, core, "v0.1.0")
        self.assertEqual(again.returncode, 0)
        self.assertIn("already at v0.1.0", again.stdout)
        self.assertEqual(self.status(repo), "")

    def test_missing_profile_exits_2(self):
        core = self.make_core()
        repo = self.make_consumer()
        (repo / ".claude/harness/profile.yaml").unlink()
        result = self.sync(repo, core, "v0.1.0", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("profile not found:", result.stderr)

    def test_nested_mapping_in_profile_is_an_error_naming_the_line(self):
        core = self.make_core()
        repo = self.make_consumer()
        profile = repo / ".claude/harness/profile.yaml"
        profile.write_text(profile.read_text() + "nested:\n  inner: value\n")
        result = self.sync(repo, core, "v0.1.0", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("nested mapping", result.stderr)
        self.assertRegex(result.stderr, r"profile\.yaml:\d+:")

    def test_unsupported_profile_syntax_is_rejected(self):
        tool = __import__("helpers").load_tool()
        for text, needle in [
            ("key: {a: 1}\n", "flow style"),
            ("key: [a, b]\n", "flow style"),
            ("key: &anchor value\n", "anchors"),
            ("key: *alias\n", "anchors"),
            ("a: 1\n---\nb: 2\n", "multiple documents"),
            ("key:\tvalue\n", "tab"),
            ("- orphan\n", "without a `key:`"),
            ("key: a\nkey: b\n", "duplicate key"),
            ("key: text: more\n", "quote it"),
        ]:
            with self.subTest(text=text):
                with self.assertRaises(tool.HarnessError) as ctx:
                    tool.parse_profile_text(text, "profile.yaml")
                self.assertIn(needle, str(ctx.exception))
                self.assertEqual(ctx.exception.code, 2)

    def test_supported_profile_syntax(self):
        tool = __import__("helpers").load_tool()
        parsed = tool.parse_profile_text(
            "# comment\n\na: bare\nb: 'single'\nc: \"dou: ble\"\nd: true\ne: 12\nf: x # note\nlist:\n  - one\n  - 'two'\nempty:\n",
            "profile.yaml",
        )
        self.assertEqual(
            parsed,
            {"a": "bare", "b": "single", "c": "dou: ble", "d": True, "e": "12", "f": "x", "list": ["one", "two"], "empty": None},
        )

    def test_local_profile_overrides_key_by_key(self):
        core = self.make_core()
        repo = self.make_consumer()
        (repo / ".claude/harness/profile.local.yaml").write_text("app_dir: web\n")
        self.sync(repo, core, "v0.1.0")
        self.assertIn("web/app/**", (repo / ".claude/rules/core/testing.md").read_text())

    def test_missing_required_key_and_bad_enum_are_errors_unknown_key_is_a_warning(self):
        core = self.make_core()
        repo = self.make_consumer(vcs_host="svn")
        profile = repo / ".claude/harness/profile.yaml"
        profile.write_text(re.sub(r"^repo_name:.*\n", "", profile.read_text(), flags=re.M) + "surprise: 1\n")
        result = self.sync(repo, core, "v0.1.0", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("required key 'repo_name'", result.stderr)
        self.assertIn("'vcs_host' must be one of", result.stderr)
        self.assertIn("unknown key 'surprise'", result.stderr)

    def test_app_dir_is_rewritten_in_rules(self):
        core = self.make_core()
        src = self.make_consumer("with-src", app_dir="src")
        self.sync(src, core, "v0.1.0")
        text = (src / ".claude/rules/core/testing.md").read_text()
        self.assertIn('  - "src/app/**"', text)
        self.assertIn("Work from `src/` when editing", text)
        self.assertNotIn("{app_dir}", text)

        root = self.make_consumer("at-root", app_dir=".")
        self.sync(root, core, "v0.1.0")
        text = (root / ".claude/rules/core/testing.md").read_text()
        self.assertIn('  - "app/**"', text)
        self.assertIn("Work from `` when editing", text)
        self.assertNotIn("{app_dir}", text)
        self.assertEqual((root / ".claude/rules/core/legacy.md").read_text(), "---\npaths:\n  - docs/**\n---\n\nLegacy rule.\n")

    def test_deny_is_merged_without_duplicates_and_keeps_consumer_entries(self):
        core = self.make_core()
        repo = self.make_consumer()
        (repo / ".claude/settings.json").write_text(
            json.dumps(
                {
                    "env": {"A": "1"},
                    "permissions": {"allow": ["Bash(ls)"], "deny": ["Bash(own)", DENY_V1[0]]},
                    "model": "x",
                }
            )
        )
        self.sync(repo, core, "v0.1.0")
        raw = (repo / ".claude/settings.json").read_text()
        self.assertTrue(raw.endswith("}\n"))
        self.assertIn('\n  "env": {', raw)
        settings = json.loads(raw)
        self.assertEqual(settings["env"], {"A": "1"})
        self.assertEqual(settings["model"], "x")
        self.assertEqual(settings["permissions"]["allow"], ["Bash(ls)"])
        self.assertEqual(settings["permissions"]["deny"], ["Bash(own)", DENY_V1[0], DENY_V1[1]])

    def test_deny_entries_dropped_by_a_newer_core_are_removed_and_own_ones_stay(self):
        core = self.make_core()
        self.add_v2(core)
        repo = self.make_consumer()
        (repo / ".claude/settings.json").write_text(json.dumps({"permissions": {"deny": ["Bash(own)"]}}))
        self.sync(repo, core, "v0.1.0")
        self.sync(repo, core, "v0.2.0")
        deny = json.loads((repo / ".claude/settings.json").read_text())["permissions"]["deny"]
        self.assertEqual(deny, ["Bash(own)", *DENY_V2])
        self.assertNotIn("Edit(.env)", deny)
        self.assertEqual(self.read_lock(repo)["deny"], DENY_V2)

    def test_deny_created_when_settings_file_is_absent(self):
        core = self.make_core()
        repo = self.make_consumer()
        self.assertFalse((repo / ".claude/settings.json").exists())
        self.sync(repo, core, "v0.1.0")
        self.assertEqual(
            json.loads((repo / ".claude/settings.json").read_text()), {"permissions": {"deny": DENY_V1}}
        )

    def test_invalid_settings_json_stops_before_writing(self):
        core = self.make_core()
        repo = self.make_consumer()
        (repo / ".claude/settings.json").write_text("{not json")
        result = self.sync(repo, core, "v0.1.0", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("settings.json is not valid JSON", result.stderr)
        self.assertFalse((repo / ".claude/skills").exists())

    def test_house_block_is_replaced_not_duplicated_on_a_new_tag(self):
        core = self.make_core()
        self.add_v2(core)
        repo = self.make_consumer()
        self.sync(repo, core, "v0.1.0")
        (repo / "CLAUDE.md").write_text("intro\n\n" + (repo / "CLAUDE.md").read_text() + "\nTrailing notes.\n")
        self.sync(repo, core, "v0.2.0")
        text = (repo / "CLAUDE.md").read_text()
        self.assertEqual(text.count("<!-- cdv-harness:house"), 1)
        self.assertEqual(text.count("<!-- /cdv-harness:house -->"), 1)
        self.assertIn("<!-- cdv-harness:house v0.2.0 -->\n" + HOUSE_V2, text)
        self.assertNotIn("v0.1.0", text)
        self.assertTrue(text.startswith("intro\n"))
        self.assertTrue(text.endswith("\nTrailing notes.\n"))
        self.assertIn("Own instructions.", text)

    def test_house_block_is_created_with_the_instructions_file_when_absent(self):
        core = self.make_core()
        repo = self.make_consumer()
        (repo / "CLAUDE.md").unlink()
        self.sync(repo, core, "v0.1.0")
        self.assertEqual(
            (repo / "CLAUDE.md").read_text(), "<!-- cdv-harness:house v0.1.0 -->\n" + HOUSE_V1 + "<!-- /cdv-harness:house -->\n"
        )

    def test_symlinked_instructions_file_is_refused(self):
        core = self.make_core()
        repo = self.make_consumer()
        (repo / "CLAUDE.md").unlink()
        (repo / "REAL.md").write_text("real\n")
        os.symlink("REAL.md", repo / "CLAUDE.md")
        result = self.sync(repo, core, "v0.1.0", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink", result.stderr)
        self.assertEqual((repo / "REAL.md").read_text(), "real\n")
        self.assertFalse((repo / ".claude/skills").exists())

    def test_files_dropped_by_a_newer_tag_are_deleted_and_empty_dirs_pruned(self):
        core = self.make_core()
        self.add_v2(core)
        repo = self.make_consumer()
        self.sync(repo, core, "v0.1.0")
        self.commit_all(repo)
        self.assertTrue((repo / ".claude/skills/cdv-debug/references/notes.md").exists())
        self.sync(repo, core, "v0.2.0")
        self.assertFalse((repo / ".claude/skills/cdv-debug/references/notes.md").exists())
        self.assertFalse((repo / ".claude/rules/core/legacy.md").exists())
        self.assertTrue((repo / ".claude/skills/cdv-debug/references/extra.md").exists())
        staged = self.git(repo, "diff", "--cached", "--name-status").stdout
        self.assertRegex(staged, r"D\t\.claude/rules/core/legacy\.md")
        self.assertRegex(staged, r"D\t\.claude/skills/cdv-debug/references/notes\.md")

    def test_a_dropped_skill_directory_disappears(self):
        core = self.make_core()
        self.commit_core(
            core,
            {},
            remove=["skills/cdv-debug/SKILL.md", "skills/cdv-debug/references/notes.md", "skills/cdv-debug/scripts/run.sh"],
            message="feat: drop a skill",
            tag="v0.2.0",
        )
        repo = self.make_consumer()
        self.sync(repo, core, "v0.1.0")
        self.sync(repo, core, "v0.2.0")
        self.assertFalse((repo / ".claude/skills/cdv-debug").exists())
        self.assertNotIn(".claude/skills/cdv-debug", self.read_lock(repo)["paths"])

    def test_lock_fields_and_tree_hash_match_what_verify_computes(self):
        core = self.make_core()
        repo = self.make_consumer()
        self.sync(repo, core, "v0.1.0")
        text = (repo / ".claude/harness.lock").read_text()
        lock = json.loads(text)
        self.assertEqual(lock["schema"], 1)
        self.assertEqual(lock["ref"], "v0.1.0")
        self.assertEqual(lock["commit"], self.git(core, "rev-parse", "v0.1.0^{commit}").stdout.strip())
        self.assertEqual(lock["source"], "https://example.com/acme/harness.git")
        self.assertRegex(lock["tree_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            lock["house_sha256"], __import__("hashlib").sha256(HOUSE_V1.encode()).hexdigest()
        )
        self.assertEqual(lock["paths"], sorted(lock["paths"]))
        self.assertEqual(
            lock["paths"],
            [
                ".claude/harness/bin",
                ".claude/rules/core",
                ".claude/skills/cdv-debug",
                ".claude/skills/cdv-grill-me",
                ".claude/skills/cdv-grilling",
                ".claude/skills/cdv-research-round",
            ],
        )
        self.assertEqual(lock["deny"], DENY_V1)
        self.assertEqual(list(lock["files"]), sorted(lock["files"]))
        self.assertIn(".claude/harness/bin/verify.sh", lock["files"])
        for path, digest in lock["files"].items():
            self.assertEqual(sha256_file(repo / path), digest, path)
        # one entry per line, as the sh verifier reads it
        self.assertIn('\n    ".claude/harness/bin",\n', text)
        self.assertIn('\n  "files": {\n    ".claude/harness/bin/verify.sh": "', text)
        self.assertTrue(text.endswith("\n}\n"))
        # the tree hash is the sha256 of the sha256sum lines, which is what verify.sh recomputes
        lines = "".join(f"{lock['files'][p]}  {p}\n" for p in sorted(lock["files"]))
        self.assertEqual(lock["tree_sha256"], __import__("hashlib").sha256(lines.encode()).hexdigest())
        result = self.verify(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("harness: vendored core matches v0.1.0", result.stdout)

    def test_lock_is_deterministic(self):
        core = self.make_core()
        first = self.make_consumer("first")
        second = self.make_consumer("second")
        self.sync(first, core, "v0.1.0")
        self.sync(second, core, "v0.1.0")
        self.assertEqual((first / ".claude/harness.lock").read_text(), (second / ".claude/harness.lock").read_text())

    def test_gitignored_claude_directory_is_still_staged(self):
        core = self.make_core()
        repo = self.make_consumer(gitignore_claude=True)
        self.sync(repo, core, "v0.1.0")
        staged = set(self.git(repo, "diff", "--cached", "--name-only").stdout.split())
        self.assertIn(".claude/skills/cdv-debug/SKILL.md", staged)
        self.assertIn(".claude/harness/bin/verify.sh", staged)
        self.assertIn(".claude/rules/core/testing.md", staged)
        self.assertIn(".claude/harness.lock", staged)
        self.assertIn(".claude/settings.json", staged)
        self.assertIn("CLAUDE.md", staged)

    def test_gitignored_claude_directory_stages_the_profile_but_not_the_local_profile(self):
        core = self.make_core()
        repo = self.make_consumer(gitignore_claude=True)
        self.git(repo, "rm", "-q", "--cached", ".claude/harness/profile.yaml")
        self.git(repo, "commit", "-q", "-m", "chore: untrack the profile")
        (repo / ".claude/harness/profile.local.yaml").write_text("commands_run_on: host\n")
        self.sync(repo, core, "v0.1.0")
        staged = self.git(repo, "diff", "--cached", "--name-status").stdout
        self.assertRegex(staged, r"A\t\.claude/harness/profile\.yaml")
        self.assertNotIn("profile.local.yaml", staged)

    def test_local_edits_to_vendored_files_are_overwritten_with_a_warning(self):
        core = self.make_core()
        self.add_v2(core)
        repo = self.make_consumer()
        self.sync(repo, core, "v0.1.0")
        skill = repo / ".claude/skills/cdv-debug/SKILL.md"
        skill.write_text(skill.read_text() + "local edit\n")
        result = self.sync(repo, core, "v0.2.0")
        self.assertIn("local changes in .claude/skills/cdv-debug/SKILL.md", result.stderr)
        self.assertNotIn("local edit", skill.read_text())

    def test_sync_without_from_clones_harness_source(self):
        core = self.make_core(with_remote=True)
        repo = self.make_consumer(harness_source=str(self.core_remote))
        result = self.harness("sync", "v0.1.0", "--repo", str(repo))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_lock(repo)["source"], str(self.core_remote))
        self.assertTrue((repo / ".claude/skills/cdv-debug/SKILL.md").exists())

    def test_sync_without_from_and_without_harness_source_is_an_error(self):
        repo = self.make_consumer()
        profile = repo / ".claude/harness/profile.yaml"
        profile.write_text(re.sub(r"^harness_source:.*\n", "", profile.read_text(), flags=re.M))
        result = self.harness("sync", "v0.1.0", "--repo", str(repo))
        self.assertEqual(result.returncode, 2)
        self.assertIn("harness_source", result.stderr)

    # -- --pr -------------------------------------------------------------------------

    def test_pr_with_gh_creates_branch_commits_pushes_and_opens_the_pr(self):
        core = self.make_core()
        gh = self.make_cli("gh")
        repo = self.make_consumer(pr_cli=gh)
        result = self.sync(repo, core, "v0.1.0", "--pr")
        self.assertEqual(result.returncode, 0, result.stderr)
        branch = "chore/harness-sync-v0.1.0"
        remote = self.tmp / "consumer-remote.git"
        remote_log = self.git(remote, "log", "--format=%s%n%b", branch).stdout
        self.assertTrue(remote_log.startswith("chore(harness): sync core v0.1.0"))
        self.assertNotIn("Co-Authored-By", remote_log)
        self.assertEqual(self.git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), "main")
        self.assertFalse((repo / ".claude/skills").exists())
        names = self.git(repo, "show", "--name-only", "--format=", branch).stdout.split()
        self.assertIn(".claude/harness.lock", names)
        self.assertIn(".claude/skills/cdv-debug/SKILL.md", names)
        calls = self.cli_calls("gh")
        self.assertEqual(len(calls), 1)
        argv = calls[0]
        self.assertEqual(argv[:2], ["pr", "create"])
        self.assertEqual(argv[argv.index("--base") + 1], "main")
        self.assertEqual(argv[argv.index("--head") + 1], branch)
        self.assertEqual(argv[argv.index("--title") + 1], "chore(harness): sync core v0.1.0")
        self.assertIn("--body-file", argv)
        body = (self.bin_dir / "gh.log.body").read_text()
        self.assertIn("v0.1.0", body)
        self.assertIn(self.git(core, "rev-parse", "v0.1.0^{commit}").stdout.strip(), body)
        self.assertRegex(body, r"Files added: \d+")
        self.assertIn("https://example.com/acme/app/pull/1", result.stdout)

    def test_pr_with_a_bitbucket_client_uses_source_and_dest(self):
        core = self.make_core()
        bb = self.make_cli("bb-client")
        repo = self.make_consumer(pr_cli=bb, vcs_host="bitbucket")
        result = self.sync(repo, core, "v0.1.0", "--pr")
        self.assertEqual(result.returncode, 0, result.stderr)
        argv = self.cli_calls("bb-client")[0]
        self.assertEqual(argv[:2], ["pr", "create"])
        self.assertEqual(argv[argv.index("--title") + 1], "chore(harness): sync core v0.1.0")
        self.assertEqual(argv[argv.index("--source") + 1], "chore/harness-sync-v0.1.0")
        self.assertEqual(argv[argv.index("--dest") + 1], "main")
        self.assertIn("--body-file", argv)
        self.assertNotIn("--base", argv)
        self.assertNotIn("--head", argv)

    def test_pr_command_failure_prints_the_push_output_and_exits_0(self):
        core = self.make_core()
        gh = self.make_cli("gh")
        repo = self.make_consumer(pr_cli=gh)
        env = dict(self.env, FAKE_FAIL="1")
        result = self.harness("sync", "v0.1.0", "--from", str(core), "--repo", str(repo), "--pr", env=env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("warning", result.stderr)
        self.assertIn("chore/harness-sync-v0.1.0", result.stdout)
        remote = self.tmp / "consumer-remote.git"
        self.assertIn("chore/harness-sync-v0.1.0", self.git(remote, "branch", "--list").stdout)

    def test_pr_on_an_up_to_date_repo_creates_no_branch(self):
        core = self.make_core()
        gh = self.make_cli("gh")
        repo = self.make_consumer(pr_cli=gh)
        self.sync(repo, core, "v0.1.0")
        self.commit_all(repo)
        result = self.sync(repo, core, "v0.1.0", "--pr")
        self.assertIn("already at v0.1.0", result.stdout)
        self.assertEqual(self.git(repo, "branch", "--list", "chore/*").stdout.strip(), "")
        self.assertEqual(self.cli_calls("gh"), [])

    def test_pr_refuses_a_dirty_working_tree(self):
        core = self.make_core()
        gh = self.make_cli("gh")
        repo = self.make_consumer(pr_cli=gh)
        (repo / "CLAUDE.md").write_text("changed\n")
        result = self.sync(repo, core, "v0.1.0", "--pr", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("uncommitted changes", result.stderr)
        self.assertEqual(self.git(repo, "branch", "--list", "chore/*").stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
