import json
import random
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import REPO_ROOT, HarnessTestCase

HOOKS = ["require-model", "prod-ssh", "suite-lock"]
PROD_HOST = "prod.example.invalid"
ROLE_LINES = ["role_builder: personal sonnet high", "role_verifier: personal opus high"]


class HookCase(HarnessTestCase):
    """A repository with the core hooks installed where sync puts them."""

    def setUp(self):
        super().setUp()
        self.repo = self.tmp / "repo"
        hooks_dir = self.repo / ".claude" / "harness" / "hooks"
        hooks_dir.mkdir(parents=True)
        for path in (REPO_ROOT / "hooks").iterdir():
            if path.is_file() and not path.name.endswith(".pyc"):
                shutil.copy2(path, hooks_dir / path.name)
        self.hooks_dir = hooks_dir

    def write_profile(self, text):
        (self.repo / ".claude" / "harness" / "profile.yaml").write_text(text)

    def hook(self, name, payload):
        data = payload if isinstance(payload, str) else json.dumps(payload)
        proc = subprocess.run(
            [str(self.hooks_dir / name)], input=data, text=True, capture_output=True, cwd=str(self.repo), env=self.env
        )
        return proc

    def call(self, tool_name, tool_input):
        return {
            "session_id": "s1",
            "cwd": str(self.repo),
            "permission_mode": "bypassPermissions",
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": "t1",
        }

    def bash(self, command):
        return self.call("Bash", {"command": command, "description": "x"})

    def assertBlocks(self, proc, *needles):
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        for needle in needles:
            self.assertIn(needle, proc.stderr)

    def assertAllows(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class RequireModelTest(HookCase):
    def setUp(self):
        super().setUp()
        self.write_profile(
            "repo_name: app\ndelegate_tool: mcp__orchestrator__delegate_task\n" + "\n".join(ROLE_LINES) + "\n"
        )

    def test_subagent_without_model_exits_2_with_the_role_table(self):
        for tool in ("Agent", "Task"):
            with self.subTest(tool=tool):
                proc = self.hook(
                    "require-model",
                    self.call(tool, {"description": "d", "prompt": "p", "subagent_type": "general-purpose"}),
                )
                self.assertBlocks(proc, *ROLE_LINES)
        empty = self.hook("require-model", self.call("Agent", {"prompt": "p", "model": ""}))
        self.assertBlocks(empty, *ROLE_LINES)

    def test_delegation_without_model_or_with_inherit_exits_2(self):
        tool = "mcp__orchestrator__delegate_task"
        for tool_input in (
            {"task": "build", "target": {"provider": "acct"}},
            {"task": "build", "target": {"provider": "acct", "model": "inherit"}},
            {"task": "build"},
        ):
            with self.subTest(tool_input=tool_input):
                self.assertBlocks(self.hook("require-model", self.call(tool, tool_input)), *ROLE_LINES)
        named = self.hook("require-model", self.call(tool, {"task": "b", "target": {"provider": "a", "model": "m-1"}}))
        self.assertAllows(named)
        other = self.hook("require-model", self.call("mcp__other__tool", {"x": 1}))
        self.assertAllows(other)

    def test_fork_and_named_model_exit_0(self):
        self.assertAllows(self.hook("require-model", self.call("Agent", {"prompt": "p", "subagent_type": "fork"})))
        self.assertAllows(
            self.hook("require-model", self.call("Agent", {"prompt": "p", "subagent_type": "Explore", "model": "sonnet"}))
        )
        self.assertAllows(self.hook("require-model", self.call("Task", {"prompt": "p", "model": "sonnet"})))


class ProdSshTest(HookCase):
    def setUp(self):
        super().setUp()
        self.write_profile(f"repo_name: app\nprod_hosts:\n  - {PROD_HOST}\n  - 203.0.113.7\n")

    def test_ssh_to_a_production_host_exits_2_naming_the_script(self):
        for command in (
            f"ssh {PROD_HOST} 'docker ps'",
            f"ssh deploy@{PROD_HOST} uptime",
            f"ssh -p 2222 -i ~/.ssh/key {PROD_HOST}",
            "ssh root@203.0.113.7 'ls /'",
            f"cd /tmp && ssh {PROD_HOST} true",
            f'bash -c "ssh {PROD_HOST} true"',
            f"echo $(ssh {PROD_HOST} hostname)",
            f"/usr/bin/ssh {PROD_HOST.upper()} true",
        ):
            with self.subTest(command=command):
                self.assertBlocks(self.hook("prod-ssh", self.bash(command)), ".claude/harness/bin/prod-read")

    def test_allowed_commands_exit_0(self):
        for command in (
            "ssh staging.example.invalid true",
            "docker build --ssh default .",
            f".claude/harness/bin/prod-read --probe probe.php",
            f"echo {PROD_HOST}",
            "git push origin feat/x",
        ):
            with self.subTest(command=command):
                self.assertAllows(self.hook("prod-ssh", self.bash(command)))
        self.write_profile("repo_name: app\nprod_hosts:\n")
        self.assertAllows(self.hook("prod-ssh", self.bash(f"ssh {PROD_HOST} true")))
        self.write_profile("repo_name: app\n")
        self.assertAllows(self.hook("prod-ssh", self.bash(f"ssh {PROD_HOST} true")))


class SuiteLockTest(HookCase):
    def setUp(self):
        super().setUp()
        tag = random.randint(100000, 999999)
        self.test_cmd = f"sleep {tag}1"
        self.analysis_cmd = f"sleep {tag}2"
        self.write_profile(
            f"repo_name: app\ncmd_test_backend: {self.test_cmd}\ncmd_static_analysis: {self.analysis_cmd}\n"
            f"cmd_test_backend_filter: {self.test_cmd} --filter\n"
        )

    def start(self, command, cwd=None):
        proc = subprocess.Popen(command.split(), cwd=str(cwd or self.repo))
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        return proc

    def start_waiting(self, *args):
        """A process in the repository whose arguments carry `args`, as a test runner's would."""
        argv = [sys.executable, "-c", "import time; time.sleep(120)", *args]
        proc = subprocess.Popen(argv, cwd=str(self.repo))
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        return proc

    def test_full_suite_while_static_analysis_runs_exits_2(self):
        self.start(self.analysis_cmd)
        self.assertBlocks(self.hook("suite-lock", self.bash(self.test_cmd)), "static analysis")
        self.assertBlocks(self.hook("suite-lock", self.bash(f"cd src && {self.test_cmd} --parallel")))
        for command in (
            f"{self.test_cmd} 2>&1 | tail -50",
            f"{self.test_cmd} > out.txt",
            f"{self.test_cmd} >> out.txt 2> err.txt",
            f"{self.test_cmd} --processes 4 2>&1 | tee out.txt",
            f"{self.test_cmd} -c phpunit.xml",
            f"{self.test_cmd} --configuration phpunit.xml",
            f"{self.test_cmd} --log-junit report.xml",
            f"{self.test_cmd} --coverage-html build/coverage 2>&1 | tail -50",
            f"{self.test_cmd} --testdox-xml out.xml",
            f"{self.test_cmd} --some-future-report out/report.json",
            f"{self.test_cmd} --log-custom=build/report.log",
        ):
            with self.subTest(command=command):
                self.assertBlocks(self.hook("suite-lock", self.bash(command)), "static analysis")

    def test_static_analysis_while_full_suite_runs_exits_2(self):
        bare = self.start(self.test_cmd)
        self.assertBlocks(self.hook("suite-lock", self.bash(self.analysis_cmd)), "test suite")
        self.assertBlocks(self.hook("suite-lock", self.bash(f"{self.analysis_cmd} 2>&1 | tail -50")), "test suite")
        bare.kill()
        bare.wait()
        for options in (
            ["-c", "phpunit.xml"], ["--log-junit", "report.xml"], ["--coverage-html", "build/coverage"],
            ["--testdox-xml", "out.xml"],
        ):
            with self.subTest(running=options):
                suite = self.start_waiting(*self.test_cmd.split(), *options)
                self.assertBlocks(self.hook("suite-lock", self.bash(self.analysis_cmd)), "test suite")
                suite.kill()
                suite.wait()

    def test_a_profile_command_with_a_leading_cd_still_blocks_both_ways(self):
        self.write_profile(
            f"repo_name: app\ncmd_test_backend: cd . && {self.test_cmd}\n"
            f"cmd_static_analysis: cd . && {self.analysis_cmd}\n"
            f"cmd_test_backend_filter: cd . && {self.test_cmd} --filter\n"
        )
        analysis = self.start(self.analysis_cmd)
        self.assertBlocks(self.hook("suite-lock", self.bash(f"cd . && {self.test_cmd}")), "static analysis")
        self.assertBlocks(self.hook("suite-lock", self.bash(self.test_cmd)), "static analysis")
        self.assertAllows(self.hook("suite-lock", self.bash(f"cd . && {self.test_cmd} --filter=InvoiceTest")))
        analysis.kill()
        analysis.wait()
        suite = self.start(self.test_cmd)
        self.assertBlocks(self.hook("suite-lock", self.bash(f"cd . && {self.analysis_cmd}")), "test suite")
        self.assertBlocks(self.hook("suite-lock", self.bash(self.analysis_cmd)), "test suite")
        suite.kill()
        suite.wait()
        self.assertAllows(self.hook("suite-lock", self.bash(f"cd . && {self.analysis_cmd}")))

    def test_filtered_suite_or_nothing_running_exits_0(self):
        self.assertAllows(self.hook("suite-lock", self.bash(self.test_cmd)))
        self.assertAllows(self.hook("suite-lock", self.bash(self.analysis_cmd)))
        other = self.tmp / "other-repo"
        other.mkdir()
        self.start(self.analysis_cmd, cwd=other)
        self.assertAllows(self.hook("suite-lock", self.bash(self.test_cmd)))
        self.start(self.analysis_cmd)
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} --filter=InvoiceTest")))
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} tests/Feature/InvoiceTest.php")))
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} --filter InvoiceTest > out.txt")))
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} tests/Feature 2>&1 | tail -50")))
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} -c phpunit.xml tests/Feature/InvoiceTest.php")))
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} --log-junit report.xml --filter InvoiceTest")))
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} Tests/Unit/InvoiceTest::testTotal")))
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} --testdox-xml out.xml --filter InvoiceTest")))
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} tests/Unit")))
        (self.repo / "modules").mkdir()
        self.assertAllows(self.hook("suite-lock", self.bash(f"{self.test_cmd} modules")))
        self.assertAllows(self.hook("suite-lock", self.bash("git status")))


class FailOpenTest(HookCase):
    def blocking_inputs(self):
        return {
            "require-model": self.call("Agent", {"prompt": "p", "subagent_type": "general-purpose"}),
            "prod-ssh": self.bash(f"ssh {PROD_HOST} true"),
            "suite-lock": self.bash("sleep 1234561"),
        }

    def test_each_hook_exits_0_without_a_profile_or_json(self):
        profile = (
            f"repo_name: app\nprod_hosts:\n  - {PROD_HOST}\ncmd_test_backend: sleep 1234561\n"
            "cmd_static_analysis: sleep 1234562\n"
        )
        self.write_profile(profile)
        analysis = subprocess.Popen(["sleep", "1234562"], cwd=str(self.repo))
        self.addCleanup(analysis.wait)
        self.addCleanup(analysis.kill)
        inputs = self.blocking_inputs()
        for name in HOOKS:
            with self.subTest(hook=name, case="with a profile it blocks"):
                self.assertBlocks(self.hook(name, inputs[name]))
        for name in HOOKS:
            with self.subTest(hook=name, case="not JSON"):
                self.assertAllows(self.hook(name, "this is not json {"))
                self.assertAllows(self.hook(name, '["a list"]'))
        (self.repo / ".claude" / "harness" / "profile.yaml").unlink()
        for name in HOOKS:
            with self.subTest(hook=name, case="no profile"):
                self.assertAllows(self.hook(name, inputs[name]))

    def test_hooks_write_no_bytecode_beside_themselves(self):
        self.write_profile(f"repo_name: app\nprod_hosts:\n  - {PROD_HOST}\n")
        for name in HOOKS:
            self.hook(name, self.bash("true"))
        self.assertEqual(sorted(p.name for p in self.hooks_dir.iterdir() if p.is_dir()), [])


if __name__ == "__main__":
    unittest.main()
