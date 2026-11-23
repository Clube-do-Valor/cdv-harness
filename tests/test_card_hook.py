"""The card-check hook (hooks/card-check) as the host runs it: a subprocess fed the PostToolUse or
PostToolUseFailure JSON on stdin.

A temporary `.claude/` holds the real hook, the real checker and, at the client's path, a fake
cdv-notion client: the real client over a fake Notion kept in a JSON state file, whose requests are
logged beside it. There is no profile.yaml anywhere: the hook needs none."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import card_fixtures as cf
from card_fixtures import ANA, BRUNO, ME, TOKEN, uid
from helpers import REPO_ROOT

CLIENT_CMD = ".claude/skills/cdv-notion/scripts/notion"
GOOD = ("## Pedido\n\nO pedido como chegou.\n\n## Entrega\n\n**Objetivo:** Uma frase.\n\n**Pronto quando:**\n\n"
        "- Um critério.\n")


class HookCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="card-hook-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        claude = self.tmp / "project" / ".claude"
        self.hooks = claude / "harness" / "hooks"
        self.hooks.mkdir(parents=True)
        for name in ("card-check", "harness_hook.py"):
            shutil.copy2(REPO_ROOT / "hooks" / name, self.hooks / name)
        scripts = claude / "skills" / "cdv-notion-ticket" / "scripts"
        scripts.mkdir(parents=True)
        for name in ("card_contract.py", "card-contract.json"):
            shutil.copy2(cf.CHECKER.parent / name, scripts / name)
        self.checker = scripts / "card_contract.py"
        self.state = self.tmp / "state.json"
        self.client = cf.write_fake_client(claude / "skills" / "cdv-notion" / "scripts" / "notion", self.state)
        self.fake = cf.CardNotion()
        self.config({"me": ME, "card": {"since": cf.SINCE}})
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "NOTION_"))}
        self.env.update({"HOME": str(self.home), "NOTION_API_TOKEN": TOKEN})
        self.session = "s-" + uuid.uuid4().hex[:8]

    def config(self, value):
        path = self.home / ".config" / "cdv-notion" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def add(self, built):
        page, body = built
        self.fake.add(page, body)
        cf.save_state(self.fake, self.state)
        return page

    def calls(self):
        log = Path(str(self.state) + ".calls")
        return log.read_text().splitlines() if log.exists() else []

    def clear_calls(self):
        Path(str(self.state) + ".calls").unlink(missing_ok=True)

    def hook(self, payload, env=None):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run([str(self.hooks / "card-check")], input=data, text=True, capture_output=True,
                              cwd=str(self.tmp / "project"), env=env or self.env)

    def event(self, tool, tool_input, response=None, error=None, session=None, use_id=None):
        payload = {
            "session_id": session or self.session, "cwd": str(self.tmp / "project"),
            "hook_event_name": "PostToolUseFailure" if error is not None else "PostToolUse",
            "tool_name": tool, "tool_input": tool_input, "tool_use_id": use_id or "toolu_" + uuid.uuid4().hex,
        }
        if error is not None:
            payload["error"] = error
        else:
            payload["tool_response"] = response if response is not None else {"stdout": "", "stderr": "",
                                                                              "interrupted": False, "isImage": False}
        return payload

    def bash(self, command, stdout="", **extra):
        return self.event("Bash", {"command": command, "description": "x"},
                          {"stdout": stdout, "stderr": "", "interrupted": False, "isImage": False}, **extra)

    def update(self, ref, *flags, **extra):
        return self.bash(f"{CLIENT_CMD} update {ref} " + " ".join(flags), stdout=f"updated https://www.notion.so/x\n", **extra)

    def assertSays(self, proc, *needles):
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout, "")
        for needle in needles:
            self.assertIn(needle, proc.stderr)

    def assertSilent(self, proc):
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))


class CardHookTest(HookCase):
    def test_client_update_and_create_are_checked_and_other_verbs_are_not(self):
        bad = self.add(cf.task(1, ""))
        created = self.add(cf.task(2, ""))
        self.assertSays(self.hook(self.update(cf.key(1), "--set", "'Status=Done'")), cf.key(1), "request-zone:")
        create = self.bash("cd x && notion create --parent Tasks --set 'Task name=y'",
                           stdout=f"created {created['url']} {cf.key(2)}\n")
        self.assertSays(self.hook(create), created["url"], "request-zone:")
        self.clear_calls()
        for command in (f"notion fetch {cf.key(1)}", f"notion comments add {cf.key(1)} --body z",
                        f"echo notion update {cf.key(1)}"):
            with self.subTest(command=command):
                self.assertSilent(self.hook(self.bash(command)))
        self.assertEqual(self.calls(), [])
        spaced = self.bash(f"{CLIENT_CMD} update --set 'Status=In progress' {cf.key(1)}")
        self.assertSays(self.hook(spaced), cf.key(1))
        self.assertTrue(bad)

    def test_a_client_write_is_found_in_any_shell_shape(self):
        first = self.add(cf.task(1, ""))
        second = self.add(cf.task(2, ""))
        theirs = self.add(cf.task(3, "", assignee=(BRUNO,)))
        one, two = cf.key(1), cf.key(2)
        printed = f"updated {first['url']}\n"
        shapes = {
            "variable": f"N={CLIENT_CMD}; $N update {one} --set 'Status=Done'",
            "bash -c": f"bash -c \"{CLIENT_CMD} update {one} --set 'Status=Done'\"",
            "timeout": f"timeout 60 {CLIENT_CMD} update {one} --set 'Status=Done'",
            "timeout with options": f"timeout -k 5 60 {CLIENT_CMD} update {one} --set 'Status=Done'",
            "env": f"env X=1 {CLIENT_CMD} update {one} --set 'Status=Done'",
            "loop body": f"for i in 1; do {CLIENT_CMD} update {one} --set 'Status=Done'; done",
        }
        def bash(command, stdout=""):  # a session of its own: page 1 is written more than 3 times here
            return self.bash(command, stdout=stdout, session="s-" + uuid.uuid4().hex[:8])

        for name, command in shapes.items():
            with self.subTest(shape=name, output="the client's line"):
                self.assertSays(self.hook(bash(command, stdout=printed)), "request-zone:")
            with self.subTest(shape=name, output="none"):
                self.assertSays(self.hook(bash(command + " > /dev/null")), "request-zone:")
        loop = bash(f"for k in {one} {two}; do {CLIENT_CMD} update $k --set 'Status=Done'; done",
                    stdout=printed + f"updated {second['url']}\n")
        proc = self.hook(loop)
        self.assertSays(proc, first["url"], second["url"])
        self.assertEqual(proc.stderr.count("request-zone:"), 2)
        single = bash(f"for k in {one}; do {CLIENT_CMD} update $k --set 'Status=Done'; done", stdout=printed)
        self.assertSays(self.hook(single), first["url"], "request-zone:")
        heredoc = bash(f"cat > b.md <<'EOF'\nIt's the card.\nEOF\n{CLIENT_CMD} update {cf.key(3)} --replace-file b.md",
                       stdout=f"updated {theirs['url']}\n")
        self.assertSays(self.hook(heredoc), "request-zone:")
        quiet = bash(f"{CLIENT_CMD} update {one} --set 'Status=Done' > /dev/null")
        self.assertSays(self.hook(quiet), one, "request-zone:")
        # On PostToolUse the output is the call's stdout: a write line on stderr is not the client's
        on_stderr = self.event("Bash", {"command": f"{CLIENT_CMD} create --parent Tasks --set 'Task name=y' > /dev/null"},
                               {"stdout": "", "stderr": f"created {second['url']} {two}\n", "interrupted": False,
                                "isImage": False}, session="s-" + uuid.uuid4().hex[:8])
        self.assertSilent(self.hook(on_stderr))
        self.clear_calls()
        self.assertSilent(self.hook(bash("cat notes.txt", stdout=printed)))
        self.assertSilent(self.hook(bash("cat notion-log.txt", stdout=printed)))
        self.assertSilent(self.hook(bash(f"echo notion update {one}", stdout=f"notion update {one}\n")))
        self.assertEqual(self.calls(), [])

    def test_a_failed_client_call_is_checked_only_on_exit_4(self):
        self.add(cf.task(1, ""))
        command = {"command": f"{CLIENT_CMD} update {cf.key(1)} --set 'Status=Done' --append-file f.md"}
        done_in_part = self.event("Bash", command, error="Exit code 4\nupdated x\ndone in part: written: properties")
        self.assertSays(self.hook(done_in_part), cf.key(1))
        self.clear_calls()
        for code in (1, 2, 3):
            with self.subTest(code=code):
                self.assertSilent(self.hook(self.event("Bash", command, error=f"Exit code {code}\nrefused")))
        self.assertEqual(self.calls(), [])

    def test_a_failed_call_checks_the_pages_its_output_shows_as_written(self):
        first = self.add(cf.task(1, ""))
        self.add(cf.task(2, ""))
        both = {"command": f"{CLIENT_CMD} update {cf.key(1)} --set 'Status=Done' && "
                           f"{CLIENT_CMD} update {cf.key(2)} --set 'Status=Nope'"}
        proc = self.hook(self.event("Bash", both, error=f"Exit code 1\nupdated {first['url']}\nStatus has no option Nope"))
        self.assertSays(proc, first["url"], "request-zone:")
        self.assertNotIn(cf.key(2), proc.stderr)
        self.assertEqual(proc.stderr.count("request-zone:"), 1)

    def test_connector_page_writes_are_checked_under_any_server_prefix(self):
        bad = self.add(cf.task(1, ""))
        other = self.add(cf.task(2, ""))
        for tool in ("mcp__claude_ai_Notion__notion-update-page", "mcp__other__notion-update-page"):
            with self.subTest(tool=tool):
                proc = self.hook(self.event(tool, {"page_id": bad["id"], "command": "update_properties"}, {"ok": True}))
                self.assertSays(proc, cf.hex32(bad["id"]), "request-zone:")
        created = {"pages": [{"id": bad["id"], "url": bad["url"], "parent": {"page_id": other["id"]}}]}
        result = {"content": [{"type": "text", "text": json.dumps(created)}]}
        create = self.event("mcp__claude_ai_Notion__notion-create-pages",
                            {"parent": {"page_id": other["id"]}, "pages": [{"properties": {"title": "x"}}]}, result)
        proc = self.hook(create)
        self.assertSays(proc, cf.hex32(bad["id"]))
        self.assertNotIn(cf.hex32(other["id"]), proc.stderr)
        self.assertSilent(self.hook(self.event("mcp__claude_ai_Notion__notion-search", {"query": "x"}, {"ok": True})))

    def test_a_whole_body_replace_passes_body_replaced(self):
        theirs = self.add(cf.task(1, "", assignee=(BRUNO,)))
        self.assertSilent(self.hook(self.update(cf.key(1), "--set", "'Status=Done'")))
        self.assertSays(self.hook(self.update(cf.key(1), "--replace-file", "card.md")), "request-zone:")
        tool = "mcp__claude_ai_Notion__notion-update-page"
        self.assertSilent(self.hook(self.event(tool, {"page_id": theirs["id"], "command": "update_content"}, {})))
        self.assertSays(self.hook(self.event(tool, {"page_id": theirs["id"], "command": "replace_content"}, {})),
                        "request-zone:")

    def test_findings_exit_2_on_stderr_with_the_page_and_a_clean_card_is_silent(self):
        self.add(cf.task(1, "Status: Done\n"))
        self.add(cf.task(2, GOOD))
        proc = self.hook(self.update(cf.key(1), "--set", "'Status=In progress'"))
        self.assertSays(proc, cf.key(1), "status-in-body: ", "request-zone: ", "delivery-zone: ")
        self.assertSilent(self.hook(self.update(cf.key(2), "--set", "'Status=In progress'")))

    def test_three_failed_checks_in_a_row_are_said_once_then_silence(self):
        page = self.add(cf.task(1, ""))
        first, second = self.hook(self.update(cf.key(1))), self.hook(self.update(cf.key(1)))
        for proc in (first, second):
            self.assertSays(proc, "request-zone:")
            self.assertNotIn("in a row", proc.stderr)
        third = self.hook(self.update(cf.key(1)))
        self.assertSays(third, "request-zone:", "failed 3 checks in a row", "still outside the contract",
                        "developer decides")
        self.clear_calls()
        self.assertSilent(self.hook(self.update(cf.key(1))))
        self.assertEqual(self.calls(), [])
        self.assertSays(self.hook(self.update(cf.key(1), session="another")), "request-zone:")
        other = "reset-" + self.session
        self.hook(self.update(cf.key(1), session=other))
        self.hook(self.update(cf.key(1), session=other))
        self.fake.markdown[page["id"]] = GOOD
        cf.save_state(self.fake, self.state)
        self.assertSilent(self.hook(self.update(cf.key(1), session=other)))
        self.fake.markdown[page["id"]] = ""
        cf.save_state(self.fake, self.state)
        again = self.hook(self.update(cf.key(1), session=other))
        self.assertSays(again, "request-zone:")
        self.assertNotIn("in a row", again.stderr)

    def test_two_entries_of_one_call_run_one_check(self):
        self.add(cf.task(1, ""))
        payload = self.update(cf.key(1), use_id="toolu_same_call")
        self.assertSays(self.hook(payload), "request-zone:")
        self.clear_calls()
        self.assertSilent(self.hook(payload))
        self.assertEqual(self.calls(), [])
        self.assertTrue((self.home / ".cache" / "cdv-notion" / "card-check" / "claims" / "toolu_same_call").is_file())

    def test_the_hook_fails_open_and_needs_no_profile(self):
        self.assertFalse(list((self.tmp / "project").rglob("profile.yaml")))
        self.add(cf.task(1, ""))
        self.assertSays(self.hook(self.update(cf.key(1))), "request-zone:")
        self.assertSilent(self.hook("this is not json {"))
        self.assertSilent(self.hook('["a list"]'))
        self.assertSilent(self.hook(self.event("Edit", {"file_path": "x"}, {})))
        self.assertSilent(self.hook(self.update(uid(0x6999))))
        refused = self.add(cf.task(2, ""))
        self.fake.fail_pages = {refused["id"]: 403}
        cf.save_state(self.fake, self.state)
        self.assertSilent(self.hook(self.update(refused["id"])))
        original = self.checker.read_text()
        self.checker.write_text("import sys\nraise RuntimeError('broken checker')\n")
        self.assertSilent(self.hook(self.update(cf.key(1))))
        self.checker.unlink()
        self.assertSilent(self.hook(self.update(cf.key(1))))
        self.checker.write_text(original)
        self.client.unlink()
        self.assertSilent(self.hook(self.update(cf.key(1))))

    def test_no_token_is_said_once_per_session(self):
        self.add(cf.task(1, ""))
        env = {k: v for k, v in self.env.items() if k != "NOTION_API_TOKEN"}
        first = self.hook(self.update(cf.key(1)), env=env)
        self.assertSays(first, "not being checked on this machine", "notion auth login")
        self.assertEqual(len(first.stderr.strip().splitlines()), 1)
        self.assertSilent(self.hook(self.update(cf.key(1)), env=env))
        self.assertSilent(self.hook(self.update(cf.key(1)), env=env))
        self.assertSays(self.hook(self.update(cf.key(1), session="next"), env=env), "not being checked")

    def test_a_fetch_output_pins_the_request_zone_without_calling_notion(self):
        self.add(cf.task(1, GOOD))
        fetched = subprocess.run([str(self.client), "fetch", cf.key(1)], capture_output=True, text=True, env=self.env)
        self.assertEqual(fetched.returncode, 0, fetched.stderr)
        self.assertIn("parent: data source Tasks", fetched.stdout)
        self.clear_calls()
        pins = self.home / ".cache" / "cdv-notion" / "card-pins"
        self.assertSilent(self.hook(self.bash(f"{CLIENT_CMD} fetch {cf.key(1)}", stdout=fetched.stdout)))
        self.assertEqual(self.calls(), [])
        stored = list(pins.glob("*.json"))
        self.assertEqual(len(stored), 1)
        pinned = stored[0].read_text()
        checked = subprocess.run([sys.executable, str(self.checker), "check", cf.key(1)], capture_output=True,
                                 text=True, env=self.env)
        self.assertEqual((checked.returncode, checked.stdout), (0, ""), checked.stderr)
        self.assertEqual(stored[0].read_text(), pinned)
        stored[0].write_text(json.dumps({"digest": "kept"}))
        self.hook(self.bash(f"{CLIENT_CMD} fetch {cf.key(1)}", stdout=fetched.stdout))
        self.assertEqual(json.loads(stored[0].read_text())["digest"], "kept")


if __name__ == "__main__":
    unittest.main()
