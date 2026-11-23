"""The card-check hook (hooks/card-check) as the host runs it: a subprocess fed the PostToolUse or
PostToolUseFailure JSON on stdin.

A temporary `.claude/` holds the real hook, the real checker and, at the client's path, a fake
cdv-notion client: the real client over a fake Notion kept in a JSON state file, whose requests are
logged beside it. There is no profile.yaml anywhere: the hook needs none."""

import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

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
        url = self.url(ref)
        return self.bash(f"{CLIENT_CMD} update {ref} " + " ".join(flags), stdout=f"updated {url}\n" if url else "", **extra)

    def url(self, ref):
        """The url the client prints for a page of the fake, by id or key; None when it has none."""
        for page in self.fake.pages.values():
            number = (page["properties"].get("Task ID") or {}).get("unique_id", {}).get("number")
            if ref == page["id"] or ref == cf.key(number):
                return page["url"]
        return None

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
        self.assertSays(self.hook(self.update(cf.key(1), "--set", "'Status=Done'")), bad["url"], "request-zone:")
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
        mixed = bash(f"{CLIENT_CMD} update {one} --set 'Status=Done' > /dev/null; K={two}; {CLIENT_CMD} update $K --set 'Status=Done'",
                     stdout=f"updated {second['url']}\n")
        self.assertSays(self.hook(mixed), second["url"], "request-zone:")  # the line decides, not the command
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
        # Exit 4: the second update is done in part and prints no line of its own, so the command names it
        proc = self.hook(self.event("Bash", both, error=f"Exit code 4\nupdated {first['url']}\ndone in part; not applied: x"))
        self.assertSays(proc, first["url"], cf.key(2))
        single = {"command": f"{CLIENT_CMD} update {cf.key(1)} --set 'Status=Done' --append-file f.md"}
        proc = self.hook(self.event("Bash", single, session="partial", error=(
            f"Exit code 4\nupdated {first['url']}\ndone in part on {first['url']}: written: properties. Not written: body")))
        self.assertSays(proc, first["url"])
        self.assertEqual(proc.stderr.count("request-zone:"), 1)  # one page, checked once
        loop = {"command": f"for k in {cf.key(1)}; do {CLIENT_CMD} update $k --append-file f.md; done"}
        proc = self.hook(self.event("Bash", loop, session="named", error=(
            f"Exit code 4\ndone in part on {first['url']}: written: properties. Not written: body")))
        self.assertSays(proc, first["url"], "request-zone:")

    def client_run(self, argv, *failures):
        """(exit code, stdout, stderr) of the real client over the fake Notion, where each (method, path,
        answer) of `failures` answers for it: a status, or the exception the transport raises."""
        fake, module = cf.fake_from_state(self.state), cf.real_client()
        fake.now = cf.CREATED
        module.SLEEP = lambda seconds: None
        module.TRANSPORT = fake
        for method, path, answer in failures:
            def handler(request, answer=answer):
                if isinstance(answer, tuple):
                    return answer
                if isinstance(answer, int):
                    return answer, {"object": "error", "status": answer, "code": "synthetic", "message": "synthetic"}
                raise getattr(module, answer)("synthetic") if isinstance(answer, str) else answer
            fake.on(method, path, handler)
        with mock.patch.dict(os.environ, self.env, clear=True):
            return cf.run_main(module, argv)

    def failed(self, command, run, **extra):
        """The host's event for a Bash call that ended in the client run `run`."""
        code, out, err = run
        return self.event("Bash", {"command": command}, error=f"Exit code {code}\n{out}{err}", **extra)

    def test_a_write_in_doubt_whose_page_the_client_names_is_checked(self):
        page = self.add(cf.task(1, ""))
        other = self.add(cf.task(2, ""))
        parent = self.add(cf.task(3, ""))
        clean = self.add(cf.task(4, GOOD))
        body = self.tmp / "f.md"
        body.write_text("Uma linha.\n", encoding="utf-8")
        one, page_path, body_path = cf.key(1), f"/v1/pages/{page['id']}", f"/v1/pages/{page['id']}/markdown"
        props = ["update", one, "--set", "Status=Done"]
        append = ["update", one, "--append-file", str(body)]
        command = f"{CLIENT_CMD} update {one} --set 'Status=Done'"
        loop = f"for k in {one} {cf.key(2)}; do {CLIENT_CMD} update $k --set 'Status=Done'; done"

        # In doubt on the first write: exit 1, no `updated` line, and the message names the page
        for number, (argv, path, answer) in enumerate((
                (props, page_path, 502), (props, page_path, 529), (props, page_path, TimeoutError("slow")),
                (props, page_path, ConnectionResetError("reset")), (append, body_path, 503))):
            with self.subTest(argv=argv, answer=answer):
                run = self.client_run(argv, ("PATCH", path, answer))
                self.assertEqual(run[0], 1, run)
                self.assertIn("In doubt: ", run[2])
                self.assertNotIn("updated", run[1])
                proc = self.hook(self.failed(command, run, session=f"doubt-{number}"))
                self.assertSays(proc, cf.hex32(page["id"]), "request-zone:")
                self.assertEqual(proc.stderr.count("request-zone:"), 1)

        # Refused or never sent: the message may name the page too, and nothing is checked
        self.clear_calls()
        for argv, path, answer, code in ((props, page_path, 409, 1), (props, page_path, 400, 2),
                                         (props, page_path, 401, 3), (props, page_path, 429, 1),
                                         (props, page_path, "Unsent", 1), (append, body_path, ConnectionRefusedError("no"), 1)):
            with self.subTest(argv=argv, answer=answer):
                run = self.client_run(argv, ("PATCH", path, answer))
                self.assertEqual(run[0], code, run)
                self.assertNotIn("In doubt: ", run[2])
                self.assertSilent(self.hook(self.failed(command, run)))
        self.assertEqual(self.calls(), [])

        # In doubt on a later write: exit 4, the page is checked once
        run = self.client_run(props + ["--append-file", str(body)], ("PATCH", body_path, TimeoutError("slow")))
        self.assertEqual(run[0], 4, run)
        self.assertIn("In doubt: ", run[2])
        proc = self.hook(self.failed(loop, run, session="later"))
        self.assertSays(proc, page["url"])
        self.assertEqual(proc.stderr.count("request-zone:"), 1)

        # One call, one update in doubt and one that landed: both, whichever decided the call's exit code
        doubt = self.client_run(props, ("PATCH", page_path, 502))
        landed = f"updated {other['url']}\n"
        proc = self.hook(self.failed(loop, (1, landed, doubt[2]), session="both"))
        self.assertSays(proc, cf.hex32(page["id"]), other["url"])
        for name, out, err in (("stderr", landed, doubt[2]), ("2>&1", doubt[2] + landed, "")):
            with self.subTest(exit=0, doubt_on=name):
                proc = self.hook(self.event("Bash", {"command": loop}, {"stdout": out, "stderr": err, "interrupted": False},
                                            session="zero " + name))
                self.assertSays(proc, cf.hex32(page["id"]), other["url"])
        masked = self.hook(self.event("Bash", {"command": command + " 2>&1 | tail -3"}, {"stdout": doubt[2], "stderr": ""},
                                      session="masked"))
        self.assertSays(masked, cf.hex32(page["id"]))
        self.assertEqual(masked.stderr.count("request-zone:"), 1)
        # The first update in doubt, the second done in part (exit 4): each page once, the keys add nothing
        two = {"command": f"{CLIENT_CMD} update {one} --set 'Status=Done'; "
                          f"{CLIENT_CMD} update {cf.key(2)} --set 'Status=Done' --append-file f.md"}
        proc = self.hook(self.event("Bash", two, session="two", error=(
            f"Exit code 4\n{landed}{doubt[2]}done in part on {other['url']}: written: properties Status. Not written: x")))
        self.assertSays(proc, cf.hex32(page["id"]), other["url"])
        self.assertEqual(proc.stderr.count("request-zone:"), 2)
        # A whole-body replace in doubt is judged as one, and a clean card in doubt says nothing
        theirs = self.add(cf.task(5, "", assignee=(BRUNO,)))
        run = self.client_run(["update", cf.key(5), "--replace-file", str(body)],
                              ("PATCH", f"/v1/pages/{theirs['id']}/markdown", 504))
        self.assertSays(self.hook(self.failed(f"{CLIENT_CMD} update {cf.key(5)} --replace-file f.md", run)), "request-zone:")
        run = self.client_run(["update", cf.key(4), "--set", "Status=Done"], ("PATCH", f"/v1/pages/{clean['id']}", 502))
        self.assertIn("In doubt: ", run[2])
        self.assertSilent(self.hook(self.failed(f"{CLIENT_CMD} update {cf.key(4)} --set 'Status=Done'", run)))

        # A create in doubt names its parent and no page of its own: nothing is checked
        create = f"{CLIENT_CMD} create --parent {cf.key(3)} --set 'title=Plano'"
        run = self.client_run(["create", "--parent", parent["id"], "--set", "title=Plano"], ("POST", "/v1/pages", 502))
        self.assertEqual(run[0], 1, run)
        self.assertIn("In doubt: ", run[2])
        self.assertIn(cf.hex32(parent["id"]), run[2])
        self.clear_calls()
        self.assertSilent(self.hook(self.failed(create, run)))
        # unless Notion said which page the create committed and only reading it back failed
        run = self.client_run(["create", "--parent", parent["id"], "--set", "title=Plano"],
                              ("POST", "/v1/pages", (503, {"object": "error", "status": 503, "code": "synthetic", "message": "x",
                                                           "additional_data": {"committed_resource_id": other["id"]}})),
                              ("GET", f"/v1/pages/{other['id']}", TimeoutError("slow")))
        self.assertIn("In doubt: ", run[2])
        proc = self.hook(self.failed(create, run, session="committed"))
        self.assertSays(proc, cf.hex32(other["id"]))
        self.assertNotIn(cf.hex32(parent["id"]), proc.stderr)
        self.clear_calls()
        # The same words in a command that does not name the client are not a write
        self.assertSilent(self.hook(self.event("Bash", {"command": "cat notes.txt"}, {"stdout": doubt[2], "stderr": ""})))
        self.assertEqual(self.calls(), [])

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

    def test_a_write_of_more_pages_than_the_time_budget_says_how_many_were_not_checked(self):
        pages = [self.add(cf.task(n, "")) for n in range(1, 13)]
        result = {"content": [{"type": "text", "text": json.dumps({"pages": [{"id": p["id"]} for p in pages]})}]}
        create = self.event("mcp__claude_ai_Notion__notion-create-pages", {"parent": {"data_source_id": cf.DS_TASKS},
                                                                            "pages": [{}] * 12}, result)
        env = dict(self.env, CARD_CHECK_BUDGET="3")
        started = time.monotonic()
        proc = self.hook(create, env=env)
        took = time.monotonic() - started
        self.assertEqual(proc.returncode, 2, proc.stderr)
        checked = proc.stderr.count("request-zone:")
        last = proc.stderr.strip().splitlines()[-1]
        match = re.fullmatch(r"card-check: (\d+) more pages? this call wrote (?:was|were) not checked inside the hook's "
                             r"time budget of 3s; run `card_contract\.py check <ref>` on each\.", last)
        self.assertIsNotNone(match, last)
        self.assertGreaterEqual(checked, 1)
        self.assertEqual(checked + int(match.group(1)), 12)
        self.assertLess(took, 3 + 2)
        self.assertEqual(proc.stderr.count("time budget"), 1)
        everything = self.hook(self.event("mcp__claude_ai_Notion__notion-create-pages", {"pages": [{}] * 2},
                                          {"pages": [{"id": p["id"]} for p in pages[:2]]}))
        self.assertEqual(everything.stderr.count("request-zone:"), 2)
        self.assertNotIn("time budget", everything.stderr)
        # Less than a second left: no check is started
        none = self.hook(self.update(cf.key(1), session="late"), env=dict(self.env, CARD_CHECK_BUDGET="0.95"))
        self.assertIn("card-check: 1 more page this call wrote was not checked", none.stderr)
        self.assertNotIn("request-zone:", none.stderr)
        # A check that hangs (Notion slow to answer) is cut at the budget, and said as not checked
        wrapper = self.client.read_text()
        self.assertIn("def main(argv=None):\n", wrapper)
        self.client.write_text(wrapper.replace("def main(argv=None):\n", "def main(argv=None):\n    import time\n"
                                                                         "    time.sleep(60)\n"))
        started = time.monotonic()
        slow = self.hook(self.update(cf.key(1), session="slow"), env=env)
        self.assertLess(time.monotonic() - started, 3 + 2)
        self.assertEqual(slow.returncode, 2, slow.stderr)
        self.assertIn("card-check: 1 more page this call wrote was not checked inside the hook's time budget of 3s",
                      slow.stderr)
        # The budget is the host's timeout of door 3 less a margin, and a setting can only lower it
        loader = importlib.machinery.SourceFileLoader("card_check_hook", str(self.hooks / "card-check"))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        for value, expected in (("999", 25.0), ("not a number", 25.0), ("3", 3.0), ("", 25.0)):
            with self.subTest(budget=value), mock.patch.dict(os.environ, {"CARD_CHECK_BUDGET": value}):
                self.assertEqual(module.budget(), expected)
        self.assertLess(module.BUDGET_SECONDS, 30)

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
        self.assertSays(proc, self.url(cf.key(1)), "status-in-body: ", "request-zone: ", "delivery-zone: ")
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

    def checks_of(self, page):
        """How many times the checker read this page since the log was cleared."""
        return self.calls().count(f"GET /v1/pages/{page['id']}/markdown")

    def test_a_page_is_one_page_whatever_names_it(self):
        page = self.add(cf.task(1, ""))
        other = self.add(cf.task(2, ""))
        one, two = cf.key(1), cf.key(2)
        printed = f"updated {page['url']}\n"
        miss = "Exit code 4\n" + printed
        part = f"done in part on {page['url']}: written: properties. Not written: body"
        doubt = f"In doubt: properties Status (PATCH /v1/pages/{page['id']}: HTTP 502): it may have been applied"
        once = {  # one call that names page 1 more than once, exit 4
            "two updates, a miss in the second": (
                f"{CLIENT_CMD} update {one} --set 'Status=Done' && {CLIENT_CMD} update {one} --edit a b --edit c d",
                miss + printed + "done in part; not applied: edit 2"),
            "a miss in one update": (f"{CLIENT_CMD} update {one} --edit a b --edit c d", miss + "done in part; not applied: edit 2"),
            "done in part on the page": (f"{CLIENT_CMD} update {one} --set 'Status=Done' --append-file f.md", miss + part),
            "by its key and by its url": (
                f"{CLIENT_CMD} update {one} --set 'Status=Done' > /dev/null; {CLIENT_CMD} update {page['url']} --append-file f.md",
                "Exit code 4\n" + part),
            "by its key, then by its url, with no output": (
                f"{CLIENT_CMD} update {one} --set 'Status=Done' > /dev/null; {CLIENT_CMD} update {page['url']} --edit a b --edit c d > /dev/null",
                "Exit code 4\ndone in part; not applied: edit 2"),
            "by its id with and without hyphens": (
                f"{CLIENT_CMD} update {page['id']} --set 'Status=Done'; {CLIENT_CMD} update {cf.hex32(page['id'])} --append-file f.md",
                "Exit code 4\n" + part),
            "by its key in small letters": (f"{CLIENT_CMD} update {one.lower()} --edit a b --edit c d", miss + "done in part; not applied: x"),
            "in doubt and by its key": (f"{CLIENT_CMD} update {one} --set 'Status=Done'; {CLIENT_CMD} update {one} --append-file f.md",
                                        f"Exit code 4\n{doubt}\n{part}"),
        }
        for number, (name, (command, error)) in enumerate(once.items()):
            with self.subTest(call=name):
                self.clear_calls()
                proc = self.hook(self.event("Bash", {"command": command}, error=error, session=f"once-{number}"))
                self.assertSays(proc, "request-zone:")
                self.assertEqual(proc.stderr.count("request-zone:"), 1, proc.stderr)
                self.assertEqual(self.checks_of(page), 1)
        # Two pages in one call are still two pages
        both = {"command": f"{CLIENT_CMD} update {one} --set 'Status=Done' && {CLIENT_CMD} update {two} --edit a b --edit c d"}
        proc = self.hook(self.event("Bash", both, session="both", error=(
            f"{miss}updated {other['url']}\ndone in part; not applied: edit 2")))
        self.assertEqual(proc.stderr.count("request-zone:"), 2, proc.stderr)
        # A connector create that shows the page by its url and by its id
        proc = self.hook(self.event("mcp__x__notion-create-pages", {"pages": [{}]}, {"pages": [
            {"id": page["id"], "url": page["url"]}, {"id": cf.hex32(page["id"])}]}, session="connector"))
        self.assertEqual(proc.stderr.count("request-zone:"), 1, proc.stderr)

        # One counter across calls: the line comes once, on the third failed check, then silence
        for number, names in enumerate(((one, page["url"]), (page["url"], one), (page["id"], one.lower()),
                                        (one, cf.hex32(page["id"])))):
            with self.subTest(names=names):
                session = f"turns-{number}"
                for turn in range(1, 7):
                    ref = names[(turn - 1) % 2]
                    self.clear_calls()
                    quiet = turn % 2 == 1  # every other write shows no output: the command names the page
                    proc = self.hook(self.bash(f"{CLIENT_CMD} update '{ref}' --set 'Status=Done'" + (" > /dev/null" if quiet else ""),
                                               stdout="" if quiet else printed, session=session))
                    if turn > 3:
                        self.assertSilent(proc)
                        self.assertEqual(self.calls(), [], turn)
                        continue
                    self.assertEqual(self.checks_of(page), 1, turn)
                    self.assertEqual(proc.stderr.count("request-zone:"), 1, proc.stderr)
                    self.assertEqual(proc.stderr.count("3 checks in a row"), 1 if turn == 3 else 0, proc.stderr)
        # The page an address opens in a peek is the page it names
        peek = f"https://www.notion.so/board-{cf.hex32(other['id'])}?p={cf.hex32(page['id'])}&pm=s"
        for ref in (peek, one):
            proc = self.hook(self.bash(f"{CLIENT_CMD} update '{ref}' --set 'Status=Done' > /dev/null", session="peek"))
            self.assertNotIn("in a row", proc.stderr)
        third = self.hook(self.bash(f"{CLIENT_CMD} update '{peek}' --set 'Status=Done' > /dev/null", session="peek"))
        self.assertSays(third, "3 checks in a row")
        self.assertNotIn("in a row", self.hook(self.update(two, session="peek")).stderr)

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

    def test_a_cut_or_piped_fetch_pins_nothing(self):
        request = "## Pedido\n\nO pedido como chegou.\nCom uma segunda linha de quem pediu.\n\n"
        self.add(cf.task(1, request + GOOD.split("\n\n", 2)[2].replace("O pedido como chegou.\n\n", "")))
        fetched = subprocess.run([str(self.client), "fetch", cf.key(1)], capture_output=True, text=True, env=self.env)
        self.assertEqual(fetched.returncode, 0, fetched.stderr)
        whole = fetched.stdout
        self.assertIn("## Entrega", whole)
        lines = whole.splitlines()
        cut = "\n".join(lines[: lines.index("O pedido como chegou.") + 1]) + "\n"
        pins = self.home / ".cache" / "cdv-notion" / "card-pins"
        cases = {
            "piped through head": (f"{CLIENT_CMD} fetch {cf.key(1)} | head -40", cut),
            "piped, the output whole": (f"{CLIENT_CMD} fetch {cf.key(1)} | sed -n 1,400p", whole),
            "redirected": (f"{CLIENT_CMD} fetch {cf.key(1)} 2>&1", whole),
            "the client's truncation marker": (f"{CLIENT_CMD} fetch {cf.key(1)}",
                                               whole.rstrip("\n") + "\n(truncated: 3 blocks not loaded; fetch again)\n"),
            "a request zone with no end marker": (f"{CLIENT_CMD} fetch {cf.key(1)}", cut),
            "two client calls": (f"{CLIENT_CMD} fetch {cf.key(1)} && {CLIENT_CMD} fetch {cf.key(1)}", whole + whole),
        }
        as_json = subprocess.run([str(self.client), "fetch", cf.key(1), "--json"], capture_output=True, text=True,
                                 env=self.env)
        self.assertEqual(as_json.returncode, 0, as_json.stderr)
        marked = json.loads(as_json.stdout)
        marked["markdown"]["truncated"] = True
        cases["--json with truncated"] = (f"{CLIENT_CMD} fetch {cf.key(1)} --json", json.dumps(marked))
        project = self.add(cf.project(2, cf.project_body(current="")))
        shown = subprocess.run([str(self.client), "fetch", project["id"]], capture_output=True, text=True,
                               env=self.env).stdout
        shown_lines = shown.splitlines()
        cases["a request toggle with no closing tag"] = (
            f"{CLIENT_CMD} fetch {project['id']}", "\n".join(shown_lines[: shown_lines.index("</toggle>")]) + "\n")
        for name, (command, stdout) in cases.items():
            with self.subTest(case=name):
                for stale in sorted(pins.glob("*.json")) if pins.is_dir() else []:
                    stale.unlink()  # each case alone
                self.assertSilent(self.hook(self.bash(command, stdout=stdout)))
                self.assertEqual(sorted(pins.glob("*.json")) if pins.is_dir() else [], [])
        checked = subprocess.run([sys.executable, str(self.checker), "check", cf.key(1)], capture_output=True,
                                 text=True, env=self.env)
        self.assertEqual((checked.returncode, checked.stdout), (0, ""), checked.stderr)
        for stale in sorted(pins.glob("*.json")):
            stale.unlink()
        for command, stdout in ((f"{CLIENT_CMD} fetch {cf.key(1)} --json", as_json.stdout),
                                (f"{CLIENT_CMD} fetch {project['id']}", shown)):
            with self.subTest(whole=command):
                self.assertSilent(self.hook(self.bash(command, stdout=stdout)))
        self.assertEqual(len(list(pins.glob("*.json"))), 2)


if __name__ == "__main__":
    unittest.main()
