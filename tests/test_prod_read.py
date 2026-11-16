"""Production is read through one script: bin/prod-read against a fake `ssh` on PATH (never a real
host), and the cdv-prod skill's rules (S6)."""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unittest

from helpers import REPO_ROOT, HarnessTestCase
from test_kickoff_profile import sentences

PROD_READ = REPO_ROOT / "bin" / "prod-read"
SKILL = REPO_ROOT / "skills" / "cdv-prod" / "SKILL.md"
READONLY = "DB::statement('SET SESSION TRANSACTION READ ONLY');"
DOOR_7 = "docker exec -i -u www-data $(docker ps -qf name=acme_app) sh -c 'php artisan tinker --execute \"$(cat)\"'"

# The fake ssh records argv and stdin, prints $FAKE_SSH_OUTPUT, sleeps $FAKE_SSH_SLEEP, exits $FAKE_SSH_EXIT.
FAKE_SSH = """#!{python}
import json, os, sys, time
text = sys.stdin.read()
with open(os.environ["FAKE_SSH_CALLS"], "a") as log:
    log.write(json.dumps({{"argv": sys.argv[1:], "stdin": text}}) + "\\n")
sys.stdout.write(os.environ.get("FAKE_SSH_OUTPUT", ""))
sys.stdout.flush()
time.sleep(float(os.environ.get("FAKE_SSH_SLEEP", "0")))
sys.exit(int(os.environ.get("FAKE_SSH_EXIT", "0")))
"""

PROFILE = {
    "prod_ssh_target": "prod.example.invalid",
    "prod_app_container": "acme_app",
    "prod_exec_user": "www-data",
    "prod_session_readonly_sql": "SET SESSION TRANSACTION READ ONLY",
    "prod_row_cap": "50",
    "prod_timeout_seconds": "20",
    "prod_job_runs_table": "job_runs job started_at",
}


class ProdReadTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.tmp / "repo"
        (self.root / ".claude" / "harness").mkdir(parents=True)
        self.calls = self.tmp / "ssh-calls.jsonl"
        self.log = self.tmp / "prod-read.log"
        ssh = self.bin_dir / "ssh"
        ssh.write_text(FAKE_SSH.format(python=sys.executable))
        ssh.chmod(0o755)
        self.probe = self.root / "probe.php"
        self.probe.write_text("echo App\\Models\\Invoice::count();\n")
        self.profile()

    def profile(self, **changes):
        values = dict(PROFILE, prod_log=str(self.log))
        values.update(changes)
        text = "".join(f"{key}: {value}\n" for key, value in values.items() if value is not None)
        (self.root / ".claude" / "harness" / "profile.yaml").write_text(text)

    def read(self, *args, output="", sleep="0", exit_code="0"):
        env = dict(
            self.env,
            PATH=f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            FAKE_SSH_CALLS=str(self.calls),
            FAKE_SSH_OUTPUT=output,
            FAKE_SSH_SLEEP=sleep,
            FAKE_SSH_EXIT=exit_code,
        )
        return subprocess.run(
            [sys.executable, str(PROD_READ), "--root", str(self.root), *[str(a) for a in args]],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )

    def ssh_calls(self):
        if not self.calls.exists():
            return []
        return [json.loads(line) for line in self.calls.read_text().splitlines() if line.strip()]

    def test_missing_or_none_ssh_target_exits_2_without_connecting(self):
        for value in (None, "none"):
            with self.subTest(prod_ssh_target=value):
                self.profile(prod_ssh_target=value)
                proc = self.read("--probe", self.probe)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn("prod_ssh_target", proc.stderr)
                self.assertEqual(self.ssh_calls(), [])

    def test_probe_text_starts_with_the_readonly_statement(self):
        proc = self.read("--probe", self.probe, output="12\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout, "12\n")
        [call] = self.ssh_calls()
        self.assertEqual(call["argv"], ["prod.example.invalid", DOOR_7])
        text = call["stdin"]
        self.assertTrue(text.startswith(READONLY), text)
        self.assertNotIn("setDefaultConnection", text)
        self.assertEqual(text[len(READONLY):].strip(), self.probe.read_text().strip())

    def test_readonly_connection_comes_before_the_statement(self):
        self.profile(prod_readonly_connection="mysql_readonly")
        self.assertEqual(self.read("--probe", self.probe).returncode, 0)
        [call] = self.ssh_calls()
        self.assertEqual(call["argv"], ["prod.example.invalid", DOOR_7])
        text = call["stdin"]
        connection = "DB::setDefaultConnection('mysql_readonly');"
        self.assertTrue(text.startswith(connection), text)
        rest = text[len(connection):].lstrip()
        self.assertTrue(rest.startswith(READONLY), rest)
        self.assertEqual(rest[len(READONLY):].strip(), self.probe.read_text().strip())

    def test_output_over_the_row_cap_is_cut_with_a_count_line(self):
        self.profile(prod_row_cap="3")
        proc = self.read("--probe", self.probe, output="".join(f"row {n}\n" for n in range(1, 6)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertEqual(lines[:3], ["row 1", "row 2", "row 3"])
        self.assertEqual(len(lines), 4, proc.stdout)
        self.assertRegex(lines[3], r"\b2\b.*\bcut\b")
        self.assertNotIn("row 4", proc.stdout)

    def test_ssh_over_the_timeout_is_stopped_and_exits_4(self):
        self.profile(prod_timeout_seconds="1")
        started = time.monotonic()
        proc = self.read("--probe", self.probe, sleep="30")
        self.assertEqual(proc.returncode, 4, proc.stdout + proc.stderr)
        self.assertLess(time.monotonic() - started, 10)

    def test_log_line_has_time_mode_hash_and_exit_code_and_no_output(self):
        proc = self.read("--probe", self.probe, output="secret-row-value\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 1, lines)
        line = lines[0]
        self.assertRegex(line, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
        self.assertRegex(line, r"\bprobe\b")
        self.assertIn(hashlib.sha256(self.probe.read_bytes()).hexdigest(), line)
        self.assertRegex(line, r"\b0\s*$")
        self.assertNotIn("secret-row-value", line)
        self.read("--migrate-status", exit_code="1")
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 2, lines)
        self.assertRegex(lines[1], r"\bmigrate-status\b.*\b4\s*$")

    def test_each_fixed_read_sends_its_command(self):
        cases = [
            (["--migrate-status"], [r"Artisan::call\('migrate:status'\)"]),
            (["--failed-jobs"], [r"Artisan::call\('queue:failed'\)"]),
            (["--job-runs", "nightly-sync"], [r"DB::table\('job_runs'\)", r"'job'", r"nightly-sync", r"'started_at'"]),
            (["--logs", "Timeout while"], [r"storage_path\('logs'\)", r"'Timeout while'"]),
        ]
        for args, patterns in cases:
            with self.subTest(read=args[0]):
                self.calls.unlink(missing_ok=True)
                proc = self.read(*args, output="ok\n")
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                [call] = self.ssh_calls()
                self.assertEqual(call["argv"], ["prod.example.invalid", DOOR_7])
                self.assertTrue(call["stdin"].startswith(READONLY), call["stdin"])
                for pattern in patterns:
                    self.assertRegex(call["stdin"], pattern)

    def test_another_command_exits_3(self):
        for args in (["--artisan", "migrate"], ["--shell"], ["migrate:fresh"], ["--exec", "DB::table('invoices')->delete();"]):
            with self.subTest(args=args):
                proc = self.read(*args)
                self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
                self.assertEqual(self.ssh_calls(), [])

    def test_ssh_failure_exits_4(self):
        proc = self.read("--probe", self.probe, exit_code="255")
        self.assertEqual(proc.returncode, 4)

    def test_missing_log_key_exits_2_without_connecting(self):
        self.profile(prod_log=None)
        proc = self.read("--probe", self.probe)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("prod_log", proc.stderr)
        self.assertEqual(self.ssh_calls(), [])

    def test_job_runs_without_its_table_key_exits_2_without_connecting(self):
        self.profile(prod_job_runs_table=None)
        proc = self.read("--job-runs", "nightly-sync")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("prod_job_runs_table", proc.stderr)
        self.assertEqual(self.ssh_calls(), [])

    def test_quotes_in_a_pattern_stay_inside_the_php_string(self):
        self.assertEqual(self.read("--logs", "it's").returncode, 0)
        [call] = self.ssh_calls()
        self.assertIn("'it\\'s'", call["stdin"])

    def test_local_profile_wins(self):
        (self.root / ".claude" / "harness" / "profile.local.yaml").write_text("prod_ssh_target: none\n")
        self.assertEqual(self.read("--probe", self.probe).returncode, 2)
        self.assertEqual(self.ssh_calls(), [])

    def test_executable(self):
        self.assertTrue(os.access(PROD_READ, os.X_OK))


class ProdSkillTest(unittest.TestCase):
    def assertSentence(self, *patterns):
        regexes = [re.compile(p, re.I) for p in patterns]
        found = [s for s in sentences(SKILL.read_text(encoding="utf-8")) if all(r.search(s) for r in regexes)]
        self.assertTrue(found, f"no sentence of cdv-prod/SKILL.md holds all of {patterns}")
        return found

    def test_prod_reads_the_local_copy_first(self):
        self.assertSentence(r"question about registry data", r"local copy", r"first")
        self.assertSentence(
            r"read production only for",
            r"run history",
            r"state after a deploy",
            r"environment",
        )

    def test_production_write_is_one_guarded_question_never_unattended(self):
        self.assertSentence(r"production write", r"one question per mutation", r"labell?ed", r"production")
        self.assertSentence(r"guard(ed)? (the statement )?by the old value")
        self.assertSentence(r"print the row before and after")
        self.assertSentence(r"never run", r"unattended mode")


if __name__ == "__main__":
    unittest.main()
