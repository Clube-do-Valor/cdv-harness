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
