"""cdv-qa: the agent tests in the browser, records each step with qa_report.py, keeps the external
test records it creates in qa_manifest.py, and the skill says how (S4, C88)."""

import re
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, HarnessTestCase
from test_kickoff_profile import sentences

SCRIPTS = REPO_ROOT / "skills" / "cdv-qa" / "scripts"
SKILL = REPO_ROOT / "skills" / "cdv-qa" / "SKILL.md"
STEP_FIELDS = ["what", "expected", "result", "screenshot"]
RECORD_FIELDS = ["system", "type", "id"]


def script(name, *args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


class RunFolderCase(HarnessTestCase):
    """A repository with one run profile and no plan, so the work folder is RUN-invoice-export/."""

    def setUp(self):
        super().setUp()
        self.root = self.tmp / "repo"
        self.root.mkdir()
        (self.root / "RUN-invoice-export.yaml").write_text("schema: 1\nfeature: invoice-export\n")
        self.shots = self.root / "RUN-invoice-export" / "shots"
        self.shots.mkdir(parents=True)

    def shot(self, name):
        path = self.shots / name
        path.write_bytes(b"\x89PNG fake")
        return path.relative_to(self.root).as_posix()


class QaReportTest(RunFolderCase):
    def step(self, **fields):
        values = {
            "what": "Open the invoice list",
            "expected": "The export button shows",
            "result": "pass",
            "screenshot": self.shot("step-1.png"),
        }
        values.update(fields)
        args = []
        for key, value in values.items():
            if value is not None:
                args += [f"--{key}", value]
        return script("qa_report.py", "add", "--root", self.root, *args)

    def test_add_requires_each_field_and_names_the_missing_one(self):
        for field in STEP_FIELDS:
            with self.subTest(missing=field):
                proc = self.step(**{field: None})
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn(field, proc.stderr)
        self.assertEqual(script("qa_report.py", "render", "--root", self.root).stdout, "")

    def test_add_accepts_only_pass_or_fail(self):
        proc = self.step(result="maybe")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("result", proc.stderr)
        for result in ("pass", "fail"):
            with self.subTest(result=result):
                self.assertEqual(self.step(result=result).returncode, 0)

    def test_render_prints_one_line_per_step_in_order_with_an_image_link(self):
        first = self.shot("list.png")
        second = self.shot("export.png")
        self.assertEqual(self.step(what="Open the invoice list", expected="Twelve rows", result="pass", screenshot=first).returncode, 0)
        self.assertEqual(
            self.step(what="Click Export", expected="A CSV downloads", result="fail", screenshot=second).returncode, 0
        )
        proc = script("qa_report.py", "render", "--root", self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2, proc.stdout)
        for line, (what, expected, result, path) in zip(
            lines,
            [("Open the invoice list", "Twelve rows", "pass", first), ("Click Export", "A CSV downloads", "fail", second)],
        ):
            self.assertIn(what, line)
            self.assertIn(expected, line)
            self.assertRegex(line, rf"\b{result}\b")
            self.assertRegex(line, r"!\[[^\]]*\]\(" + re.escape(path) + r"\)")

    def test_render_encodes_a_screenshot_path_with_a_space_or_a_parenthesis(self):
        spaced = self.shot("Screenshot 2026-11-16 at 10.00.00.png")
        paren = self.shot("step (2).png")
        self.assertEqual(self.step(what="Open the list", screenshot=spaced).returncode, 0)
        self.assertEqual(self.step(what="Click Export", screenshot=paren).returncode, 0)
        proc = script("qa_report.py", "render", "--root", self.root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        first, second = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertTrue(
            first.endswith("![step 1](RUN-invoice-export/shots/Screenshot%202026-11-16%20at%2010.00.00.png)"), first
        )
        self.assertTrue(second.endswith("![step 2](RUN-invoice-export/shots/step%20%282%29.png)"), second)

    def test_add_refuses_a_screenshot_that_does_not_exist(self):
        proc = self.step(screenshot="RUN-invoice-export/shots/missing.png")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("screenshot", proc.stderr)

    def test_no_run_profile_and_no_dir_exits_2(self):
        bare = self.tmp / "bare"
        bare.mkdir()
        proc = script("qa_report.py", "render", "--root", bare)
        self.assertEqual(proc.returncode, 2)

    def test_dir_names_the_work_folder(self):
        folder = self.tmp / "elsewhere"
        shot = self.shot("dir.png")
        args = ["--what", "Open", "--expected", "Opens", "--result", "pass", "--screenshot", shot]
        self.assertEqual(script("qa_report.py", "add", "--root", self.root, "--dir", folder, *args).returncode, 0)
        self.assertTrue(any(folder.iterdir()))
        self.assertIn("Open", script("qa_report.py", "render", "--root", self.root, "--dir", folder).stdout)


class QaManifestTest(RunFolderCase):
    def manifest(self, *args):
        return script("qa_manifest.py", *args, "--root", self.root)

    def test_pending_lists_only_records_not_done(self):
        self.assertEqual(self.manifest("add", "--system", "crm", "--type", "deal", "--id", "9001").returncode, 0)
        self.assertEqual(self.manifest("add", "--system", "crm", "--type", "contact", "--id", "9002").returncode, 0)
        self.assertEqual(self.manifest("done", "--system", "crm", "--type", "deal", "--id", "9001").returncode, 0)
        proc = self.manifest("pending")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, proc.stdout)
        self.assertIn("9002", lines[0])
        self.assertIn("contact", lines[0])
        self.assertIn("crm", lines[0])
        self.assertNotIn("9001", proc.stdout)

    def test_pending_with_nothing_added_prints_nothing(self):
        proc = self.manifest("pending")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_add_requires_system_type_and_id(self):
        values = {"system": "crm", "type": "deal", "id": "9001"}
        for field in RECORD_FIELDS:
            with self.subTest(missing=field):
                args = []
                for key, value in values.items():
                    if key != field:
                        args += [f"--{key}", value]
                proc = self.manifest("add", *args)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn(field, proc.stderr)
        self.assertEqual(self.manifest("pending").stdout, "")

    def test_the_real_id_replaces_the_name_registered_before_creation(self):
        name = "QA-TEST invoice deal"
        self.assertEqual(self.manifest("add", "--system", "crm", "--type", "deal", "--id", name).returncode, 0)
        self.assertEqual(
            self.manifest("add", "--system", "crm", "--type", "deal", "--id", "9001", "--name", name).returncode, 0
        )
        lines = self.manifest("pending").stdout.splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("9001", lines[0])
        self.assertEqual(self.manifest("done", "--system", "crm", "--type", "deal", "--id", "9001").returncode, 0)
        self.assertEqual(self.manifest("pending").stdout, "")

    def test_done_of_an_unknown_record_exits_2(self):
        proc = self.manifest("done", "--system", "crm", "--type", "deal", "--id", "404")
        self.assertEqual(proc.returncode, 2)


class QaSkillTest(unittest.TestCase):
    def assertSentence(self, *patterns):
        regexes = [re.compile(p, re.I) for p in patterns]
        found = [s for s in sentences(SKILL.read_text(encoding="utf-8")) if all(r.search(s) for r in regexes)]
        self.assertTrue(found, f"no sentence of cdv-qa/SKILL.md holds all of {patterns}")
        return found

    def test_qa_drives_the_browser_and_reports_through_qa_report(self):
        self.assertSentence(r"\bdrives? the browser\b", r"yourself|itself", r"never (asks?|hands?|tells?) the developer")
        self.assertSentence(r"\bevery step\b", r"`qa_report\.py add[^`]*`")
        self.assertSentence(r"output of `qa_report\.py render`", r"final report")

    def test_external_records_are_registered_marked_and_deleted(self):
        self.assertSentence(
            r"`qa: browser-external-test-records`",
            r"register",
            r"`qa_manifest\.py add[^`]*`",
            r"before (you )?creat(e|ing) it",
        )
        self.assertSentence(r"\bnamed?\b", r"`?profile\.qa_test_marker`?", r"record")
        self.assertSentence(r"delete every pending record", r"\bend\b", r"`qa_manifest\.py pending`")

    def test_undeletable_record_is_listed_with_system_type_and_id(self):
        self.assertSentence(r"cannot be deleted", r"final report", r"\bsystem\b", r"\btype\b", r"\bid\b")

    def test_external_change_names_automations_and_stops_before_a_person(self):
        self.assertSentence(
            r"changes? an external record",
            r"name the automations",
            r"trigger",
            r"a person or a live automation",
            r"stop and ask",
        )

    def test_step_by_step_hands_each_step_to_the_developer(self):
        self.assertSentence(r"`step-by-step`", r"hand each step to the developer", r"record (their|the developer's) answer as the result")

    def test_worktree_starts_the_side_stack_or_asks_to_bring_the_branch(self):
        self.assertSentence(r"`workspace: worktree`", r"start `profile\.qa_side_stack_script`")
        self.assertSentence(r"final report", r"address", r"login link")
        self.assertSentence(
            r"`profile\.qa_side_stack_script` is `none`|that key is `none`", r"ask", r"bring the branch to the main checkout"
        )


if __name__ == "__main__":
    unittest.main()
