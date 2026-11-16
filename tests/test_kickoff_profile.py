"""cdv-kickoff: the signals become a proposed run profile, the run profile is validated, and the
skill holds the conversation around them (S1)."""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, HarnessTestCase

SCRIPTS = REPO_ROOT / "skills" / "cdv-kickoff" / "scripts"
SKILL = REPO_ROOT / "skills" / "cdv-kickoff" / "SKILL.md"

# A small request: every signal present, nothing that raises the track.
BASE_SIGNALS = {
    "feature": "invoice-export",
    "intent": "build",
    "files_estimate": 3,
    "migration": "none",
    "new_screen": False,
    "screen_audience_other": False,
    "changes_existing_screen": False,
    "appearance_decision": False,
    "external_integration": [],
    "access_kernel": False,
    "money_or_contract": False,
    "one_way_door": False,
    "repositories": 1,
    "main_checkout_free": True,
    "origin": "direct",
    "waiting_reply": False,
    "owner_must_validate": False,
    "no_precedent": False,
}
MEDIUM = {"files_estimate": 6}
BIG = {"files_estimate": 6, "repositories": 2}
TRACKS = {"small": {}, "medium": MEDIUM, "big": BIG}


def parse(text):
    """The flat run profile format, read independently of the scripts: scalars and `- item` lists."""
    values, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("- "):
            current.append(line[2:].strip())
            continue
        key, _sep, value = line.partition(":")
        value = value.strip()
        if value:
            values[key] = value
            current = None
        else:
            current = values[key] = []
    return values


def script(name, *args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *[str(a) for a in args]],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def sentences(text):
    """The skill's prose as sentences, bullets and table rows, code spans kept, formatting dropped."""
    text = re.sub(r"\*\*|__", "", text)
    parts = []
    for block in re.split(r"\n\s*\n|\n(?=\s*(?:[-*]|\d+\.|\|) )", text):
        block = " ".join(block.split())
        parts += [p for p in re.split(r"(?<=[.!?])\s+(?=[A-Z`(])", block) if p]
    return parts


class ProposeCase(HarnessTestCase):
    def propose(self, *answers, **overrides):
        signals = dict(BASE_SIGNALS, **overrides)
        args = ["--signals", json.dumps(signals)]
        for answer in answers:
            args += ["--answer", answer]
        proc = script("propose_profile.py", *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return parse(proc.stdout)

    def on_track(self, track, **overrides):
        return self.propose(**dict(TRACKS[track], **overrides))


class ProposeProfileTest(ProposeCase):
    def test_three_files_is_small(self):
        self.assertEqual(self.propose(files_estimate=3)["track"], "small")

    def test_four_files_is_medium(self):
        self.assertEqual(self.propose(files_estimate=4)["track"], "medium")

    def test_schema_migration_is_medium(self):
        self.assertEqual(self.propose(files_estimate=2, migration="schema")["track"], "medium")

    def test_new_screen_alone_is_medium(self):
        self.assertEqual(self.propose(files_estimate=2, new_screen=True)["track"], "medium")

    def test_each_big_signal_makes_the_track_big(self):
        cases = {
            "new screen for another audience": {"new_screen": True, "screen_audience_other": True},
            "external integration, one file": {"external_integration": ["crm"], "files_estimate": 1},
            "access kernel": {"access_kernel": True},
            "two repositories": {"repositories": 2},
            "data migration": {"migration": "data"},
        }
        for name, overrides in cases.items():
            with self.subTest(signal=name):
                self.assertEqual(self.propose(**overrides)["track"], "big")
        self.assertEqual(self.propose(migration="schema")["track"], "medium")

    def test_small_is_autonomous_without_planner(self):
        profile = self.on_track("small")
        self.assertEqual(profile["track"], "small")
        self.assertEqual((profile["mode"], profile["planner"]), ("autonomous", "none"))

    def test_medium_and_big_plan_then_build_with_tlc_spec_lean(self):
        for track in ("medium", "big"):
            with self.subTest(track=track):
                profile = self.on_track(track)
                self.assertEqual(profile["track"], track)
                self.assertEqual((profile["mode"], profile["planner"]), ("plan-then-build", "tlc-spec-lean"))

    def test_investigate_intent_wins_on_every_track(self):
        for track in TRACKS:
            with self.subTest(track=track):
                profile = self.on_track(track, intent="investigate")
                self.assertEqual(profile["track"], track)
                self.assertEqual(profile["mode"], "investigate")

    def test_each_risk_signal_picks_builder_risk_and_fault_injection(self):
        for signal in ("access_kernel", "money_or_contract", "one_way_door"):
            with self.subTest(signal=signal):
                profile = self.on_track("medium", **{signal: True})
                self.assertEqual((profile["builder_role"], profile["fault_injection"]), ("builder_risk", "true"))

    def test_no_risk_signal_picks_builder_without_fault_injection(self):
        for track in TRACKS:
            with self.subTest(track=track):
                profile = self.on_track(track)
                self.assertEqual((profile["builder_role"], profile["fault_injection"]), ("builder", "false"))

    def test_verify_rounds_follow_the_track(self):
        for track, rounds in (("small", "0"), ("medium", "2"), ("big", "3")):
            with self.subTest(track=track):
                profile = self.on_track(track)
                self.assertEqual((profile["track"], profile["verify_rounds"]), (track, rounds))

    def test_review_follows_the_track(self):
        for track, review in (("small", "none"), ("medium", "bugs-and-regressions"), ("big", "bugs-and-regressions")):
            with self.subTest(track=track):
                self.assertEqual(self.on_track(track)["review"], review)

    def test_qa_follows_the_screen_and_integration_signals(self):
        self.assertEqual(self.propose()["qa"], "none")
        self.assertEqual(self.propose(new_screen=True)["qa"], "browser-local")
        self.assertEqual(self.propose(changes_existing_screen=True)["qa"], "browser-local")
        self.assertEqual(self.propose(new_screen=True, external_integration=["crm"])["qa"], "browser-external-test-records")

    def test_workspace_main_only_when_free_and_not_big(self):
        cases = [("small", True, "main"), ("medium", True, "main"), ("big", True, "worktree"), ("medium", False, "worktree")]
        for track, free, workspace in cases:
            with self.subTest(track=track, free=free):
                profile = self.on_track(track, main_checkout_free=free)
                self.assertEqual((profile["track"], profile["workspace"]), (track, workspace))

    def test_builder_inline_for_small_child_otherwise(self):
        for track, builder in (("small", "inline"), ("medium", "child"), ("big", "child")):
            with self.subTest(track=track):
                self.assertEqual(self.on_track(track)["builder"], builder)

    def test_optional_steps_follow_their_signals(self):
        cases = [
            ({"origin": "chat-thread"}, "slack-draft"),
            ({"waiting_reply": True}, "slack-draft"),
            ({"appearance_decision": True}, "mock-before-after"),
            ({"changes_existing_screen": True}, "mock-before-after"),
            ({"new_screen": True, "screen_audience_other": True}, "blind-judges"),
            ({"owner_must_validate": True}, "validation-page"),
        ]
        for overrides, step in cases:
            with self.subTest(signal=overrides):
                self.assertEqual(self.propose(**overrides)["optional"], [step])
        for track in TRACKS:
            with self.subTest(track=track, signal=None):
                self.assertEqual(self.on_track(track)["optional"], [])

    def test_stops_follow_the_mode(self):
        self.assertEqual(self.on_track("medium")["stops"], ["plan-approval", "external-write", "production-write"])
        self.assertEqual(self.on_track("small")["stops"], ["external-write", "production-write"])
        self.assertEqual(self.on_track("medium", intent="investigate")["stops"], ["report"])
        for track in TRACKS:
            with self.subTest(track=track, mode="step-by-step"):
                profile = self.propose("mode=step-by-step", **TRACKS[track])
                self.assertEqual(profile["mode"], "step-by-step")
                self.assertGreater(len(profile["chain"]), 5)
                self.assertEqual(profile["stops"], profile["chain"])

    def test_unattended_is_always_own_test_records(self):
        for track in TRACKS:
            for intent in ("build", "investigate"):
                with self.subTest(track=track, intent=intent):
                    self.assertEqual(self.on_track(track, intent=intent)["unattended"], "own-test-records")

    def test_research_first_only_when_big_without_precedent(self):
        def first_stages(**overrides):
            proc = script("propose_profile.py", "--signals", json.dumps(dict(BASE_SIGNALS, **overrides)))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            repo = self.tmp / f"repo-{len(list(self.tmp.iterdir()))}"
            run_yaml = repo / ".specs" / "features" / "invoice-export" / "run.yaml"
            run_yaml.parent.mkdir(parents=True)
            run_yaml.write_text(proc.stdout)
            show = script("run_status.py", "--root", repo, "show")
            self.assertEqual(show.returncode, 0, show.stderr)
            return [line.split()[0] for line in show.stdout.splitlines()]

        stages = first_stages(no_precedent=True, **BIG)
        self.assertEqual(stages[0], "research")
        self.assertNotIn("research", first_stages(no_precedent=False, **BIG))
        medium = first_stages(no_precedent=True, **MEDIUM)
        self.assertNotIn("research", medium)
        self.assertIn("build", medium)

    def test_missing_or_bad_signal_exits_2_naming_the_key(self):
        signals = dict(BASE_SIGNALS)
        del signals["files_estimate"]
        proc = script("propose_profile.py", "--signals", json.dumps(signals))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("files_estimate", proc.stderr)
        self.assertEqual(proc.stdout, "")
        proc = script("propose_profile.py", "--signals", json.dumps(dict(BASE_SIGNALS, migration="sometimes")))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("migration", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_answer_track_derives_the_keys_that_follow(self):
        profile = self.propose("track=big")
        self.assertEqual(
            (profile["track"], profile["mode"], profile["verify_rounds"], profile["workspace"]),
            ("big", "plan-then-build", "3", "worktree"),
        )
        bad = script("propose_profile.py", "--signals", json.dumps(BASE_SIGNALS), "--answer", "track=huge")
        self.assertEqual(bad.returncode, 2)
        self.assertIn("track", bad.stderr)


VALID_RUN = """schema: 1
feature: invoice-export
track: medium
mode: plan-then-build
planner: tlc-spec-lean
workspace: main
builder: child
builder_role: builder
verify_rounds: 2
fault_injection: false
review: bugs-and-regressions
qa: browser-local
unattended: own-test-records
role_builder: personal sonnet high
optional:
  - mock-before-after
stops:
  - plan-approval
  - external-write
  - production-write
chain:
  - grilling
  - plan
  - build
  - verify
  - review
  - fix
  - qa
  - finalize
  - watch
  - ticket
"""


class RunProfileTest(HarnessTestCase):
    def validate(self, text):
        path = self.tmp / "run.yaml"
        path.write_text(text)
        return script("run_profile.py", "validate", path)

    def test_validate_rejects_each_bad_line_naming_the_key(self):
        cases = {
            "unknown key": ("deadline: friday\n", None, "deadline"),
            "track outside its set": (None, ("track: medium", "track: huge"), "track"),
            "verify_rounds over 3": (None, ("verify_rounds: 2", "verify_rounds: 4"), "verify_rounds"),
            "inherit role": (None, ("role_builder: personal sonnet high", "role_builder: personal inherit high"), "role_builder"),
        }
        for name, (extra, swap, key) in cases.items():
            with self.subTest(case=name):
                text = VALID_RUN + extra if extra else VALID_RUN.replace(*swap)
                proc = self.validate(text)
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                problems = proc.stdout.splitlines()
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(f": {key}: ", problems[0])

    def test_validate_accepts_a_valid_file(self):
        proc = self.validate(VALID_RUN)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_every_proposal_validates(self):
        for overrides in ({}, MEDIUM, BIG, dict(BIG, no_precedent=True), {"intent": "investigate"}):
            with self.subTest(signals=overrides):
                proc = script("propose_profile.py", "--signals", json.dumps(dict(BASE_SIGNALS, **overrides)))
                self.assertEqual(proc.returncode, 0, proc.stderr)
                result = self.validate(proc.stdout)
                self.assertEqual(result.returncode, 0, result.stdout)

    def test_missing_key_and_chain_out_of_order_are_invalid(self):
        proc = self.validate(VALID_RUN.replace("qa: browser-local\n", ""))
        self.assertEqual(proc.returncode, 1)
        self.assertIn(": qa: missing key", proc.stdout)
        proc = self.validate(VALID_RUN.replace("  - build\n  - verify\n", "  - verify\n  - build\n"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn(": chain: ", proc.stdout)


class SkillProse(unittest.TestCase):
    def assertSentence(self, *patterns):
        """Some one sentence of the skill holds every pattern."""
        regexes = [re.compile(p, re.I) for p in patterns]
        found = [s for s in sentences(SKILL.read_text(encoding="utf-8")) if all(r.search(s) for r in regexes)]
        self.assertTrue(found, f"no sentence of {SKILL.name} holds all of {patterns}")
        return found


class KickoffSkillTest(SkillProse):
    def test_small_track_states_one_line_and_asks_nothing(self):
        self.assertSentence(r"small track", r"one line", r"(asks?|ask) no question|no question")

    def test_medium_and_big_ask_one_screen_of_four_questions_at_most(self):
        self.assertSentence(r"medium or big track", r"one question screen", r"at most four questions")
        self.assertSentence(r"recommended option", r"proposed value")
        self.assertSentence(r"each option", r"consequence")

    def test_writes_the_profile_and_gates_on_validate(self):
        self.assertSentence(r"screen is answered|answers? (on|of) the screen", r"writes? the run profile")
        self.assertSentence(r"no stage", r"`run_profile\.py validate[^`]*`", r"exits? `?0`?")

    def test_signals_are_filled_never_a_default_decided_here(self):
        self.assertSentence(r"never decides? a (default|value)", r"propose_profile\.py")


if __name__ == "__main__":
    unittest.main()
