"""The headless probe's session (tests/probe_hooks_headless.py) as it calls the CLI: a fake `claude`
that prints the arguments it was given, so no real session runs here."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import probe_hooks_headless as probe

FAKE_CLAUDE = "#!{python}\nimport json, sys\nprint(json.dumps({{'argv': sys.argv[1:]}}))\n"


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


if __name__ == "__main__":
    unittest.main()
