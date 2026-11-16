from helpers import REPO_ROOT, HarnessTestCase, run

SCRIPT = REPO_ROOT / "skills" / "cdv-code-review" / "scripts" / "verify-anchors.sh"


class VerifyAnchorsTest(HarnessTestCase):
    def make_repo(self):
        repo = self.tmp / "app"
        repo.mkdir()
        self.git(repo, "init", "-q")
        (repo / "README.md").write_text("base\n")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "chore: base")
        self.git(repo, "switch", "-q", "-c", "feature")
        (repo / "Service.php").write_text("<?php\n\nclass Service\n{\n}\n")
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-q", "-m", "feat: add the service")
        return repo

    def review_dir(self, anchor):
        review = self.tmp / "review"
        review.mkdir(exist_ok=True)
        (review / "M1-finding.md").write_text(f"<!-- ANCHOR: {anchor} -->\n\nFinding.\n")
        return review

    def anchors(self, repo, review, *refs):
        return run(["bash", SCRIPT, review, *refs], cwd=repo, env=self.env, check=False)

    def test_head_ref_is_read_without_a_checkout(self):
        repo = self.make_repo()
        self.git(repo, "switch", "-q", "main")
        result = self.anchors(repo, self.review_dir("Service.php:3"), "main", "feature")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("all 1 anchors ok", result.stdout)

    def test_a_line_past_the_end_of_the_head_ref_file_is_out_of_file(self):
        repo = self.make_repo()
        self.git(repo, "switch", "-q", "main")
        result = self.anchors(repo, self.review_dir("Service.php:9"), "main", "feature")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stdout, r"Service\.php:9\s+out-of-file")

    def test_a_file_outside_the_diff_is_rejected(self):
        repo = self.make_repo()
        result = self.anchors(repo, self.review_dir("README.md:1"), "main", "HEAD")
        self.assertEqual(result.returncode, 1)
        self.assertRegex(result.stdout, r"README\.md:1\s+missing-from-diff")
