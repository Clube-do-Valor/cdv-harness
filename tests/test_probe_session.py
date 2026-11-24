"""The headless probe's session (tests/probe_hooks_headless.py) as it calls the CLI: a fake `claude`
that prints the arguments it was given, and its `card-check` case fed recorded streams (synthetic), so
no real session runs here."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import probe_hooks_headless as probe

FAKE_CLAUDE = ("#!{python}\nimport json, os, sys\n"
               "print(json.dumps({{'argv': sys.argv[1:], 'memory': os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY')}}))\n")

INIT = {"type": "system", "subtype": "init", "permissionMode": "bypassPermissions"}
FINDING = {"type": "system", "subtype": "hook_response", "hook_event": "PostToolUse", "exit_code": 2,
           "stderr": "card-check: <url> is outside the card contract:\nrequest-zone: no zone. Write it"}
API_ERROR = {"type": "result", "subtype": "success", "is_error": True, "result": "API Error: 529\noverloaded " + "x" * 300}
DONE = {"type": "result", "subtype": "success", "is_error": False, "result": "DONE"}


def called(command):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": command}}]}}


def replied(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


WRITE = called(f"{probe.CLIENT} update KEY --set 'Status=In progress'")
GOOD = [INIT, WRITE, FINDING, replied("card-check: <url> is outside the card contract"), DONE]


def ended(events, code=0, stderr=""):
    """(process, events) as `session` returns them."""
    return subprocess.CompletedProcess(["claude"], code, "", stderr), events


class ProbeSessionTest(unittest.TestCase):
    def test_the_probe_session_saves_nothing_and_loads_no_user_settings(self):
        tmp = Path(tempfile.mkdtemp(prefix="probe-session-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        claude = tmp / "claude"
        claude.write_text(FAKE_CLAUDE.format(python=sys.executable))
        claude.chmod(0o755)
        proc, events = probe.session(str(claude), tmp, "reply with pong", "haiku", "--include-hook-events")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        argv = events[0]["argv"]
        self.assertEqual(argv[:2], ["-p", "reply with pong"])
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project,local")
        self.assertEqual(argv[-1], "--include-hook-events")
        self.assertEqual(argv.count("--setting-sources"), 1)
        # Without it the CLI still makes the project's auto-memory folder under the config dir
        self.assertEqual(events[0]["memory"], "1")


class CardCaseTest(unittest.TestCase):
    def run_card(self, *sessions):
        """((passed?, the line's detail), how many sessions ran) of the case over these sessions, in turn."""
        left = list(sessions)
        with mock.patch("builtins.print") as said:
            judged = probe.run_card(lambda: left.pop(0))
        self.said = " ".join(str(call.args[0]) for call in said.call_args_list)
        return judged, len(sessions) - len(left)

    def test_a_case_that_cannot_be_judged_says_what_the_session_answered(self):
        self.assertEqual(probe.judge_card(*ended(GOOD))[0], True)
        no_call, other, failed = ([INIT, API_ERROR], [INIT, called("ls"), DONE], [])
        for name, answer, needles in (
            ("the API failed", ended(no_call, 1, "warning\nthe last line\n"),
             (f"the session made no call of {probe.CLIENT}", "result success, is_error True: API Error: 529 overloaded x",
              "exit code 1", "stderr: the last line")),
            ("another call", ended(other), ("(tool calls: ['Bash'])", "result success, is_error False: DONE", "exit code 0", "stderr: empty")),
            ("it never started", ended(failed, 127, "claude: not logged in"),
             ("the session's permission mode is None", "no result in the stream", "exit code 127", "stderr: claude: not logged in")),
        ):
            with self.subTest(session=name):
                passed, line = probe.judge_card(*answer)
                self.assertFalse(passed)
                self.assertEqual(len(line.splitlines()), 1)
                for needle in needles:
                    self.assertIn(needle, line)
        line = probe.judge_card(*ended(no_call))[1]
        self.assertIn("overloaded " + "x" * 174 + ";", line)  # the first 200 characters of the result
        # What the session answered is not said of a case that was judged
        for events in ([INIT, WRITE, DONE], [INIT, WRITE, dict(FINDING, exit_code=0), DONE], [INIT, WRITE, FINDING, replied("NONE"), DONE]):
            with self.subTest(judged=events):
                passed, line = probe.judge_card(*ended(events, 1, "noise"))
                self.assertFalse(passed)
                self.assertNotIn("the session answered", line)

    def test_a_session_is_run_once_more_only_when_it_made_no_tool_call(self):
        nothing, silent = ended([INIT, API_ERROR], 1, "lost"), ended([INIT, WRITE, DONE])
        self.assertEqual(self.run_card(nothing, ended(GOOD))[0][0], True)
        self.assertIn("run once more", self.said)
        self.assertIn("API Error: 529", self.said)  # the first session's answer is not lost
        judged, ran = self.run_card(nothing, ended([], 1, "lost again"), ended(GOOD))
        self.assertEqual((judged[0], ran), (False, 2))  # once, not until it passes
        self.assertIn("stderr: lost again", judged[1])
        for name, first in (("the hook gave no finding", silent), ("another call", ended([INIT, called("ls"), DONE])),
                            ("the finding was not quoted", ended([INIT, WRITE, FINDING, DONE])), ("it passed", ended(GOOD))):
            with self.subTest(first=name):
                judged, ran = self.run_card(first, ended(GOOD))
                self.assertEqual((ran, self.said), (1, ""))
                self.assertEqual(judged, probe.judge_card(*first))
        judged, ran = self.run_card(nothing, silent, ended(GOOD))
        self.assertEqual((judged, ran), ((False, "card-check gave no PostToolUse response with a finding"), 2))

    def test_a_session_that_hangs_is_judged_by_what_it_had_said(self):
        for said, needle in ((None, "the session's permission mode is None"),
                             ("\n".join(map(json.dumps, (INIT, WRITE))).encode(), "card-check gave no PostToolUse response")):
            late = subprocess.TimeoutExpired(["claude"], probe.SESSION_SECONDS, output=said, stderr=b"no route to the API\n")
            with self.subTest(said=said), mock.patch.object(probe.subprocess, "run", side_effect=late) as run:
                proc, events = probe.session("claude", ".", "reply with pong", "haiku")
                self.assertEqual(run.call_args.kwargs["timeout"], probe.SESSION_SECONDS)
                line = probe.judge_card(proc, events)[1]
                self.assertIn(needle, line)
                if said is None:
                    self.assertIn(f"exit code none, stopped after {probe.SESSION_SECONDS} s; stderr: no route to the API", line)


if __name__ == "__main__":
    unittest.main()
