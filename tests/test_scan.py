import shutil
import unittest

from helpers import REPO_ROOT, HarnessTestCase, fake_token

EXPECTED_MATCH = {
    "collection": "collec" + "tion://",
    "bitbucket": "bitbucket" + ".org/someworkspace/",
    "brazil": ".com" + ".br",
    "home": "/ho" + "me/s",
    "ticket": fake_token("ticket"),
    "slack": "xo" + "xb-",
    "aws": fake_token("aws"),
    "github": fake_token("github"),
    "email": fake_token("email"),
}
PUBLIC_KINDS = list(EXPECTED_MATCH)


class ScanTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.core = self.tmp / "scancore"
        self.core.mkdir()
        shutil.copy(REPO_ROOT / "scan-patterns.txt", self.core / "scan-patterns.txt")
        (self.core / "notes").mkdir()

    def put(self, relative, text):
        path = self.core / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def scan(self, *args):
        return self.harness("scan", "--core", str(self.core), *args)

    def test_clean_core_has_no_findings(self):
        self.put("notes/clean.md", "Nothing to see. Contact user@example.com or v0.1.0 or sha256 abc.\n")
        self.put("notes/noreply.md", "Co-author: 123+name@users.noreply.github.com\n")
        result = self.scan()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "scan: 0 findings")

    def test_each_public_pattern_is_caught(self):
        for kind in PUBLIC_KINDS:
            with self.subTest(kind=kind):
                token = fake_token(kind)
                self.put(f"notes/{kind}.md", f"first line\nsome {token} here\n")
                result = self.scan(str(self.core / "notes" / f"{kind}.md"))
                self.assertEqual(result.returncode, 1, f"{kind}: {result.stdout}")
                self.assertIn(f"notes/{kind}.md:2: ", result.stdout)
                self.assertTrue(result.stdout.rstrip().endswith(": " + EXPECTED_MATCH[kind]), result.stdout)
                (self.core / "notes" / f"{kind}.md").unlink()

    def test_output_format_is_path_line_pattern_match(self):
        self.put("notes/a.md", f"x\n{fake_token('aws')}\n")
        result = self.scan()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), f"notes/a.md:2: AKIA[0-9A-Z]{{16}}: {fake_token('aws')}")

    def test_a_directory_walk_reports_every_file(self):
        self.put("notes/one.md", fake_token("slack") + "\n")
        self.put("notes/two.md", fake_token("home") + "\n")
        result = self.scan()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stdout.strip().splitlines()), 2)

    def test_pattern_files_binaries_and_git_dir_are_skipped(self):
        self.put("scan-allowlist.txt", f"# {fake_token('ticket')}\n")
        self.put("notes/pattern-mention.md", "clean\n")
        (self.core / ".git").mkdir()
        self.put(".git/config", fake_token("github") + "\n")
        (self.core / "notes" / "blob.bin").write_bytes(b"\0\1\2" + fake_token("github").encode())
        (self.core / "notes" / "latin1.txt").write_bytes(b"caf\xe9 " + fake_token("github").encode())
        result = self.scan()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_file_path_is_scanned_too(self):
        self.put(f"notes/{fake_token('ticket')}-notes.md", "clean\n")
        result = self.scan()
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"notes/{fake_token('ticket')}-notes.md:0: ", result.stdout)

    def test_commits_scans_identities_messages_and_tags(self):
        self.git(self.core, "init", "-q")
        self.put("notes/clean.md", "clean\n")
        self.git(self.core, "add", "-A")
        env = dict(self.env, GIT_AUTHOR_EMAIL="dev@company" + ".com" + ".br")
        self.git(self.core, "commit", "-q", "-m", "chore: start", env=env)
        self.git(self.core, "commit", "-q", "--allow-empty", "-m", f"fix: the {fake_token('ticket')} bug")
        self.git(self.core, "tag", "-a", "v0.1.0", "-m", "release v0.1.0")
        self.assertEqual(self.scan().returncode, 0)
        result = self.scan("--commits", "HEAD")
        self.assertEqual(result.returncode, 1)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 3, result.stdout)
        self.assertTrue(any(line.startswith("commit ") and ".com" + ".br" in line for line in lines), lines)
        self.assertTrue(any(line.startswith("commit ") and line.endswith(fake_token("ticket")) for line in lines), lines)

    def test_commits_include_the_tagger(self):
        self.git(self.core, "init", "-q")
        self.put("notes/clean.md", "clean\n")
        self.git(self.core, "add", "-A")
        self.git(self.core, "commit", "-q", "-m", "chore: start")
        env = dict(self.env, GIT_COMMITTER_EMAIL="dev@company" + ".com" + ".br")
        self.git(self.core, "tag", "-a", "v0.1.0", "-m", "release v0.1.0", env=env)
        result = self.scan("--commits", "HEAD")
        self.assertEqual(result.returncode, 1)
        self.assertIn("tag v0.1.0:", result.stdout)

    def test_extra_patterns_file_adds_a_pattern(self):
        self.put("notes/a.md", "the codename is Bluebird here\n")
        self.assertEqual(self.scan().returncode, 0)
        extra = self.tmp / "extra.txt"
        extra.write_text("# private\nBluebird\n")
        result = self.scan("--extra-patterns", str(extra))
        self.assertEqual(result.returncode, 1)
        self.assertIn("notes/a.md:1: Bluebird: Bluebird", result.stdout)

    def test_matching_is_case_sensitive_unless_the_pattern_starts_with_i_flag(self):
        self.put("notes/a.md", "the codename is bluebird here\n")
        sensitive = self.tmp / "sensitive.txt"
        sensitive.write_text("Bluebird\n")
        self.assertEqual(self.scan("--extra-patterns", str(sensitive)).returncode, 0)
        insensitive = self.tmp / "insensitive.txt"
        insensitive.write_text("(?i)Bluebird\n")
        result = self.scan("--extra-patterns", str(insensitive))
        self.assertEqual(result.returncode, 1)
        self.assertIn("(?i)Bluebird: bluebird", result.stdout)

    def test_an_allowlisted_finding_is_skipped(self):
        token = fake_token("ticket")
        self.put("notes/a.md", f"see {token} here\n")
        self.put("notes/b.md", f"see {token} here\n")
        self.put("scan-allowlist.txt", f"notes/a.md\t^{token}$\tfixture used in the docs\n")
        result = self.scan()
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("notes/a.md", result.stdout)
        self.assertIn("notes/b.md:1:", result.stdout)

    def test_allowlist_glob_and_regex_must_both_match(self):
        token = fake_token("ticket")
        self.put("notes/a.md", f"see {token} here\n")
        self.put("scan-allowlist.txt", f"notes/*.md\tNOPE\treason\nother/*\t{token}\treason\n")
        self.assertEqual(self.scan().returncode, 1)
        self.put("scan-allowlist.txt", f"notes/*.md\t{token}\treason\n")
        self.assertEqual(self.scan().returncode, 0)

    def test_an_allowlist_span_exempts_only_the_containing_text(self):
        names = self.tmp / "names.txt"
        names.write_text("(?i)\\bbluebird\\b\n")
        self.put("notes/a.md", "owner: bluebird-jones\n")
        self.put("notes/b.md", "written by Bluebird\n")
        self.put("scan-allowlist.txt", "notes/*.md\tbluebird-jones\tpublic login of the named owner\n")
        result = self.scan("--extra-patterns", str(names))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("notes/a.md", result.stdout)
        self.assertIn("notes/b.md:1:", result.stdout)

    def test_an_allowlist_line_without_a_reason_is_an_error(self):
        self.put("notes/a.md", "clean\n")
        for line in ["notes/*\tregex\n", "notes/*\tregex\t \n", "notes/* regex reason\n"]:
            with self.subTest(line=line):
                self.put("scan-allowlist.txt", line)
                result = self.scan()
                self.assertEqual(result.returncode, 2)
                self.assertIn("scan-allowlist.txt:1:", result.stderr)
                self.assertIn("reason", result.stderr)

    def test_an_invalid_pattern_is_an_error(self):
        extra = self.tmp / "bad.txt"
        extra.write_text("ok\n(unclosed\n")
        result = self.scan("--extra-patterns", str(extra))
        self.assertEqual(result.returncode, 2)
        self.assertIn("bad.txt:2:", result.stderr)

    def test_untracked_files_are_scanned_in_a_git_core_and_ignored_ones_are_not(self):
        self.git(self.core, "init", "-q", "-b", "main")
        self.put(".gitignore", "ignored/\n")
        self.put("ignored/x.md", fake_token("github") + "\n")
        self.put("notes/untracked.md", fake_token("slack") + "\n")
        result = self.scan()
        self.assertEqual(result.returncode, 1)
        self.assertIn("notes/untracked.md", result.stdout)
        self.assertNotIn("ignored/", result.stdout)


if __name__ == "__main__":
    unittest.main()
