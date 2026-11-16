"""The pull request is watched and delivered: watch_pipeline.py against fake PR clients, and the
delivery prose of cdv-finalize, cdv-notion-ticket, cdv-rollout and cdv-kickoff (S5)."""

import json
import re
import subprocess
import sys
import time
import unittest

from helpers import REPO_ROOT, HarnessTestCase
from test_kickoff_profile import sentences

WATCH = REPO_ROOT / "skills" / "cdv-finalize" / "scripts" / "watch_pipeline.py"

# A fake `gh`: `run list` and `run view` answer from the JSON state file named by $FAKE_PR_STATE.
FAKE_GH = """#!{python}
import json, os, sys
state = json.load(open(os.environ["FAKE_PR_STATE"]))
args = sys.argv[1:]
with open(os.environ["FAKE_PR_STATE"] + ".calls", "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["run", "list"]:
    print(json.dumps(state["runs"]))
elif args[:2] == ["run", "view"]:
    print(json.dumps({{"jobs": state["jobs"].get(args[2], [])}}))
else:
    sys.exit("fake gh: unexpected " + " ".join(args))
"""

# A fake Bitbucket-style client: `pipelines --branch B` lines, `pipelines --steps N` tab-separated.
FAKE_BB = """#!{python}
import json, os, sys
args = sys.argv[1:]
if args == ["--help"]:
    print("usage: bb {{pr,pipelines,auth}} ...")
    sys.exit(0)
state = json.load(open(os.environ["FAKE_PR_STATE"]))
if args[:1] == ["pipelines"] and "--steps" in args:
    for step in state["steps"]:
        print("\\t".join(step))
elif args[:1] == ["pipelines"]:
    for line in state["runs"]:
        print(line)
else:
    sys.exit("fake bb: unexpected " + " ".join(args))
"""

# A PR client with no pipelines command.
FAKE_PLAIN = """#!{python}
import sys
if sys.argv[1:] == ["--help"]:
    print("usage: prcli {{pr,auth}} ...\\n  pr create   open a pull request\\n  auth login  store a token")
    sys.exit(0)
sys.exit(2)
"""


class WatchPipelineTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "repo"
        (self.root / ".claude" / "harness").mkdir(parents=True)
        self.state = self.tmp / "pr-state.json"

    def client(self, name, body, state=None):
        path = self.bin_dir / name
        path.write_text(body.format(python=sys.executable))
        path.chmod(0o755)
        (self.root / ".claude" / "harness" / "profile.yaml").write_text(f"pr_cli: {path}\n")
        if state is not None:
            self.state.write_text(json.dumps(state))
        return path

    def watch(self, *args, timeout="20"):
        env = dict(self.env, FAKE_PR_STATE=str(self.state))
        return subprocess.run(
            [sys.executable, str(WATCH), "--root", str(self.root), "--branch", "feat/invoice-export",
             "--timeout", timeout, "--interval", "0.2", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def gh_run(self, status, conclusion="", sha="a1b2c3d4e5f6"):
        return {"databaseId": 7, "headSha": sha, "status": status, "conclusion": conclusion, "workflowName": "ci"}

    def test_successful_run_exits_0(self):
        self.client("gh", FAKE_GH, {"runs": [self.gh_run("completed", "success")], "jobs": {}})
        proc = self.watch()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("green", proc.stdout.splitlines()[-1])

    def test_failed_run_exits_1_naming_the_failed_step(self):
        jobs = {
            "7": [
                {"name": "tests", "conclusion": "failure", "steps": [
                    {"name": "Set up job", "conclusion": "success"},
                    {"name": "Run unit tests", "conclusion": "failure"},
                    {"name": "Upload report", "conclusion": "skipped"},
                ]}
            ]
        }
        self.client("gh", FAKE_GH, {"runs": [self.gh_run("completed", "failure")], "jobs": jobs})
        proc = self.watch()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        last = proc.stdout.splitlines()[-1]
        self.assertIn("red", last)
        self.assertIn("Run unit tests", last)
        self.assertNotIn("Set up job", last)

    def test_no_terminal_state_before_the_timeout_exits_3(self):
        self.client("gh", FAKE_GH, {"runs": [self.gh_run("in_progress")], "jobs": {}})
        started = time.monotonic()
        proc = self.watch(timeout="1")
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertLess(time.monotonic() - started, 10)

    def test_client_without_pipelines_exits_2(self):
        self.client("prcli", FAKE_PLAIN)
        proc = self.watch()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("pipelines", proc.stderr)

    def test_missing_or_none_pr_cli_exits_2(self):
        for text in ("", "pr_cli: none\n"):
            with self.subTest(profile=text):
                (self.root / ".claude" / "harness" / "profile.yaml").write_text(text)
                self.assertEqual(self.watch().returncode, 2)

    def test_runs_of_another_commit_are_not_read(self):
        self.client("gh", FAKE_GH, {"runs": [self.gh_run("completed", "failure", sha="0ldc0mm17")], "jobs": {}})
        proc = self.watch("--commit", "a1b2c3d4e5f6", timeout="1")
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)

    def test_one_red_workflow_of_the_commit_makes_it_red(self):
        runs = [self.gh_run("completed", "success"), dict(self.gh_run("completed", "failure"), databaseId=8, workflowName="lint")]
        jobs = {"8": [{"name": "lint", "conclusion": "failure", "steps": [{"name": "Static analysis", "conclusion": "failure"}]}]}
        self.client("gh", FAKE_GH, {"runs": runs, "jobs": jobs})
        proc = self.watch()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Static analysis", proc.stdout.splitlines()[-1])

    def test_bitbucket_style_client_green_and_red(self):
        self.client("bb", FAKE_BB, {"runs": ["#41 COMPLETED SUCCESSFUL feat/invoice-export a1b2c3d4e"], "steps": []})
        self.assertEqual(self.watch().returncode, 0)
        self.state.write_text(json.dumps({
            "runs": ["#42 COMPLETED FAILED feat/invoice-export a1b2c3d4e"],
            "steps": [["COMPLETED", "SUCCESSFUL", "Build"], ["COMPLETED", "FAILED", "Run unit tests"]],
        }))
        proc = self.watch()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("Run unit tests", proc.stdout.splitlines()[-1])
        self.state.write_text(json.dumps({"runs": ["#43 IN_PROGRESS  feat/invoice-export a1b2c3d4e"], "steps": []}))
        self.assertEqual(self.watch(timeout="1").returncode, 3)


class BitbucketClientTest(unittest.TestCase):
    """The bundled client's `pipelines --steps`, with its API call replaced (no network)."""

    def test_pipelines_steps_prints_state_result_and_name(self):
        import contextlib
        import importlib.machinery
        import importlib.util
        import io

        path = REPO_ROOT / "skills" / "cdv-open-pr" / "scripts" / "bb"
        loader = importlib.machinery.SourceFileLoader("bb_client", str(path))
        spec = importlib.util.spec_from_loader("bb_client", loader)
        bb = importlib.util.module_from_spec(spec)
        writes = sys.dont_write_bytecode
        sys.dont_write_bytecode = True  # no __pycache__ beside the vendored client
        try:
            loader.exec_module(bb)
        finally:
            sys.dont_write_bytecode = writes
        asked = []

        def fake_call(method, api_path, body=None, header=None):
            asked.append(api_path)
            if api_path.startswith("/pipelines/?"):
                return {"values": [{"build_number": 42, "uuid": "{abc-1}"}, {"build_number": 41, "uuid": "{abc-0}"}]}
            return {"values": [
                {"name": "Build", "state": {"name": "COMPLETED", "result": {"name": "SUCCESSFUL"}}},
                {"name": "Run unit tests", "state": {"name": "COMPLETED", "result": {"name": "FAILED"}}},
            ]}

        bb.call = fake_call
        out = io.StringIO()
        argv = sys.argv
        sys.argv = ["bb", "pipelines", "--steps", "42"]
        try:
            with contextlib.redirect_stdout(out):
                bb.main()
        finally:
            sys.argv = argv
        self.assertEqual(out.getvalue().splitlines(), ["COMPLETED\tSUCCESSFUL\tBuild", "COMPLETED\tFAILED\tRun unit tests"])
        self.assertEqual(asked[-1], "/pipelines/%7Babc-1%7D/steps/")


def skill_sentences(name):
    return sentences((REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8"))


class DeliveryProseTest(unittest.TestCase):
    def assertSentence(self, skill, *patterns):
        regexes = [re.compile(p, re.I) for p in patterns]
        found = [s for s in skill_sentences(skill) if all(r.search(s) for r in regexes)]
        self.assertTrue(found, f"no sentence of {skill}/SKILL.md holds all of {patterns}")
        return found

    def test_red_pipeline_is_fixed_in_the_same_pr_twice_at_most(self):
        self.assertSentence(
            "cdv-finalize",
            r"pipeline is red",
            r"fix the failure",
            r"same pull request",
            r"watch (it )?again",
            r"at most twice",
            r"report the status (it|the pipeline) ended on",
        )

    def test_ticket_follows_the_three_recent_cards_links_both_ways_and_sets_pr_open(self):
        self.assertSentence(
            "cdv-notion-ticket",
            r"`profile\.ticket_system` is not `none`",
            r"pull request exists",
            r"create or update the card",
            r"layout of the three most recent cards of the same project",
            r"link the pull request both ways",
            r"`profile\.ticket_status_pr_open`",
        )

    def test_rollout_sets_merged_or_deployed_and_asks_one_step_per_question(self):
        self.assertSentence(
            "cdv-rollout", r"\bmerged\b", r"`profile\.ticket_status_merged`", r"\bdeployed\b", r"`profile\.ticket_status_deployed`"
        )
        self.assertSentence("cdv-rollout", r"production steps", r"not automatic", r"one per question")

    def test_big_track_plan_goes_to_the_ticket_system_not_a_commit(self):
        self.assertSentence(
            "cdv-kickoff",
            r"big track",
            r"approved plan",
            r"page under the project",
            r"ticket system",
            r"never add it to a commit",
        )


if __name__ == "__main__":
    unittest.main()
