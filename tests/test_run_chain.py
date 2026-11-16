"""The chain runs from the run profile: roles resolve to targets, the status keeps the order and
the caps, the brief carries what a child needs, and the orchestrator text runs the chain (S2)."""

import json
import re

from helpers import HarnessTestCase
from test_kickoff_profile import VALID_RUN, SkillProse, script

REFERENCES = ["module-opt-in.md", "naming-language.md", "production-safety.md", "qa-fixtures.md", "worktree-safe-commands.md"]
TIME_RE = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
ROLE_PROFILE = """repo_name: app
cmd_test_backend: make test
cmd_format_backend: make format
cmd_static_analysis: make analyse
cmd_test_frontend: none
delegate_tool: mcp__orchestrator__delegate_task
role_builder: personal sonnet high
role_verifier: personal opus high
role_judge: work fable high
role_qa: work haiku medium
role_reviewer: nobody opus high
"""
LOCAL_PROFILE = """account_personal: provider-personal-7
account_work: provider-work-3
model_sonnet: vendor-sonnet-9-9
model_opus: vendor-opus-9-9
model_fable: vendor-fable-9-9
"""


class RepoCase(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        (self.repo / ".claude" / "harness").mkdir(parents=True)

    def write_repo_profile(self, text=ROLE_PROFILE, local=LOCAL_PROFILE):
        harness = self.repo / ".claude" / "harness"
        (harness / "profile.yaml").write_text(text)
        if local is not None:
            (harness / "profile.local.yaml").write_text(local)

    def write_run(self, text=VALID_RUN, slug="invoice-export"):
        path = self.repo / ".specs" / "features" / slug / "run.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path


class RoleTargetTest(RepoCase):
    def setUp(self):
        super().setUp()
        self.write_repo_profile()

    def target(self, *args):
        return script("role_target.py", "--root", self.repo, *args)

    def test_role_line_resolves_provider_model_and_effort(self):
        proc = self.target("builder")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        target = json.loads(proc.stdout)
        self.assertEqual(
            (target["provider"], target["model"], target["effort"]), ("provider-personal-7", "vendor-sonnet-9-9", "high")
        )

    def test_each_missing_mapping_exits_2_naming_the_key(self):
        cases = {"fixer": "role_fixer", "reviewer": "account_nobody", "qa": "model_haiku"}
        for role, key in cases.items():
            with self.subTest(role=role):
                proc = self.target(role)
                self.assertEqual(proc.returncode, 2, proc.stdout)
                self.assertIn(key, proc.stderr)
                self.assertEqual(proc.stdout, "")

    def test_fable_needs_named_by_user(self):
        refused = self.target("judge")
        self.assertEqual(refused.returncode, 2, refused.stdout)
        self.assertIn("fable", refused.stderr)
        named = self.target("judge", "--named-by-user")
        self.assertEqual(named.returncode, 0, named.stderr)
        self.assertEqual(json.loads(named.stdout)["model"], "vendor-fable-9-9")

    def test_run_profile_role_line_wins_for_the_run(self):
        run = self.write_run(VALID_RUN.replace("role_builder: personal sonnet high", "role_builder: personal opus max"))
        target = json.loads(self.target("builder", "--run", run).stdout)
        self.assertEqual((target["model"], target["effort"]), ("vendor-opus-9-9", "max"))


class RunStatusTest(RepoCase):
    def setUp(self):
        super().setUp()
        self.run_path = self.write_run()
        self.status_path = self.run_path.parent / "status.json"

    def status(self, *args):
        return script("run_status.py", "--root", self.repo, *args)

    def ok(self, *args):
        proc = self.status(*args)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def walk_to(self, stage):
        """Start and finish every stage before `stage`."""
        for line in self.ok("show").stdout.splitlines():
            name, state = line.split()[:2]
            if name == stage:
                return
            if state == "pending":
                self.ok("start", name)
                self.ok("done", name)

    def shown(self):
        return {line.split()[0]: line for line in self.ok("show").stdout.splitlines()}

    def test_start_out_of_order_exits_3_and_changes_nothing(self):
        self.ok("start", "grilling", "--child", "orchestrator-1")
        self.ok("done", "grilling")
        before = self.status_path.read_bytes()
        for stage in ("build", "review", "grilling"):
            with self.subTest(stage=stage):
                proc = self.status("start", stage)
                self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
                self.assertEqual(self.status_path.read_bytes(), before)

    def test_verify_over_the_cap_exits_3_and_marks_capped(self):
        self.walk_to("verify")
        self.assertEqual(self.status("start", "verify").returncode, 0)
        self.ok("done", "verify")
        self.assertEqual(self.status("start", "verify").returncode, 0)
        self.ok("done", "verify")
        third = self.status("start", "verify")
        self.assertEqual(third.returncode, 3, third.stdout + third.stderr)
        self.assertEqual(self.shown()["verify"].split()[1], "capped")
        self.ok("start", "review")

    def test_none_and_zero_stages_are_skipped_and_never_start(self):
        text = VALID_RUN.replace("review: bugs-and-regressions", "review: none").replace("verify_rounds: 2", "verify_rounds: 0")
        self.write_run(text)
        self.walk_to("verify")
        shown = self.shown()
        for stage in ("verify", "review", "fix"):
            with self.subTest(stage=stage):
                self.assertEqual(shown[stage].split()[1], "skipped")
                proc = self.status("start", stage)
                self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.ok("start", "qa")

    def test_show_prints_one_line_per_stage_with_state_times_and_child(self):
        self.write_run(VALID_RUN.replace("review: bugs-and-regressions", "review: none").replace("verify_rounds: 2", "verify_rounds: 1"))
        self.walk_to("verify")
        self.ok("start", "verify", "--child", "verifier-7")
        self.assertEqual(self.status("start", "verify").returncode, 3)  # running: no second start
        self.ok("done", "verify")
        self.assertEqual(self.status("start", "verify").returncode, 3)  # one round: capped
        self.ok("start", "qa", "--child", "qa-2")
        lines = self.ok("show").stdout.splitlines()
        self.assertEqual([line.split()[0] for line in lines], [s.strip()[2:] for s in VALID_RUN.split("chain:\n")[1].splitlines()])
        shown = {line.split()[0]: line.split() for line in lines}
        expected = {
            "grilling": "done",
            "verify": "capped",
            "review": "skipped",
            "qa": "running",
            "finalize": "pending",
        }
        for stage, state in expected.items():
            with self.subTest(stage=stage):
                self.assertEqual(shown[stage][1], state)
        self.assertRegex(shown["verify"][2], TIME_RE)
        self.assertRegex(shown["verify"][3], TIME_RE)
        self.assertEqual(shown["verify"][4], "verifier-7")
        self.assertRegex(shown["qa"][2], TIME_RE)
        self.assertEqual((shown["qa"][3], shown["qa"][4]), ("-", "qa-2"))
        self.assertEqual(shown["finalize"][2:5], ["-", "-", "-"])

    def test_third_retry_of_a_stage_exits_3(self):
        self.ok("start", "grilling")
        self.assertEqual(self.status("retry", "grilling", "--child", "resume-1").returncode, 0)
        self.assertEqual(self.status("retry", "grilling", "--child", "resume-2").returncode, 0)
        before = self.status_path.read_bytes()
        third = self.status("retry", "grilling")
        self.assertEqual(third.returncode, 3, third.stdout + third.stderr)
        self.assertEqual(self.status_path.read_bytes(), before)
        self.assertIn("resume-2", self.shown()["grilling"])

    def test_unknown_stage_exits_2(self):
        for stage in ("deploy", "research"):
            with self.subTest(stage=stage):
                for command in ("start", "done", "retry"):
                    proc = self.status(command, stage)
                    self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                    self.assertIn(stage, proc.stderr)

    def test_no_or_invalid_run_profile_exits_2(self):
        self.write_run(VALID_RUN.replace("track: medium", "track: huge"))
        self.assertEqual(self.status("show").returncode, 2)
        self.run_path.unlink()
        self.assertEqual(self.status("show").returncode, 2)


class BriefTest(RepoCase):
    def setUp(self):
        super().setUp()
        self.write_repo_profile()
        references = self.repo / ".claude" / "harness" / "references"
        references.mkdir()
        for name in REFERENCES:
            (references / name).write_text("# Reference\n")

    def render(self, role="builder"):
        return script("brief.py", "--root", self.repo, "render", role)

    def test_brief_carries_profile_role_skill_references_gates_and_unattended_rule(self):
        self.write_run()
        proc = self.render("builder")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        brief = proc.stdout
        self.assertIn(".specs/features/invoice-export/run.yaml", brief)
        self.assertRegex(brief, r"Role: `builder`")
        self.assertRegex(brief, r"Skill to load: `tlc-spec-lean` \(`\.claude/skills/tlc-spec-lean/SKILL\.md`\)")
        for name in REFERENCES:
            with self.subTest(reference=name):
                self.assertIn(f".claude/harness/references/{name}", brief)
        for command in ("make test", "make format", "make analyse"):
            with self.subTest(gate=command):
                self.assertIn(f"`{command}`", brief)
        self.assertNotIn("cmd_test_frontend", brief)
        rule = re.search(r"Unattended rule.*", brief)
        self.assertIsNotNone(rule)
        self.assertIn("own-test-records", rule.group(0))
        self.assertRegex(rule.group(0), r"own test records")
        self.assertRegex(rule.group(0), r"Stop and ask before .*person or a live automation.*production.*deploys")

    def test_no_run_profile_exits_2(self):
        proc = self.render("builder")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(proc.stdout, "")
        self.assertIn("no run profile", proc.stderr)

    def test_each_role_names_its_skill(self):
        self.write_run()
        skills = {
            "verifier": "tlc-spec-lean",
            "reviewer": "cdv-code-review",
            "fixer": "cdv-apply-review",
            "qa": "cdv-qa",
            "research": "cdv-research-round",
        }
        for role, skill in skills.items():
            with self.subTest(role=role):
                self.assertIn(f"Skill to load: `{skill}`", self.render(role).stdout)
        self.assertEqual(self.render("deployer").returncode, 2)


class OrchestratorProseTest(SkillProse):
    def test_next_stage_starts_without_a_prompt(self):
        self.assertSentence(r"`plan-then-build`", r"`autonomous`", r"stage ends", r"next stage", r"without a prompt")

    def test_capped_verifier_items_go_to_the_pr_tagged(self):
        self.assertSentence(r"`capped`", r"open item", r"`defect`", r"`proof-gap`", r"pull request description")
        self.assertSentence(r"`capped`", r"(continue|go on) to the review")

    def test_stops_before_external_send_production_write_or_deploy(self):
        self.assertSentence(
            r"developer is away",
            r"stop and ask before",
            r"sends? (something )?to a person or a live automation",
            r"writes? in production",
            r"deploys?",
        )

    def test_one_way_door_switches_to_builder_risk(self):
        self.assertSentence(r"approved plan", r"one-way door", r"`builder_role: builder_risk`", r"before .*dispatch")

    def test_delegate_tool_none_runs_native_subagents_on_the_role_model(self):
        self.assertSentence(r"`profile\.delegate_tool`", r"`none`", r"native subagent", r"model of the role|role's model")
