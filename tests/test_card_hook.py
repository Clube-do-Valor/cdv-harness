"""The card-check hook (hooks/card-check) as the host runs it: a subprocess fed the PostToolUse or
PostToolUseFailure JSON on stdin.

A temporary `.claude/` holds the real hook, the real checker and, at the client's path, a fake
cdv-notion client: the real client over a fake Notion kept in a JSON state file, whose requests are
logged beside it. There is no profile.yaml anywhere: the hook needs none."""

import importlib.machinery
import importlib.util
import io
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

    def hook_module(self):
        loader = importlib.machinery.SourceFileLoader("card_check_hook", str(self.hooks / "card-check"))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        module.checker_path, module.client_path = lambda: self.checker, lambda: self.client
        return module

    def run_module(self, module, payload, env=None):
        """(exit code, message) of the hook's main() in this process."""
        with mock.patch.dict(os.environ, env or self.env, clear=True), mock.patch("sys.stdin", io.StringIO(json.dumps(payload))):
            return module.main()

    def checks(self, payload):
        """[(task number, whether it was checked as a whole-body replace)] of the checks a call starts, in
        order: the hook's main() with the checker replaced by a record of the calls it gets."""
        module, found = self.hook_module(), []

        def check(ref, flags, timeout=None):
            for page in self.fake.pages.values():
                number = page["properties"]["Task ID"]["unique_id"]["number"]
                if ref.upper() == cf.key(number) or cf.hex32(page["id"]) in ref.replace("-", ""):
                    found.append((number, self.replaced(number, page, flags)))
                    return 1, "finding", page["id"], cf.key(number)
            raise AssertionError(f"checked {ref!r}, which is no page")

        module.check = check
        self.run_module(module, dict(payload, session_id="s-" + uuid.uuid4().hex))
        return found

    def replaced(self, number, page, flags):
        """Whether the checker, given these flags, judges this page as replaced."""
        named = [ref for flag, ref in zip(flags, flags[1:]) if flag == "--body-replaced-of"]
        return "--body-replaced" in flags or any(
            ref.upper() == cf.key(number) or cf.hex32(page["id"]) in ref.replace("-", "") for ref in named)

    def marked(self, command, stdout="", error=None):
        """The task numbers a Bash call checks as replaced, and every one it checks."""
        payload = self.bash(command, stdout=stdout) if error is None else self.event("Bash", {"command": command}, error=error)
        found = self.checks(payload)
        return [number for number, replaced in found if replaced], [number for number, _ in found]

    def pages(self, command, stdout="", error=None):
        """The task numbers a Bash call checks, in order."""
        payload = self.bash(command, stdout=stdout) if error is None else self.event("Bash", {"command": command}, error=error)
        return [number for number, _ in self.checks(payload)]

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
        proc = self.hook(mixed)  # the first from the command, the second from the output, each once
        self.assertSays(proc, f"check {one})", second["url"])
        self.assertEqual(proc.stderr.count("request-zone:"), 2, proc.stderr)
        labelled = bash(f"for k in {one} {two}; do echo -n \"$k: \"; {CLIENT_CMD} update $k --set 'Status=Done'; done",
                        stdout=f"{one}: updated {first['url']}\n{two}: updated {second['url']}\n")
        proc = self.hook(labelled)
        self.assertSays(proc, first["url"], second["url"])
        self.assertEqual(proc.stderr.count("request-zone:"), 2, proc.stderr)
        default = bash(f"N=${{N:-{CLIENT_CMD}}}; $N update $KEY --set 'Status=Done'", stdout=printed)
        self.assertSays(self.hook(default), first["url"], "request-zone:")
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

    def test_the_client_line_is_taken_wherever_it_sits_in_the_output(self):
        pages = [self.add(cf.task(n, "")) for n in (1, 2)]
        one, two = (page["url"] for page in pages)
        loop = f"for k in $KEYS; do {CLIENT_CMD} update $k --set 'Status=Done'; done"
        for name, output, expected in (
                ("a line of its own", f"updated {one}\nupdated {two}\n", [1, 2]),
                ("after a label", f"a: updated {one}\nb: updated {two}\n", [1, 2]),
                ("glued to a label", f"a=updated {one}\nTSKupdated {two}\n", [1, 2]),
                ("two on a line", f"updated {one} updated {two}", [1, 2]),
                ("indented, in quotes, with a full stop", f"   'updated {one}'\n(updated {two}).\n", [1, 2]),
                ("after a label, created", f"new: created {one} {cf.key(1)}\n", [1]),
                ("in the app's address", f"updated https://app.notion.com/p/{cf.hex32(pages[0]['id'])}\n", [1]),
                ("another host", f"updated https://example.com/{cf.hex32(pages[0]['id'])}\n", []),
                ("a host that only ends like it", f"updated https://notnotion.so/{cf.hex32(pages[0]['id'])}\n", []),
                ("a Notion address with no page", "updated https://www.notion.so/product\n", []),
                ("no scheme", f"updated {one.replace('https://', '')}\n", []),
                ("the word alone", "updated 3 files\n", [])):
            with self.subTest(output=name):
                self.assertEqual(self.pages(loop, stdout=output), expected)
                self.assertEqual(self.pages(loop, error="Exit code 1\n" + output), expected)
        for spelling in (f"N={CLIENT_CMD}; $N update $KEY", f"N=${{N:-{CLIENT_CMD}}}; $N update $KEY", "${N:-notion} update $KEY",
                         f"\"${{N:-{CLIENT_CMD}}}\" update $KEY", "${N:=notion} update $KEY", f"x=$({CLIENT_CMD} update $KEY)",
                         f"x=`{CLIENT_CMD} update $KEY`", f"{CLIENT_CMD} \\\n  update $KEY", "xargs notion update",
                         "python3 -c \"run(['notion', 'update'])\"", f"eval '{CLIENT_CMD} update $KEY'"):
            with self.subTest(spelling=spelling):
                self.assertEqual(self.pages(spelling, stdout=f"updated {one}\n"), [1])
        for name, tail in (("nested past reading", "echo " + "$(" * 3000 + ")" * 3000), ("not closed", "echo \"$(x")):
            with self.subTest(command=name):
                self.assertEqual(self.pages(f"{CLIENT_CMD} update $KEY; {tail}", stdout=f"updated {one}\n"), [1])
        for command in ("cat notes.txt", "cat notion-log.txt", "cd cdv-notion && cat x", "cat my.notion.txt", "ls notions"):
            with self.subTest(not_the_client=command):
                self.assertEqual(self.pages(command, stdout=f"updated {one}\n"), [])

    def test_the_command_names_the_pages_of_a_write_with_no_output(self):
        for n in (1, 2, 3):
            self.add(cf.task(n, ""))
        one, two = cf.key(1), cf.key(2)
        write = f"{CLIENT_CMD} update {one} --set 'Status=In progress'"
        shapes = {
            "a list": f"cd x && {write} > /dev/null; echo done",
            "after a list that may fail": f"false || {write} > /dev/null",
            "in the background of a list": f"true & {write} > /dev/null",
            "a pipeline": f"echo x | {write} | tail -1 > /dev/null",
            "both streams in a pipeline": f"{write} |& cat > /dev/null",
            "a redirection before the client": f"> /dev/null {write}",
            "a redirection glued to the word": f"{write}>/dev/null",
            "both streams": f"{write} > out.txt 2>&1",
            "both streams, short": f"{write} &> out.txt",
            "standard error first": f"2>err.txt {write} >> out.txt",
            "flags before the page": f"{CLIENT_CMD} update --set 'Status=In progress' {one} > /dev/null",
            "a flag with its value glued": f"{CLIENT_CMD} update --set='Status=Done' {one} > /dev/null",
            "a flag cut short": f"{CLIENT_CMD} update --app f.md {one} > /dev/null",
            "an edit with two values": f"{CLIENT_CMD} update --edit 'a b' c {one} > /dev/null",
            "a subshell": f"(cd x && {write}) > /dev/null",
            "a group": f"{{ {write}; }} > /dev/null",
            "bash -c": f"bash -c \"{write}\" > /dev/null",
            "bash with options": f"bash -o pipefail -ec \"{write}\" > /dev/null",
            "sh -c inside bash -c": f"bash -c \"sh -c '{CLIENT_CMD} update {one} --icon x'\" > /dev/null",
            "bash -c under a wrapper": f"timeout 60 bash -lc \"{write}\" > /dev/null",
            "env": f"env -u A -i X=1 {write} > /dev/null",
            "timeout": f"timeout -k 5 --signal=TERM 60 {write} > /dev/null",
            "nice": f"nice -n 5 {write} > /dev/null",
            "nohup": f"nohup {write} > /dev/null",
            "time": f"time -p {write} > /dev/null",
            "exec": f"exec -a name {write} > /dev/null",
            "command": f"command -p {write} > /dev/null",
            "sudo": f"sudo -E -u root X=1 {write} > /dev/null",
            "sudo with glued options": f"sudo -nuroot {write} > /dev/null",
            "two wrappers": f"nohup env X=1 timeout 60 {write} > /dev/null",
            "the test of an if": f"if {write} > /dev/null; then echo ok; fi",
            "the body of an if": f"if true; then {write} > /dev/null; fi",
            "the else of an if": f"if false; then :; else {write} > /dev/null; fi",
            "the elif of an if": f"if false; then :; elif {write} > /dev/null; then :; fi",
            "a negated test": f"if ! {write} > /dev/null; then :; fi",
            "the body of a for": f"for i in 1 2; do {write} > /dev/null; done",
            "the test of a while": f"while ! {write} > /dev/null; do sleep 1; done",
            "the body of a while": f"while read line; do {write} > /dev/null; done < list.txt",
            "the test of an until": f"until {write} > /dev/null; do sleep 1; done",
            "a substitution inside quotes": f"OUT=\"$({write})\"",
            "a substitution inside quotes, with words": f"echo \"got $({write}) there\" > /dev/null",
            "a substitution": f"OUT=$({write})",
            "backquotes inside quotes": f"OUT=\"`{CLIENT_CMD} update {one} --icon x`\"",
            "a substitution inside a substitution": f"OUT=\"$(echo \"$({write})\")\"",
            "a heredoc in a substitution": f"git commit -m \"$(cat <<'EOF'\nIt's (a\nEOF\n)\" && {write} > /dev/null",
            "an interpreter": f"python3 {write} > /dev/null",
            "an interpreter with options": f"python3 -u -X dev -Wignore {write} > /dev/null",
            "an interpreter under env": f"/usr/bin/env python3.11 -u {write} > /dev/null",
            "a shell in front of the client": f"bash -e {write} > /dev/null",
            "a variable": f"N={CLIENT_CMD}\n$N update {one} --icon x > /dev/null",
            "a variable in quotes": f"N='{CLIENT_CMD}'; \"${{N}}\" update {one} --icon x > /dev/null",
            "a variable with its default": f"N=${{N:-{CLIENT_CMD}}}; $N update {one} --icon x > /dev/null",
            "a default with no assignment": f"${{N:-{CLIENT_CMD}}} update {one} --icon x > /dev/null",
            "a variable with the interpreter": f"N=\"python3 -u {CLIENT_CMD}\"; $N update {one} --icon x > /dev/null",
            "an exported variable": f"export N={CLIENT_CMD}; $N update {one} --icon x > /dev/null",
            "the page in a variable": f"K={one}; {CLIENT_CMD} update \"$K\" --icon x > /dev/null",
            "the page in a variable of an if": f"if true; then K={one}; fi; {CLIENT_CMD} update $K --icon x > /dev/null",
            "a loop inside an if": f"if true; then for k in {one}; do {CLIENT_CMD} update $k --icon x > /dev/null; done; fi",
            "a comment before": f"# it's the card\n{write} > /dev/null",
            "a comment after": f"{write} > /dev/null # it's done",
            "a line cut in two": f"{CLIENT_CMD} \\\n  update {one} \\\n  --icon x > /dev/null",
            "a heredoc with an apostrophe before": f"cat > b.md <<'EOF'\nIt's the card.\nEOF\n{write} > /dev/null",
            "a heredoc fed to it": f"{CLIENT_CMD} update {one} --append-file - > /dev/null <<EOF\nIt's (the card\nEOF\n",
            "a heredoc run by a shell": f"bash <<'EOF' > /dev/null\n{write}\nEOF",
            "a quoted hash": f"echo '#' x#y; {write} > /dev/null",
            "an ANSI string": f"echo $'it\\'s'; {write} > /dev/null",
            "arithmetic": f"i=$((1<<2))\n{write} > /dev/null",
            "an indented heredoc before": f"cat > b.md <<-EOF\n\tIt's the card.\n\tEOF\n{write} > /dev/null",
            "a process substitution": f"diff <({write}) x > /dev/null",
            "a subshell in a substitution": f"OUT=\"$( (cd x; true); {write} )\"",
            "the verb in the variable": f"N='{CLIENT_CMD} update'; $N {one} --icon x > /dev/null",
            "a quote left open": f"{write} > /dev/null; echo it's",
        }
        for name, command in shapes.items():
            with self.subTest(shape=name):
                self.assertEqual(self.pages(command), [1])
                self.assertEqual(self.pages(command, error="Exit code 1\nrefused"), [])  # only on a call that ended well
        several = {
            "a loop over keys": (f"for k in {one} {two}; do {CLIENT_CMD} update $k --icon x > /dev/null; done", "", [1, 2]),
            "hidden, then printed": (f"{write} > /dev/null && {CLIENT_CMD} update {two} --icon x", f"updated {self.url(two)}\n", [2, 1]),
            "printed, then hidden": (f"{write} && {CLIENT_CMD} update {two} --icon x > /dev/null", f"updated {self.url(one)}\n", [1, 2]),
            "hidden, then printed through a variable": (
                f"{write} > /dev/null; {CLIENT_CMD} update $K --icon x", f"updated {self.url(two)}\n", [2, 1]),
            "each printed": (f"{write}; {CLIENT_CMD} update {two} --icon x", f"updated {self.url(one)}\nupdated {self.url(two)}\n", [1, 2]),
            "one page twice": (f"{write}; {write}", f"updated {self.url(one)}\nupdated {self.url(one)}\n", [1]),
            "one page by key and url": (f"{write}; {CLIENT_CMD} update {self.url(one)} --icon x", "", [1]),
            "created beside a hidden update": (
                f"{write} > /dev/null; {CLIENT_CMD} create --parent Tasks --set 'Task name=y'", f"created {self.url(two)} {two}\n", [2, 1]),
        }
        for name, (command, stdout, expected) in several.items():
            with self.subTest(pages=name):
                self.assertEqual(self.pages(command, stdout=stdout), expected)
        nothing = {
            "echo": f"echo notion update {one}",
            "printf": f"printf '%s' 'notion update {one}'",
            "a comment": f"# {write}\ntrue",
            "a comment after a command": f"true # ; {write}",
            "the text of a heredoc": f"cat > notes.md <<'EOF'\n{write}\nEOF",
            "an indented heredoc": f"cat > notes.md <<-EOF\n\t{write}\n\tEOF\ntrue",
            "a commit message": f"git commit -m 'x; notion update {one}'",
            "an argument": f"grep -r \"notion update {one}\" .",
            "an ANSI string": f"echo $'a\\'; {CLIENT_CMD} update {one}; echo \\'b'",
            "the arguments of a command string": f"bash -c 'echo $0' notion update {one}",
            "the arguments of code in a string": f"python3 -c 'print(1)' notion update {one}",
            "code in a string": f"python3 -c \"print('notion update {one}')\"",
            "where the client is": f"command -v notion update {one}",
            "a page in an unknown variable": f"{CLIENT_CMD} update $KEY --icon x",
            "a variable read anew": f"K={one}; read K; {CLIENT_CMD} update $K --icon x",
            "other verbs": f"{CLIENT_CMD} fetch {one}; {CLIENT_CMD} comments add {one} --body z",
            "a page only in a value": f"{CLIENT_CMD} update --set {one} $KEY",
            "another program": f"./my-notion update {one}",
        }
        for name, command in nothing.items():
            with self.subTest(nothing=name):
                self.assertEqual(self.pages(command), [])

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
        pages = [self.add(cf.task(n, "")) for n in range(1, 31)]

        def create(count):
            return self.event("mcp__claude_ai_Notion__notion-create-pages", {"pages": [{}] * count},
                              {"pages": [{"id": p["id"]} for p in pages[:count]]}, session="s-" + uuid.uuid4().hex)

        def line(count, seconds):
            many = f"{count} more pages this call wrote were" if count > 1 else "1 more page this call wrote was"
            return (f"card-check: {many} not checked inside the hook's time budget of {seconds}s; "
                    "run `card_contract.py check <ref>` on each.")

        def run(payload, budget, step=1.0, hangs=False):
            """(pages checked, seconds each check was given, message) with a clock that only the checks move."""
            module, checked, given, clock = self.hook_module(), [], [], [0.0]
            module.STARTED, module.time = 0.0, mock.Mock(monotonic=lambda: clock[0])

            def check(ref, flags, timeout=None):
                given.append(timeout)
                clock[0] += timeout if hangs else step
                found = next((p for p in self.fake.pages.values() if p["id"] == module.hyphenated(ref)), None)
                checked.append(ref)
                return (module.TIMED_OUT, "", None, None) if hangs else (1, "finding", found and found["id"], None)

            module.check = check
            code, message = self.run_module(module, payload, dict(self.env, **({"CARD_CHECK_BUDGET": budget} if budget else {})))
            self.assertEqual(code, 2 if message else 0)
            return checked, given, message

        ids = [p["id"] for p in pages]
        checked, given, message = run(create(12), "3")
        self.assertEqual((checked, given), (ids[:3], [3.0, 2.0, 1.0]))
        self.assertEqual(message.splitlines()[-1], line(9, 3))
        self.assertEqual(message.count("time budget"), 1)
        self.assertEqual(message.count("finding"), 3)
        checked, given, message = run(create(12), "3", step=1.25)  # 0.5 s left after the second: no third check
        self.assertEqual((checked, given), (ids[:2], [3.0, 1.75]))
        self.assertEqual(message.splitlines()[-1], line(10, 3))
        checked, given, message = run(create(30), None)  # the budget is 25 s, and no check gets more than that
        self.assertEqual((checked, given[0], given[-1]), (ids[:25], 25.0, 1.0))
        self.assertEqual(message.splitlines()[-1], line(5, 25))
        checked, _, message = run(create(2), "3")
        self.assertEqual(checked, ids[:2])
        self.assertNotIn("time budget", message)
        checked, _, message = run(create(3), "3")  # the last one ends with the budget: nothing was left out
        self.assertEqual(checked, ids[:3])
        self.assertNotIn("time budget", message)
        # Less than a second left: no check is started
        self.assertEqual(run(self.update(cf.key(1), session="late"), "0.95"), ([], [], line(1, 0.95)))
        self.assertEqual(run(create(2), "0.95"), ([], [], line(2, 0.95)))
        # A check that hangs gets what is left of the budget, and its page is not checked; a page named by its
        # url in the output and by its key in the command is one page
        checked, given, message = run(self.update(cf.key(1), session="hangs"), "3", hangs=True)
        self.assertEqual((checked, given, message), ([self.url(cf.key(1))], [3.0], line(1, 3)))
        hidden = self.bash(f"{CLIENT_CMD} update {cf.key(1)} --icon x > /dev/null; {CLIENT_CMD} update {cf.key(2)} --icon x",
                           stdout=f"updated {self.url(cf.key(2))}\n", session="hidden")
        self.assertEqual(run(hidden, "3", hangs=True)[2], line(2, 3))
        # As the host runs it, the hanging check is stopped: the bound is far from the sleep on any machine
        wrapper = self.client.read_text()
        self.assertIn("def main(argv=None):\n", wrapper)
        self.client.write_text(wrapper.replace("def main(argv=None):\n", "def main(argv=None):\n    import time\n"
                                                                         "    time.sleep(300)\n"))
        started = time.monotonic()
        slow = self.hook(self.event("mcp__x__notion-update-page", {"page_id": ids[0], "command": "update_content"}, {}),
                         env=dict(self.env, CARD_CHECK_BUDGET="3"))
        self.assertLess(time.monotonic() - started, 120)
        self.assertEqual((slow.returncode, slow.stderr.strip()), (2, line(1, 3)))
        # The budget is the host's timeout of door 3 less a margin, and a setting can only lower it
        module = self.hook_module()
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

    def test_the_whole_body_flag_belongs_to_one_page(self):
        mine = self.add(cf.task(1, ""))
        theirs = self.add(cf.task(2, "", assignee=(BRUNO,)))
        old = self.add(cf.task(3, "", created="2026-10-01T10:00:00.000Z"))
        one, two, three = (cf.key(n) for n in (1, 2, 3))
        lines = [f"updated {page['url']}\n" for page in (mine, theirs, old)]
        replace, change = f"{CLIENT_CMD} update {one} --replace-file f.md", f"{CLIENT_CMD} update {two} --set 'Status=Done'"

        # As the host runs it: the other person's card is judged only when its own write replaced it
        for session, command in enumerate((f"{replace} && {change}", f"{change} && {replace}",
                                           f"{CLIENT_CMD} update {mine['url']} --replace-file f.md && {change}",
                                           f"{change}; echo --replace-file; {replace}")):
            with self.subTest(command=command):
                proc = self.hook(self.bash(command, stdout=lines[0] + lines[1], session=f"flag-{session}"))
                self.assertSays(proc, mine["url"])
                self.assertNotIn(theirs["url"], proc.stderr)
        self.assertSays(self.hook(self.bash(f"for k in -h {two}; do {CLIENT_CMD} update $k --replace-file f.md; done", stdout=lines[1])),
                        theirs["url"])
        for session, ref in enumerate((two, two.lower(), two.replace("-", "-0"), theirs["url"], theirs["id"], cf.hex32(theirs["id"]))):
            with self.subTest(named=ref):
                proc = self.hook(self.bash(f"{CLIENT_CMD} update {one} --set 'Status=Done'; {CLIENT_CMD} update {ref} --replace-file f.md",
                                           stdout=lines[0] + lines[1], session=f"named-{session}"))
                self.assertSays(proc, mine["url"], theirs["url"])
        proc = self.hook(self.bash(f"{CLIENT_CMD} update {three} --set 'Status=Done' && {replace}", stdout=lines[2] + lines[0]))
        self.assertNotIn(old["url"], proc.stderr)  # nor a card older than the pattern

        through = f"{CLIENT_CMD} update $K"
        cases = {  # command, output, the pages checked as replaced
            "one page": (replace, lines[0], [1]),
            "one page, no output": (f"{replace} > /dev/null", "", [1]),
            "the value glued": (f"{CLIENT_CMD} update {one} --replace-file=f.md", lines[0], [1]),
            "the flag cut short": (f"{CLIENT_CMD} update --rep f.md {one}", lines[0], [1]),
            "one of two": (f"{replace} && {change}", lines[0] + lines[1], [1]),
            "one of two, hidden": (f"{replace} > /dev/null && {change}", lines[1], [1]),
            "both": (f"{replace}; {CLIENT_CMD} update {two} --replace-file g.md", lines[0] + lines[1], [1, 2]),
            "written twice, replaced once": (f"{CLIENT_CMD} update {one} --set 'Status=Done'; {replace}", lines[0] * 2, [1]),
            "a loop that names its pages": (f"for k in {one} {two}; do {CLIENT_CMD} update $k --replace-file f; done", lines[0] + lines[1], [1, 2]),
            "the page in a variable of the command": (f"K={one}; {through} --replace-file f; {change}", lines[0] + lines[1], [1]),
            "an unknown page, one written": (f"{through} --replace-file f.md", lines[1], [2]),
            "an unknown page after a fetch, one written": (f"{CLIENT_CMD} fetch {one} > x; {through} --replace-file f.md", lines[1], [2]),
            "an unknown loop, one written": (f"while read K; do {through} --replace-file f.md; done < l", lines[1], [2]),
            "an unknown loop, two written": (f"while read K; do {through} --replace-file f.md; done < l", lines[0] + lines[1], []),
            "two unknown pages, one replaced": (f"{through} --replace-file f; {CLIENT_CMD} update $J --set a=b", lines[0] + lines[1], []),
            "an unknown page beside a known one": (f"{change}; {through} --replace-file f.md", lines[1] + lines[0], []),
            "a known page replaced beside an unknown one": (f"{replace}; {through} --set a=b", lines[0] + lines[1], [1]),
            "one page created, an unknown one replaced": (
                f"{CLIENT_CMD} create --parent T --set a=b; {through} --replace-file f.md || true", f"created {theirs['url']} {two}\n", []),
            "a comment": (f"{change} # not --replace-file f.md", lines[1], []),
            "a comment on a line of its own": (f"# notion update {two} --replace-file f.md\n{change}", lines[1], []),
            "an echo": (f"echo notion update {two} --replace-file f.md; {change}", lines[1], []),
            "a heredoc": (f"cat > n.md <<'EOF'\nnotion update {two} --replace-file f.md\nEOF\n{change}", lines[1], []),
            "a value": (f"{CLIENT_CMD} update {two} --set 'Resumo=use --replace-file' --edit a '--replace-file b'", lines[1], []),
            "another program": (f"./tool update {two} --replace-file f.md; {change}", lines[1], []),
            "a shape the reading does not open": (f"xargs {CLIENT_CMD} update --replace-file f.md", lines[1], []),
            "append is not replace": (f"{CLIENT_CMD} update {two} --append-file f.md", lines[1], []),
            "a quote left open, one write": (f"{replace}; echo it's", lines[0], [1]),
            "a quote left open, one write after a fetch": (f"{CLIENT_CMD} fetch {two} > x; {replace}; echo it's", lines[0], [1]),
            "a quote left open, several writes": (f"{replace}; {change}; echo it's", lines[0] + lines[1], []),
        }
        for name, (command, stdout, expected) in cases.items():
            with self.subTest(case=name):
                marked, checked = self.marked(command, stdout=stdout)
                self.assertEqual(marked, expected)
                self.assertTrue(checked)
        # A call that failed: the page the output shows takes the flag of its own call
        for command, shown, expected in ((f"{replace} && {change}", lines[0], [1]), (f"{change} && {replace}", lines[1], []),
                                         (f"{change} && {through} --replace-file f.md", lines[1], []),
                                         (f"{through} --replace-file f.md && false", lines[1], [2])):
            with self.subTest(failed=command):
                self.assertEqual(self.marked(command, error="Exit code 2\n" + shown)[0], expected)

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

    def test_a_fetch_pins_only_when_nothing_else_in_the_command_prints(self):
        other = self.add(cf.task(1, "## Pedido\n\nOutro pedido.\nCom uma segunda linha.\n\n" + GOOD.split("\n\n", 2)[2]))
        page = self.add(cf.task(2, GOOD))
        outputs = {}
        for found in (other, page):
            proc = subprocess.run([str(self.client), "fetch", found["id"]], capture_output=True, text=True, env=self.env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outputs[found["id"]] = proc.stdout
        whole, old = outputs[page["id"]], outputs[other["id"]]
        cut = old[: old.index("Com uma segunda linha.")]
        pins = self.home / ".cache" / "cdv-notion" / "card-pins"
        module = self.hook_module()

        def pinned(command, stdout=whole):
            for stale in sorted(pins.glob("*.json")) if pins.is_dir() else []:
                stale.unlink()  # each command alone
            self.assertEqual(self.run_module(module, self.bash(command, stdout=stdout)), (0, ""))
            return [path.stem for path in sorted(pins.glob("*.json"))] if pins.is_dir() else []

        fetch = f"{CLIENT_CMD} fetch {cf.key(2)}"
        for name, command, stdout in (
                ("a cut copy of another card", f"head -20 old.txt; {fetch}", cut + whole),
                ("a whole copy of another card", f"cat old.txt; {fetch}", old + whole),
                ("the copy after", f"{fetch}; cat old.txt", whole + old)):
            with self.subTest(read=name):
                self.assertEqual(pinned(command, stdout), [])
        # As the host runs it
        self.assertSilent(self.hook(self.bash(f"head -20 old.txt; {fetch}", stdout=cut + whole)))
        self.assertEqual(sorted(pins.glob("*.json")) if pins.is_dir() else [], [])
        for command in (f"echo x; {fetch}", f"true && {fetch}", f"pwd\n{fetch}", f"cd - && {fetch}", f"cd x || {fetch}", f"cd x | {fetch}",
                        f"cd x & {fetch}", f"echo id | {fetch}", f"export X=1; {fetch}", f"exec 2>&1; {fetch}", f"cd x; ls; {fetch}",
                        f"if true; then {fetch}; fi", f"for i in 1; do {fetch}; done", f"({fetch})", f"{{ {fetch}; }}", f"! {fetch}",
                        f"bash -c '{fetch}'", f"OUT=$({fetch})", f"echo \"$({fetch})\"", f"{fetch} &", f"{fetch} | cat", f"{fetch} > f.md",
                        f"> f.md {fetch}", f"{fetch} 2>&1", f"{fetch} < /dev/null", f"{fetch}; cd x", f"{fetch} && {fetch}",
                        f"X=$({fetch}); {fetch}", f"{fetch}; echo it's", "N=$(which notion) fetch"):
            with self.subTest(nothing=command):
                self.assertEqual(pinned(command), [])
        for command in (fetch, f"cd x && {fetch}", f"cd x; {fetch}", f"cd x\n{fetch}\n", f"cd \"$(git rev-parse --show-toplevel)\" &&\n  {fetch}",
                        f"cd x > /dev/null && {fetch}", f"X=1; {fetch}", f"X=1 {fetch}", f"X=$(cat old.txt); {fetch}", f"cd x && A=1 B=2 && {fetch};",
                        f"N={CLIENT_CMD}; $N fetch {cf.key(2)}", f"timeout 60 {fetch}", f"python3 -u {fetch}", f"# the card\n{fetch} # whole",
                        f"{CLIENT_CMD} \\\n  fetch {cf.key(2)}"):
            with self.subTest(pinned=command):
                self.assertEqual(pinned(command), [page["id"]])


if __name__ == "__main__":
    unittest.main()
