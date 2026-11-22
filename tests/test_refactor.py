"""cdv-refactor: the state of a refactor is kept by a script, documents follow the code that moved,
counters only move one way, a record changes only with a declaration, and every tool ends with one
verdict line."""

import json
import re
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


def verdict(result, tool, mode, status):
    """The last line of stdout is the one verdict line of the tool, and the exit code agrees with its status."""
    last = result.stdout.rstrip("\n").splitlines()[-1] if result.stdout.strip() else ""
    found = re.fullmatch(rf"{tool} ([\w-]+): (PASS|FAIL|PARTIAL) \u2014 .+", last)
    assert found, f"no verdict line in {result.stdout!r} / {result.stderr!r}"
    assert found.group(1) == mode and found.group(2) == status, last
    assert (result.returncode == 0) == (status == "PASS"), (result.returncode, last)
    assert (result.returncode == 4) == (status == "PARTIAL"), (result.returncode, last)
    return last


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


    def test_init_records_the_base_and_phase_start_the_start_of_the_phase(self):
        self.state("init")
        state = json.loads(self.folder.joinpath("state.json").read_text())
        self.assertEqual(state["base"], self.base)
        self.state("phase", "add", "1", "goal")
        (self.repo / "app" / "Later.php").write_text("<?php\n")
        later = commit(self.repo, "later", "app/Later.php")
        self.state("phase", "start", "1")
        phase = json.loads(self.folder.joinpath("state.json").read_text())["phases"][0]
        self.assertEqual(phase["start"], later)
        explicit = self.folder.parent / "other"
        done = run("refactor_state.py", "--folder", str(explicit), "init", "--base", later, cwd=self.repo)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(json.loads(explicit.joinpath("state.json").read_text())["base"], later)
        unknown = run("refactor_state.py", "--folder", str(explicit.parent / "third"), "init", "--base", "nope", cwd=self.repo)
        self.assertEqual(unknown.returncode, 2)

    def test_every_command_ends_with_the_verdict_line(self):
        verdict(self.state("init"), "refactor_state", "init", "PASS")
        verdict(self.state("init"), "refactor_state", "init", "FAIL")  # refused: exit 3
        verdict(self.state("phase", "add", "1", "goal"), "refactor_state", "phase", "PASS")
        verdict(self.state("phase", "done", "9"), "refactor_state", "phase", "FAIL")  # unknown id: exit 2
        verdict(self.state("where"), "refactor_state", "where", "PASS")
        verdict(self.state("render"), "refactor_state", "render", "PASS")
        self.assertEqual(self.state("slice", "add", "1a", "t").returncode, 2)
        self.assertEqual(self.state("phase", "bogus", "1").returncode, 2, "a bad argument is a usage error with a verdict line")
        verdict(self.state("phase", "bogus", "1"), "refactor_state", "state", "FAIL")


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


    def test_the_base_comes_from_state_and_every_exit_has_its_verdict(self):
        state = ["--folder", str(self.folder)]
        run("refactor_state.py", *state, "init", cwd=self.repo)
        (self.repo / "docs" / "guide.md").write_text("# Guide\n\n`app/InvoiceExporter.php`\n")
        commit(self.repo, "guide")
        git(self.repo, "rm", "-q", "app/InvoiceExporter.php")
        commit(self.repo, "delete")
        stale = run("docs_follow_code.py", *state, cwd=self.repo)
        self.assertEqual(stale.returncode, 1)
        verdict(stale, "docs_follow_code", "check", "FAIL")
        self.assertEqual(run("docs_follow_code.py", cwd=self.repo).returncode, 2, "no base anywhere")
        verdict(run("docs_follow_code.py", cwd=self.repo), "docs_follow_code", "check", "FAIL")
        (self.repo / "docs" / "guide.md").write_text("# Guide\n")
        verdict(self.docs(), "docs_follow_code", "check", "PASS")
        self.assertEqual(self.docs("--docs", "docs/missing").returncode, 2)
        with tempfile.TemporaryDirectory() as outside:
            elsewhere = run("docs_follow_code.py", "--base", "x", cwd=outside)
            self.assertEqual(elsewhere.returncode, 3, "not a git repository is an environment problem")
            verdict(elsewhere, "docs_follow_code", "check", "FAIL")

    def test_no_document_searched_is_partial_never_a_pass(self):
        (self.repo / "docs" / "guide.md").unlink()
        git(self.repo, "rm", "-q", "--cached", "docs/guide.md")
        commit(self.repo, "no guide")
        result = self.docs()
        self.assertEqual(result.returncode, 4)
        verdict(result, "docs_follow_code", "check", "PARTIAL")


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


class RatchetHistoryTest(RepoCase):
    """`check --base` judges the baseline commit by commit: a commit cannot lower a cap or rewrite a command."""

    def setUp(self):
        super().setUp()
        self.folder.mkdir(parents=True)
        self.config = {"counters": [
            {"name": "php-files", "cmd": "git ls-files 'app/*.php' | wc -l", "direction": "down"},
            {"name": "guides", "cmd": "git ls-files 'docs/*.md' | wc -l", "direction": "up"},
        ]}
        self.folder.joinpath("ratchet.json").write_text(json.dumps(self.config))
        self.ratchet("snapshot")
        self.start = commit(self.repo, "ratchets and baseline")

    def ratchet(self, *args):
        return run("ratchet.py", "--folder", str(self.folder), *args, cwd=self.repo)

    def walk(self, *args, base=None):
        return self.ratchet("check", "--base", base or self.start, *args)

    def set_baseline(self, **values):
        path = self.folder / "baseline.json"
        data = json.loads(path.read_text())
        data["counters"].update(values)
        path.write_text(json.dumps(data, indent=2))

    def test_a_commit_that_lowers_the_baseline_does_not_pass_even_when_plain_check_does(self):
        (self.repo / "app" / "Extra.php").write_text("<?php\n")
        self.set_baseline(**{"php-files": 3})
        commit(self.repo, "one more file, and the cap moved with it")
        plain = self.ratchet("check")
        self.assertEqual(plain.returncode, 0, "the hole: the baseline is read from the tree a commit can edit")
        result = self.walk()
        self.assertEqual(result.returncode, 1)
        self.assertIn("LOOSENED", result.stdout)
        self.assertIn("moves the baseline of php-files the wrong way (2 -> 3, may only go down)", result.stdout)
        verdict(result, "ratchet", "check", "FAIL")

    def test_a_loosening_that_a_later_commit_restores_is_still_a_loosening(self):
        self.set_baseline(guides=0)
        commit(self.repo, "lower the floor")
        self.set_baseline(guides=1)
        commit(self.repo, "put it back")
        result = self.walk()
        self.assertEqual(result.returncode, 1)
        self.assertIn("moves the baseline of guides the wrong way (1 -> 0, may only go up)", result.stdout)

    def test_a_commit_that_rewrites_a_counters_command_does_not_pass(self):
        self.config["counters"][0]["cmd"] = "echo 0"
        self.folder.joinpath("ratchet.json").write_text(json.dumps(self.config))
        commit(self.repo, "the counter now always says zero")
        self.assertEqual(self.ratchet("check").returncode, 0, "plain check measures with the rewritten command")
        result = self.walk()
        self.assertEqual(result.returncode, 1)
        self.assertIn("rewrites the command of php-files", result.stdout)
        verdict(result, "ratchet", "check", "FAIL")

    def test_flipping_a_direction_or_removing_a_counter_does_not_pass(self):
        self.config["counters"][0]["direction"] = "up"
        self.folder.joinpath("ratchet.json").write_text(json.dumps(self.config))
        commit(self.repo, "flip")
        self.assertIn("changes the direction of php-files", self.walk().stdout)
        git(self.repo, "reset", "-q", "--hard", self.start)
        self.folder.joinpath("ratchet.json").write_text(json.dumps({"counters": self.config["counters"][1:]}))
        commit(self.repo, "drop a counter")
        self.assertIn("removes the counter php-files", self.walk().stdout)

    def test_a_move_the_right_way_passes_in_every_commit(self):
        git(self.repo, "rm", "-q", "app/Index.php")
        self.set_baseline(**{"php-files": 1})
        commit(self.repo, "one file fewer, and the cap follows")
        (self.repo / "docs" / "second.md").write_text("# Second\n")
        commit(self.repo, "a guide more", "docs/second.md")
        self.ratchet("check", "--tighten")
        commit(self.repo, "tighten")
        result = self.walk()
        self.assertEqual(result.returncode, 0, result.stdout)
        verdict(result, "ratchet", "check", "PASS")
        self.assertIn("0 loosening(s)", result.stdout)

    def test_a_loosening_accepted_in_its_own_commit_passes_and_a_later_acceptance_does_not(self):
        (self.repo / "app" / "Extra.php").write_text("<?php\n")
        self.set_baseline(**{"php-files": 3})
        self.folder.joinpath("records.json").write_text(json.dumps(
            {"accepted": [{"counter": "php-files", "reason": "a file split in two, decision 7"}]}))
        commit(self.repo, "one more file, accepted")
        self.assertEqual(self.walk().returncode, 0)
        git(self.repo, "reset", "-q", "--hard", self.start)
        (self.repo / "app" / "Extra.php").write_text("<?php\n")
        self.set_baseline(**{"php-files": 3})
        commit(self.repo, "one more file")
        self.folder.joinpath("records.json").write_text(json.dumps(
            {"accepted": [{"counter": "php-files", "reason": "too late"}]}))
        commit(self.repo, "accept it afterwards")
        self.assertEqual(self.walk().returncode, 1)

    def test_the_working_tree_is_judged_against_head(self):
        self.set_baseline(guides=0)
        result = self.walk()
        self.assertEqual(result.returncode, 1)
        self.assertIn("LOOSENED the working tree", result.stdout)

    def test_the_base_comes_from_state_when_none_is_given(self):
        run("refactor_state.py", "--folder", str(self.folder), "init", "--base", self.start, cwd=self.repo)
        self.set_baseline(guides=0)
        commit(self.repo, "lower the floor")
        bare = self.ratchet("check", "--base")
        self.assertEqual(bare.returncode, 1)
        self.assertIn("history since " + self.start[:12], bare.stdout)

    def test_plain_check_keeps_working_and_every_exit_has_its_verdict(self):
        ok = self.ratchet("check")
        verdict(ok, "ratchet", "check", "PASS")
        verdict(self.ratchet("snapshot"), "ratchet", "snapshot", "PASS")
        unknown = self.walk(base="0000000000000000000000000000000000000000")
        self.assertEqual(unknown.returncode, 2)
        verdict(unknown, "ratchet", "check", "FAIL")
        nobase = self.ratchet("check", "--base")
        self.assertEqual(nobase.returncode, 2, "bare --base and no base in state")
        self.folder.joinpath("baseline.json").write_text("{broken")
        self.assertEqual(self.ratchet("check").returncode, 2, "a broken baseline is a usage problem, not a traceback")
        with tempfile.TemporaryDirectory() as outside:
            missing = run("ratchet.py", "--folder", "x", "check", cwd=outside)
            self.assertEqual(missing.returncode, 2)
            verdict(missing, "ratchet", "check", "FAIL")

    def test_a_commit_whose_files_cannot_be_read_is_partial_never_a_pass(self):
        good = self.folder.joinpath("baseline.json").read_text()
        self.folder.joinpath("baseline.json").write_text("{broken")
        commit(self.repo, "a broken baseline")
        self.folder.joinpath("baseline.json").write_text(good)
        commit(self.repo, "repaired")
        result = self.walk()
        self.assertEqual(result.returncode, 4, result.stdout)
        verdict(result, "ratchet", "check", "PARTIAL")


class RecordsGuardTest(RepoCase):
    """A file under a frozen location changes only with a declaration added by the same commit."""

    def setUp(self):
        super().setUp()
        (self.repo / "records").mkdir()
        (self.repo / "records" / "routes.json").write_text('{"v": 1}\n')
        (self.repo / "records" / "registry.json").write_text('{"v": 1}\n')
        self.start = commit(self.repo, "records")
        self.folder.mkdir(parents=True)
        self.write_records(frozen=["records/"], excludes=["records/registry.json"])
        commit(self.repo, "freeze the records")

    def write_records(self, **fields):
        path = self.folder / "records.json"
        data = json.loads(path.read_text()) if path.is_file() else {}
        data.update(fields)
        path.write_text(json.dumps(data, indent=2))

    def declare(self, path, reason="decision 4: route retired", **extra):
        data = json.loads((self.folder / "records.json").read_text())
        data.setdefault("declared", []).append({"path": path, "reason": reason, **extra})
        (self.folder / "records.json").write_text(json.dumps(data, indent=2))

    def edit(self, name="routes.json", text='{"v": 2}\n'):
        (self.repo / "records" / name).write_text(text)

    def guard(self, *args, base=None):
        return run("records_guard.py", "--folder", str(self.folder), "--base", base or self.base, *args, cwd=self.repo)

    def test_a_record_changed_in_a_commit_with_no_declaration_is_refused(self):
        self.edit()
        commit(self.repo, "fix the record instead of the code")
        result = self.guard()
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNDECLARED modified records/routes.json", result.stdout)
        self.assertIn("IN THE COMMIT THAT MAKES THEM", result.stdout)
        verdict(result, "records_guard", "check", "FAIL")

    def test_a_deletion_and_a_rename_are_changes_too(self):
        git(self.repo, "mv", "records/routes.json", "records/paths.json")
        commit(self.repo, "rename a record")
        result = self.guard()
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNDECLARED deleted  records/routes.json", result.stdout)
        self.assertNotIn("paths.json", result.stdout, "the new name is an addition, which is allowed")

    def test_a_declaration_in_a_later_commit_covers_nothing_earlier(self):
        self.edit()
        commit(self.repo, "edit the record")
        self.declare("records/routes.json")
        commit(self.repo, "declare it afterwards")
        result = self.guard()
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNDECLARED modified records/routes.json", result.stdout)
        self.assertIn("STALE declaration of records/routes.json", result.stdout, "and the late declaration covers nothing")

    def test_a_change_declared_in_its_own_commit_passes(self):
        self.edit()
        self.declare("records/routes.json")
        commit(self.repo, "retire the route, declared")
        result = self.guard()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("declared  any records/routes.json", result.stdout)
        verdict(result, "records_guard", "check", "PASS")
        self.edit(text='{"v": 3}\n')
        commit(self.repo, "edit it again")
        self.assertEqual(self.guard().returncode, 1, "the declaration covered its own commit only")

    def test_a_declared_deletion_passes_and_adding_a_record_is_always_allowed(self):
        (self.repo / "records" / "new.json").write_text("{}\n")
        commit(self.repo, "a new record")
        self.assertEqual(self.guard().returncode, 0)
        (self.repo / "records" / "new.json").write_text('{"changed": true}\n')
        commit(self.repo, "change the new record")
        self.assertEqual(self.guard().returncode, 1, "from the commit that adds it, the record is protected")
        git(self.repo, "reset", "-q", "--hard", "HEAD~1")
        git(self.repo, "rm", "-q", "records/new.json")
        self.declare("records/new.json", change="deleted")
        commit(self.repo, "drop a record, declared")
        self.assertEqual(self.guard().returncode, 0)

    def test_unfreezing_in_the_commit_that_edits_does_not_unfreeze(self):
        self.write_records(frozen=[])
        self.edit()
        commit(self.repo, "empty the list and edit the record in one commit")
        result = self.guard()
        self.assertEqual(result.returncode, 1, "the union of every version of the list freezes for good")
        self.assertIn("UNDECLARED modified records/routes.json", result.stdout)

    def test_an_exclusion_counts_only_when_every_version_has_it(self):
        self.edit("registry.json")
        commit(self.repo, "the registry is excluded: free to edit")
        self.assertEqual(self.guard().returncode, 0)
        self.write_records(excludes=[])
        commit(self.repo, "drop the exclusion")
        self.assertEqual(self.guard().returncode, 1, "the registry is frozen at once, for the whole range")

    def test_a_declaration_that_covers_nothing_is_stale_until_allowed(self):
        self.declare("records/routes.json")
        commit(self.repo, "declare what nobody changed")
        stale = self.guard()
        self.assertEqual(stale.returncode, 1)
        self.assertIn("STALE declaration of records/routes.json", stale.stdout)
        self.assertEqual(self.guard("--allow-stale").returncode, 0)

    def test_a_declaration_must_name_files_and_a_big_one_must_count(self):
        self.declare("records/*", change="modified")
        commit(self.repo, "a declaration over the whole location")
        broad = self.guard()
        self.assertEqual(broad.returncode, 2)
        self.assertIn("TOO BROAD", broad.stderr)
        verdict(broad, "records_guard", "check", "FAIL")
        git(self.repo, "reset", "-q", "--hard", "HEAD~1")
        for n in range(12):
            (self.repo / "records" / "sub").mkdir(exist_ok=True)
            (self.repo / "records" / "sub" / f"f{n:02d}.json").write_text("{}\n")
        commit(self.repo, "twelve records")
        for n in range(12):
            (self.repo / "records" / "sub" / f"f{n:02d}.json").write_text('{"n": 1}\n')
        self.declare("records/sub/*", change="modified")
        commit(self.repo, "change twelve, no count")
        self.assertIn("TOO BROAD", self.guard().stdout)
        git(self.repo, "reset", "-q", "--hard", "HEAD~1")
        for n in range(12):
            (self.repo / "records" / "sub" / f"f{n:02d}.json").write_text('{"n": 1}\n')
        self.declare("records/sub/*", change="modified", count=12)
        commit(self.repo, "change twelve, counted")
        self.assertEqual(self.guard().returncode, 0)

    def test_the_working_tree_is_judged_with_worktree(self):
        self.edit()
        self.assertEqual(self.guard().returncode, 0, "uncommitted: not in the range")
        result = self.guard("--worktree")
        self.assertEqual(result.returncode, 1)
        self.assertIn("[the working tree]", result.stdout)
        self.declare("records/routes.json")
        self.assertEqual(self.guard("--worktree").returncode, 0, "an uncommitted declaration covers the uncommitted change")

    def test_the_base_comes_from_state_when_none_is_given(self):
        run("refactor_state.py", "--folder", str(self.folder), "init", "--base", self.start, cwd=self.repo)
        self.edit()
        commit(self.repo, "edit")
        result = run("records_guard.py", "--folder", str(self.folder), cwd=self.repo)
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{self.start} -> HEAD", result.stdout)

    def test_exit_codes_and_the_verdict_line(self):
        self.assertEqual(self.guard().returncode, 0)
        verdict(self.guard(), "records_guard", "check", "PASS")
        unknown = self.guard(base="0000000000000000000000000000000000000000")
        self.assertEqual(unknown.returncode, 2)
        verdict(unknown, "records_guard", "check", "FAIL")
        nobase = run("records_guard.py", "--folder", str(self.folder), cwd=self.repo)
        self.assertEqual(nobase.returncode, 2, "no --base and no state.json")
        verdict(nobase, "records_guard", "check", "FAIL")
        missing = run("records_guard.py", "--folder", str(self.repo / "docs" / "nowhere"), "--base", self.base, cwd=self.repo)
        self.assertEqual(missing.returncode, 2, "no records.json")
        self.assertEqual(run("records_guard.py", cwd=self.repo).returncode, 2, "--folder is required")
        with tempfile.TemporaryDirectory() as outside:
            elsewhere = run("records_guard.py", "--folder", "x", "--base", "y", cwd=outside)
            self.assertEqual(elsewhere.returncode, 3)
            verdict(elsewhere, "records_guard", "check", "FAIL")

    def test_nothing_frozen_or_an_unreadable_version_is_partial_never_a_pass(self):
        self.write_records(frozen=[])
        commit(self.repo, "nothing is frozen any more")
        # the union still holds the earlier list: freeze again from a clean history
        git(self.repo, "reset", "-q", "--hard", self.start)
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "records.json").write_text(json.dumps({"frozen": []}))
        commit(self.repo, "an empty list")
        empty = self.guard()
        self.assertEqual(empty.returncode, 4)
        verdict(empty, "records_guard", "check", "PARTIAL")
        (self.folder / "records.json").write_text("{not json")
        commit(self.repo, "a broken version")
        (self.folder / "records.json").write_text(json.dumps({"frozen": ["records/"]}))
        commit(self.repo, "repaired")
        partial = self.guard()
        self.assertEqual(partial.returncode, 4, partial.stdout)
        self.assertIn("could not be read", partial.stdout)
        verdict(partial, "records_guard", "check", "PARTIAL")


class InstructionPathsTest(RepoCase):
    """Every path an instruction file names exists, and the list of exceptions only shrinks, judged from git."""

    def setUp(self):
        super().setUp()
        (self.repo / "app" / "Billing").mkdir()
        (self.repo / "app" / "Billing" / "Invoice.php").write_text("<?php\n")
        self.agents = self.repo / "AGENTS.md"
        self.agents.write_text("# Rules\n\nThe exporter is `app/InvoiceExporter.php`; the guide is [here](docs/guide.md).\n")
        self.start = commit(self.repo, "instruction file")
        self.allow = self.folder / "instruction-paths.allow"

    def paths(self, *args):
        return run("instruction_paths.py", "--instructions", "AGENTS.md", "--instructions", "docs/", *args, cwd=self.repo)

    def test_a_path_that_does_not_exist_is_refused_and_one_that_does_passes(self):
        ok = self.paths()
        self.assertEqual(ok.returncode, 0, ok.stdout)
        verdict(ok, "instruction_paths", "check", "PASS")
        self.agents.write_text("# Rules\n\nThe exporter is `app/Gone.php`, see `docs/old-guide.md:12`.\n")
        bad = self.paths()
        self.assertEqual(bad.returncode, 1)
        self.assertIn("NEW    AGENTS.md:3  `app/Gone.php` does not exist", bad.stdout)
        self.assertIn("`docs/old-guide.md` does not exist", bad.stdout)
        verdict(bad, "instruction_paths", "check", "FAIL")

    def test_placeholders_links_prose_and_ignored_paths_are_read_as_the_source_reads_them(self):
        (self.repo / ".gitignore").write_text("vendor/\n")
        self.agents.write_text(
            "See `app/<Name>.php`, `app/{a,b}.php`, `$HOME/x/y`, `vendor/autoload.php`, glob `app/*.php`, "
            "[site](https://example.com/a/b.md), and `app/Missing/*.php`.\n"
            "Prose mention of app/Index.php and of app/Nowhere/Thing.php.\n"
            "```sh\nphp app/Billing/Invoice.php app/Billing/Gone.php\n```\n"
        )
        listed = [line.split()[1] for line in self.paths("--list").stdout.splitlines() if line.startswith("  AGENTS.md")]
        self.assertEqual(sorted(listed), ["app/Billing/Gone.php", "app/Missing/*.php", "app/Nowhere/Thing.php"])

    def test_where_paths_resolve_comes_from_the_arguments(self):
        self.agents.write_text("# Rules\n\nSee `Billing/Missing.php`.\n")
        self.assertEqual(self.paths().returncode, 0, "no known first folder: not read as a path")
        known = self.paths("--resolve-from", "app")
        self.assertEqual(known.returncode, 1)
        self.assertIn("`Billing/Missing.php`", known.stdout)
        self.agents.write_text("# Rules\n\nSee `Billing/Invoice.php`.\n")
        self.assertEqual(self.paths("--resolve-from", "app").returncode, 0)

    def test_instruction_files_and_resolve_from_can_live_in_the_state_folder(self):
        self.folder.mkdir(parents=True)
        self.folder.joinpath("instruction-paths.json").write_text(json.dumps({"instructions": ["AGENTS.md"], "resolve_from": ["app"]}))
        self.agents.write_text("# Rules\n\nSee `Billing/Missing.php`.\n")
        result = run("instruction_paths.py", "--folder", str(self.folder), cwd=self.repo)
        self.assertEqual(result.returncode, 1)
        self.assertIn("`Billing/Missing.php`", result.stdout)

    def test_the_allow_list_only_shrinks_judged_from_git(self):
        self.agents.write_text("# Rules\n\n`app/Gone.php` and `app/AlsoGone.php`.\n")
        base = commit(self.repo, "two dangling references")
        self.folder.mkdir(parents=True)
        created = run("instruction_paths.py", "--folder", str(self.folder), "--instructions", "AGENTS.md", "--write-allowlist", cwd=self.repo)
        self.assertEqual(created.returncode, 0, created.stderr)
        verdict(created, "instruction_paths", "write-allowlist", "PASS")
        self.assertEqual(run("instruction_paths.py", "--folder", str(self.folder), "--instructions", "AGENTS.md", "--write-allowlist", cwd=self.repo).returncode, 2, "never overwrites")
        commit(self.repo, "the commit that creates the list")
        args = ("--folder", str(self.folder), "--instructions", "AGENTS.md", "--base", base)
        listed = run("instruction_paths.py", *args, cwd=self.repo)
        self.assertEqual(listed.returncode, 0, listed.stdout)
        verdict(listed, "instruction_paths", "check", "PASS")

        self.agents.write_text("# Rules\n\n`app/Gone.php`, `app/AlsoGone.php` and `app/Third.php`.\n")
        self.allow.write_text(self.allow.read_text() + "AGENTS.md\tapp/Third.php\n")
        commit(self.repo, "list one more instead of fixing it")
        grew = run("instruction_paths.py", *args, cwd=self.repo)
        self.assertEqual(grew.returncode, 1)
        self.assertIn("GREW   commit", grew.stdout)
        self.assertIn("app/Third.php", grew.stdout)
        verdict(grew, "instruction_paths", "check", "FAIL")

        self.agents.write_text("# Rules\n\n`app/Gone.php`.\n")
        commit(self.repo, "fix two references, leave the list")
        stale = run("instruction_paths.py", *args, cwd=self.repo)
        self.assertIn("STALE  AGENTS.md  `app/AlsoGone.php` no longer dangles", stale.stdout)

    def test_a_listed_reference_that_is_fixed_demands_its_removal_and_a_shrink_passes(self):
        self.agents.write_text("# Rules\n\n`app/Gone.php` and `app/AlsoGone.php`.\n")
        base = commit(self.repo, "two dangling references")
        self.folder.mkdir(parents=True)
        run("instruction_paths.py", "--folder", str(self.folder), "--instructions", "AGENTS.md", "--write-allowlist", cwd=self.repo)
        commit(self.repo, "list them")
        self.agents.write_text("# Rules\n\n`app/Gone.php`.\n")
        self.allow.write_text("\n".join(l for l in self.allow.read_text().splitlines() if "AlsoGone" not in l) + "\n")
        commit(self.repo, "fix one and shrink the list")
        result = run("instruction_paths.py", "--folder", str(self.folder), "--instructions", "AGENTS.md", "--base", base, cwd=self.repo)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_the_base_comes_from_state_and_without_one_the_run_is_partial(self):
        self.agents.write_text("# Rules\n\n`app/Gone.php`.\n")
        commit(self.repo, "one dangling reference")
        self.folder.mkdir(parents=True)
        run("instruction_paths.py", "--folder", str(self.folder), "--instructions", "AGENTS.md", "--write-allowlist", cwd=self.repo)
        commit(self.repo, "list it")
        args = ("--folder", str(self.folder), "--instructions", "AGENTS.md")
        partial = run("instruction_paths.py", *args, cwd=self.repo)
        self.assertEqual(partial.returncode, 4, "the list cannot be judged from git without a base")
        verdict(partial, "instruction_paths", "check", "PARTIAL")
        run("refactor_state.py", "--folder", str(self.folder), "init", "--base", self.start, cwd=self.repo)
        from_state = run("instruction_paths.py", *args, "--base", cwd=self.repo)
        self.assertEqual(from_state.returncode, 0, from_state.stdout)

    def test_exit_codes_and_the_verdict_line(self):
        none = run("instruction_paths.py", cwd=self.repo)
        self.assertEqual(none.returncode, 2, "nothing says which files are instruction files")
        verdict(none, "instruction_paths", "check", "FAIL")
        nothing = run("instruction_paths.py", "--instructions", "nowhere/*.md", cwd=self.repo)
        self.assertEqual(nothing.returncode, 4, "no instruction file matched: nothing was read")
        verdict(nothing, "instruction_paths", "check", "PARTIAL")
        unknown = self.paths("--allow", str(self.allow), "--base", "0000000000000000000000000000000000000000")
        self.assertEqual(unknown.returncode, 0, "no allow file: no history to judge")
        self.folder.mkdir(parents=True)
        self.allow.write_text("AGENTS.md\tapp/X.php\n")
        commit(self.repo, "an allow file")
        bad = self.paths("--allow", str(self.allow), "--base", "0000000000000000000000000000000000000000")
        self.assertEqual(bad.returncode, 2)
        with tempfile.TemporaryDirectory() as outside:
            elsewhere = run("instruction_paths.py", "--instructions", "AGENTS.md", cwd=outside)
            self.assertEqual(elsewhere.returncode, 3)
            verdict(elsewhere, "instruction_paths", "check", "FAIL")

    def test_folders_the_harness_lock_pins_are_copies_of_the_core_and_skipped(self):
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "harness.lock").write_text(json.dumps({"paths": [".claude/skills/pinned"]}))
        (self.repo / ".claude" / "skills" / "pinned").mkdir(parents=True)
        (self.repo / ".claude" / "skills" / "pinned" / "SKILL.md").write_text("See `app/Gone.php`.\n")
        commit(self.repo, "a pinned skill")
        args = ("--instructions", ".claude/skills/")
        self.assertEqual(run("instruction_paths.py", *args, cwd=self.repo).returncode, 4, "skipped: nothing was read")
        self.assertEqual(run("instruction_paths.py", *args, "--include-vendored", cwd=self.repo).returncode, 1)


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
