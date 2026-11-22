"""cdv-refactor: the state of a refactor is kept by a script, documents follow the code that moved,
and counters only move one way."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT

SCRIPTS = REPO_ROOT / "skills" / "cdv-refactor" / "scripts"
SKILL = REPO_ROOT / "skills" / "cdv-refactor"


def git(repo, *args):
    done = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def commit(repo, message, *paths):
    git(repo, "add", *(paths or ("-A",)))
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def run(script, *args, cwd):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=cwd, capture_output=True, text=True)


class RepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        git(self.repo, "init", "-q")
        (self.repo / "app").mkdir()
        (self.repo / "docs").mkdir()
        (self.repo / "app" / "InvoiceExporter.php").write_text("<?php class InvoiceExporter {}\n")
        (self.repo / "app" / "Index.php").write_text("<?php // list\n")
        (self.repo / "docs" / "guide.md").write_text("# Guide\n\nNothing about code yet.\n")
        self.base = commit(self.repo, "start")
        self.folder = self.repo / "docs" / "refactor"

    def tearDown(self):
        self._tmp.cleanup()


class StateTest(RepoCase):
    def state(self, *args):
        return run("refactor_state.py", "--folder", str(self.folder), *args, cwd=self.repo)

    def test_a_slice_moves_only_in_order_and_a_phase_closes_only_when_its_slices_did(self):
        self.assertEqual(self.state("init").returncode, 0)
        self.assertEqual(self.state("init").returncode, 3, "a second init must be refused")
        self.assertEqual(self.state("phase", "add", "1", "dissolve", "the", "hubs").returncode, 0)
        self.assertEqual(self.state("slice", "add", "1a", "routes by domain").returncode, 2, "--phase is required")
        self.assertEqual(self.state("slice", "add", "1a", "--phase", "9", "routes").returncode, 2, "unknown phase")
        self.assertEqual(self.state("slice", "add", "1a", "--phase", "1", "routes by domain").returncode, 0)

        refused = self.state("slice", "landed", "1a", "--range", f"{self.base}..{self.base}")
        self.assertEqual(refused.returncode, 3)
        self.assertIn("only after it started", refused.stderr)

        self.assertEqual(self.state("phase", "start", "1").returncode, 0)
        self.assertEqual(self.state("slice", "start", "1a", "--child", "builder-1").returncode, 0)
        self.assertEqual(self.state("slice", "built", "1a").returncode, 2, "--range is required")
        still_open = self.state("phase", "done", "1")
        self.assertEqual(still_open.returncode, 3)
        self.assertIn("1a", still_open.stderr)

        (self.repo / "app" / "Routes.php").write_text("<?php // moved\n")
        tip = commit(self.repo, "move the routes")
        self.assertEqual(self.state("slice", "landed", "1a", "--range", f"{self.base}..{tip}", "--evidence", "gate.log").returncode, 0)
        self.assertEqual(self.state("phase", "done", "1").returncode, 0)
        self.assertEqual(self.state("slice", "start", "nope").returncode, 2)

        where = self.state("where").stdout
        self.assertIn("phase 1 [done]", where)
        self.assertIn("1a [landed]", where)

    def test_render_counts_from_git_and_touches_only_its_block(self):
        self.state("init", "--slug", "billing-split")
        self.state("phase", "add", "1", "split billing")
        self.state("slice", "add", "1a", "--phase", "1", "exporter out of the controller")
        self.state("slice", "start", "1a")
        (self.repo / "app" / "Exporter.php").write_text("<?php\n// one\n// two\n")
        tip = commit(self.repo, "extract the exporter", "app/Exporter.php")  # the state folder stays out of the range
        self.state("slice", "landed", "1a", "--range", f"{self.base}..{tip}")
        self.folder.joinpath("STATE.md").write_text(
            "# state\n\n## Now\n\nwaiting for the verifier\n\n<!-- refactor-state:begin -->\nold table\n<!-- refactor-state:end -->\n\n## Traps\n\nkeep me\n"
        )

        self.assertEqual(self.state("render").returncode, 0)

        ledger = self.folder.joinpath("LEDGER.md").read_text()
        self.assertIn("| 1a | 1 | landed | exporter out of the controller | 1 | 1 | +3 -0 |", ledger)
        self.assertIn("Do not edit", ledger)
        state_md = self.folder.joinpath("STATE.md").read_text()
        self.assertIn("waiting for the verifier", state_md)
        self.assertIn("keep me", state_md)
        self.assertNotIn("old table", state_md)
        self.assertIn("| 1a | 1 | landed |", state_md)

    def test_a_range_git_does_not_know_is_said_not_counted(self):
        self.state("init")
        self.state("phase", "add", "1", "goal")
        self.state("slice", "add", "1a", "--phase", "1", "title")
        self.state("slice", "start", "1a")
        self.state("slice", "landed", "1a", "--range", "0000000..1111111")
        self.state("render")
        self.assertIn("range not found", self.folder.joinpath("LEDGER.md").read_text())


class DocsFollowCodeTest(RepoCase):
    def docs(self, *args):
        return run("docs_follow_code.py", "--base", self.base, *args, cwd=self.repo)

    def test_a_renamed_file_named_by_a_guide_is_reported_until_the_guide_follows(self):
        guide = self.repo / "docs" / "guide.md"
        guide.write_text("# Guide\n\nThe export lives in `app/InvoiceExporter.php`.\nSee InvoiceExporter.php too.\n")
        commit(self.repo, "guide")
        (self.repo / "app" / "Billing").mkdir()
        git(self.repo, "mv", "app/InvoiceExporter.php", "app/Billing/InvoiceCsvExporter.php")
        commit(self.repo, "move the exporter")

        result = self.docs()
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/guide.md:3: app/InvoiceExporter.php (renamed to app/Billing/InvoiceCsvExporter.php)", result.stdout)
        self.assertIn("docs/guide.md:4: InvoiceExporter.php", result.stdout)

        guide.write_text("# Guide\n\nThe export lives in `app/Billing/InvoiceCsvExporter.php`.\n")
        self.assertEqual(self.docs().returncode, 0)

    def test_a_file_name_that_is_still_alive_or_short_is_not_a_needle(self):
        (self.repo / "app" / "admin").mkdir()
        (self.repo / "app" / "admin" / "Index.php").write_text("<?php // admin list\n")
        (self.repo / "docs" / "guide.md").write_text("# Guide\n\nEvery module has an Index.php.\n")
        commit(self.repo, "second index")
        git(self.repo, "rm", "-q", "app/Index.php")
        commit(self.repo, "drop the first index")
        self.assertEqual(self.docs().returncode, 0, "Index.php still exists elsewhere: the guide is not stale")

    def test_a_named_symbol_and_the_allow_list(self):
        (self.repo / "docs" / "guide.md").write_text("# Guide\n\nCall `persistField()` from the controller.\n")
        (self.repo / "docs" / "changelog.md").write_text("# Changelog\n\n- persistField() left the controller.\n")
        commit(self.repo, "docs")

        result = self.docs("--name", "persistField")
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/guide.md:3: persistField (named with --name)", result.stdout)
        self.assertIn("docs/changelog.md:3", result.stdout)

        allow = self.repo / "allow.txt"
        allow.write_text("# history\ndocs/changelog.md\ndocs/guide.md:persistField\n")
        self.assertEqual(self.docs("--name", "persistField", "--allow", str(allow)).returncode, 0)

    def test_only_the_given_documents_are_searched(self):
        (self.repo / "docs" / "guide.md").write_text("# Guide\n\n`app/InvoiceExporter.php`\n")
        (self.repo / "README.md").write_text("`app/InvoiceExporter.php`\n")
        commit(self.repo, "docs")
        git(self.repo, "rm", "-q", "app/InvoiceExporter.php")
        commit(self.repo, "delete")
        only_readme = self.docs("--docs", "README.md")
        self.assertEqual(only_readme.returncode, 1)
        self.assertNotIn("docs/guide.md", only_readme.stdout)
        self.assertIn("(deleted)", only_readme.stdout)


class RatchetTest(RepoCase):
    def ratchet(self, *args):
        return run("ratchet.py", "--folder", str(self.folder), *args, cwd=self.repo)

    def configure(self):
        self.folder.mkdir(parents=True)
        self.folder.joinpath("ratchet.json").write_text(json.dumps({"counters": [
            {"name": "php-files", "cmd": "git ls-files 'app/*.php' | wc -l", "direction": "down"},
            {"name": "guides", "cmd": "git ls-files 'docs/*.md' | wc -l", "direction": "up"},
        ]}))

    def test_a_counter_may_only_move_its_way_and_tighten_keeps_the_gain(self):
        self.configure()
        self.assertEqual(self.ratchet("snapshot").returncode, 0)
        self.assertEqual(json.loads(self.folder.joinpath("baseline.json").read_text())["counters"], {"php-files": 2, "guides": 1})
        self.assertEqual(self.ratchet("check").returncode, 0)

        (self.repo / "app" / "Extra.php").write_text("<?php\n")
        commit(self.repo, "one more file")
        worse = self.ratchet("check")
        self.assertEqual(worse.returncode, 1)
        self.assertIn("WORSE  php-files: 2 -> 3", worse.stdout)

        git(self.repo, "rm", "-q", "app/Extra.php", "app/Index.php")
        commit(self.repo, "two fewer")
        better = self.ratchet("check", "--tighten")
        self.assertEqual(better.returncode, 0)
        self.assertIn("better php-files: 2 -> 1", better.stdout)
        self.assertEqual(json.loads(self.folder.joinpath("baseline.json").read_text())["counters"]["php-files"], 1)

    def test_no_configuration_or_no_number_is_its_own_exit(self):
        self.assertEqual(self.ratchet("check").returncode, 2)
        self.folder.mkdir(parents=True)
        self.folder.joinpath("ratchet.json").write_text(json.dumps({"counters": [{"name": "x", "cmd": "echo none", "direction": "down"}]}))
        silent = self.ratchet("snapshot")
        self.assertEqual(silent.returncode, 2)
        self.assertIn("printed no number", silent.stderr)


class SkillTextTest(unittest.TestCase):
    def test_the_skill_names_its_scripts_and_its_references_exist(self):
        text = (SKILL / "SKILL.md").read_text()
        for script in ("refactor_state.py", "docs_follow_code.py", "ratchet.py"):
            self.assertIn(script, text)
            self.assertTrue((SCRIPTS / script).is_file())
        for reference in ("references/method.md", "references/error-classes.md", "references/templates/task-file.md",
                          "references/templates/state-folder.md", "references/templates/verifier-brief.md"):
            self.assertIn(reference, text)
            self.assertTrue((SKILL / reference).is_file(), reference)


if __name__ == "__main__":
    unittest.main()
