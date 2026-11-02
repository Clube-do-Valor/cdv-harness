"""Shared fixtures: a minimal core with tags, a consumer repository, a bare remote and fake CLIs."""

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS = REPO_ROOT / "bin" / "harness"
VERIFY = REPO_ROOT / "bin" / "verify.sh"
SCHEMA = REPO_ROOT / "profile.schema.yaml"

SOURCE_URL = "https://example.com/acme/harness.git"
OLD_DATE = "2026-01-01T12:00:00 +0000"

HOUSE_V1 = "## House rules\n\nKeep changes small.\n"
HOUSE_V2 = "## House rules\n\nKeep changes small.\nAsk before a rewrite.\n"

DENY_V1 = ["Bash(rm -rf /)", "Edit(.env)"]
DENY_V2 = ["Bash(rm -rf /)", "Edit(.env*)", "Read(secrets/**)"]


def load_tool():
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("harness_tool", str(HARNESS))
    spec = importlib.util.spec_from_loader("harness_tool", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def skill_text(name, description="Does one thing in the harness.", version="0.1.0", owner="acme-team"):
    return (
        f"---\nname: {name}\ndescription: >\n  {description}\nmetadata:\n  version: {version}\n  owner: {owner}\n---\n\n"
        f"# {name}\n\nBody of the skill.\n"
    )


def rule_text(extra=""):
    return (
        "---\npaths:\n  - \"{app_dir}/app/**\"\n  - docs/**\n---\n\n"
        "Work from `{app_dir}/` when editing application code.\n" + extra
    )


def core_v1():
    files = {
        "skills/cdv-debug/SKILL.md": skill_text("cdv-debug"),
        "skills/cdv-debug/references/notes.md": "Notes v1.\n",
        "skills/cdv-debug/scripts/run.sh": ("#!/bin/sh\necho run\n", True),
        "skills/cdv-grilling/SKILL.md": skill_text("cdv-grilling"),
        "skills/cdv-grill-me/SKILL.md": skill_text("cdv-grill-me"),
        "skills/cdv-research-round/SKILL.md": skill_text("cdv-research-round"),
        "rules/core/testing.md": rule_text(),
        "rules/core/legacy.md": "---\npaths:\n  - docs/**\n---\n\nLegacy rule.\n",
        "bin/verify.sh": (VERIFY.read_text(), True),
        "settings/deny-core.json": json.dumps({"deny": DENY_V1}, indent=2) + "\n",
        "instructions/house.md": HOUSE_V1,
        "profile.schema.yaml": SCHEMA.read_text(),
    }
    return files


def core_v2_changes():
    """(files to write, files to remove) taking v1 to v2."""
    return (
        {
            "skills/cdv-debug/SKILL.md": skill_text("cdv-debug", version="0.2.0"),
            "skills/cdv-debug/references/extra.md": "Extra reference.\n",
            "rules/core/testing.md": rule_text("Second paragraph.\n"),
            "settings/deny-core.json": json.dumps({"deny": DENY_V2}, indent=2) + "\n",
            "instructions/house.md": HOUSE_V2,
        },
        ["skills/cdv-debug/references/notes.md", "rules/core/legacy.md"],
    )


def fake_token(kind):
    """Build strings the public scan patterns flag, without writing them literally."""
    return {
        "collection": "collec" + "tion://" + "abc",
        "bitbucket": "https://bitbucket" + ".org/" + "someworkspace/repo",
        "brazil": "host." + "example" + ".com" + ".br",
        "home": "/ho" + "me/" + "someone/project",
        "ticket": "AB" + "C-123",
        "slack": "xo" + "xb-" + "1234567890",
        "aws": "AK" + "IA" + "A" * 16,
        "github": "gh" + "p_" + "x" * 36,
        "email": "someone" + "@" + "acme-corp.io",
    }[kind]


def run(cmd, cwd=None, env=None, check=True, input_text=None):
    proc = subprocess.run(
        [str(c) for c in cmd], cwd=str(cwd) if cwd else None, env=env, text=True, capture_output=True, input=input_text
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"{cmd} failed ({proc.returncode}): {proc.stdout}\n{proc.stderr}")
    return proc


class HarnessTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="harness-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "HARNESS_"))}
        self.env.update(
            {
                "HOME": str(self.home),
                "GIT_AUTHOR_NAME": "Test Author",
                "GIT_AUTHOR_EMAIL": "test@example.com",
                "GIT_COMMITTER_NAME": "Test Author",
                "GIT_COMMITTER_EMAIL": "test@example.com",
                "GIT_CONFIG_GLOBAL": str(self.tmp / "gitconfig"),
                "GIT_CONFIG_NOSYSTEM": "1",
            }
        )
        (self.tmp / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n[protocol \"file\"]\n\tallow = always\n")
        self.bin_dir = self.tmp / "fakebin"
        self.bin_dir.mkdir()

    # -- running things ---------------------------------------------------------------

    def git(self, cwd, *args, check=True, env=None):
        return run(["git", *args], cwd=cwd, env=env or self.env, check=check)

    def harness(self, *args, cwd=None, check=False, env=None):
        return run([sys.executable, HARNESS, *args], cwd=cwd or self.tmp, env=env or self.env, check=check)

    # -- the core ---------------------------------------------------------------------

    def write_tree(self, root, files):
        for relative, content in files.items():
            executable = False
            if isinstance(content, tuple):
                content, executable = content
            path = Path(root) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            path.chmod(0o755 if executable else 0o644)

    def commit_core(self, core, files, remove=(), message="chore: change", tag=None, date=None):
        self.write_tree(core, files)
        for relative in remove:
            (Path(core) / relative).unlink()
        env = dict(self.env)
        if date:
            env["GIT_COMMITTER_DATE"] = date
            env["GIT_AUTHOR_DATE"] = date
        self.git(core, "add", "-A", env=env)
        self.git(core, "commit", "-q", "-m", message, env=env)
        if tag:
            self.git(core, "tag", "-a", tag, "-m", tag, env=env)

    def make_core(self, name="core", v1_tag="v0.1.0", date=OLD_DATE, with_remote=False):
        core = self.tmp / name
        core.mkdir()
        self.git(core, "init", "-q", "-b", "main")
        self.commit_core(core, core_v1(), message="feat: first version", tag=v1_tag, date=date)
        if with_remote:
            remote = self.tmp / f"{name}-remote.git"
            self.git(self.tmp, "init", "-q", "--bare", str(remote))
            self.git(core, "remote", "add", "origin", str(remote))
            self.git(core, "push", "-q", "origin", "main", "--tags")
            self.core_remote = remote
        return core

    def add_v2(self, core, tag="v0.2.0", date=OLD_DATE):
        files, remove = core_v2_changes()
        self.commit_core(core, files, remove, message="feat: second version", tag=tag, date=date)

    # -- consumers --------------------------------------------------------------------

    def make_cli(self, name):
        """A fake PR client that appends its argv (tab separated) to <name>.log and keeps the body."""
        script = self.bin_dir / name
        log = self.bin_dir / f"{name}.log"
        script.write_text(
            "#!/bin/sh\n"
            f'log="{log}"\n'
            'printf "%s\\t" "$@" >> "$log"\n'
            'printf "\\n" >> "$log"\n'
            'prev=""\n'
            'for a in "$@"; do\n'
            f'  if [ "$prev" = "--body-file" ]; then cp "$a" "{log}.body"; fi\n'
            '  prev="$a"\n'
            "done\n"
            'if [ -n "${FAKE_FAIL:-}" ]; then echo "fake failure" >&2; exit 1; fi\n'
            'echo "https://example.com/acme/app/pull/1"\n'
        )
        script.chmod(0o755)
        return script

    def cli_calls(self, name):
        log = self.bin_dir / f"{name}.log"
        if not log.exists():
            return []
        return [line.rstrip("\t").split("\t") for line in log.read_text().splitlines()]

    def profile_text(self, app_dir="src", pr_cli="gh", **overrides):
        values = {
            "harness_source": SOURCE_URL,
            "repo_name": "app",
            "app_dir": app_dir,
            "instructions_file": "CLAUDE.md",
            "extension_dir": "docs/harness",
            "default_branch": "main",
            "language_code": "en",
            "language_ui": "en",
            "vcs_host": "github",
            "vcs_repo": "acme/app",
            "pr_cli": pr_cli,
            "ticket_system": "github",
            "commands_run_on": "host",
            "cmd_test_backend": "make test",
            "cmd_format_backend": "make format",
            "backend_test_framework": "pest",
        }
        values.update(overrides)
        lists = {"branch_prefixes": ["feat", "fix"], "ephemeral_patterns": ["'*-pr.md'"]}
        variables = load_tool().parse_schema_text(SCHEMA.read_text())["variables"]
        for key, spec in variables.items():
            if spec.get("required") is True and key not in values and key not in lists:
                if spec.get("type") == "list":
                    lists[key] = ["item"]
                elif spec.get("type") == "enum":
                    values[key] = spec["values"][0]
                else:
                    values[key] = "placeholder"
        lines = ["# profile of the fake consumer"]
        for key, value in values.items():
            lines.append(f"{key}: {value}")
        for key, items in lists.items():
            lines.append(f"{key}:")
            lines += [f"  - {item}" for item in items]
        return "\n".join(lines) + "\n"

    def make_consumer(self, name="consumer", app_dir="src", pr_cli="gh", gitignore_claude=False, **overrides):
        repo = self.tmp / name
        repo.mkdir()
        self.git(repo, "init", "-q", "-b", "main")
        harness_dir = repo / ".claude" / "harness"
        harness_dir.mkdir(parents=True)
        (harness_dir / "profile.yaml").write_text(self.profile_text(app_dir, pr_cli, **overrides))
        (repo / "CLAUDE.md").write_text("# Project\n\nOwn instructions.\n")
        remote = self.tmp / f"{name}-remote.git"
        self.git(self.tmp, "init", "-q", "--bare", str(remote))
        self.git(repo, "remote", "add", "origin", str(remote))
        self.git(repo, "add", "-f", ".")
        if gitignore_claude:
            (repo / ".gitignore").write_text(".claude/\n")
            self.git(repo, "add", ".gitignore")
        self.git(repo, "commit", "-q", "-m", "chore: start")
        self.git(repo, "push", "-q", "-u", "origin", "main")
        return repo

    def sync(self, repo, core, tag, *extra, check=True):
        return self.harness("sync", tag, "--from", str(core), "--repo", str(repo), *extra, check=check)

    def commit_all(self, repo, message="chore: commit"):
        self.git(repo, "add", "-A", "-f", ".")
        self.git(repo, "commit", "-q", "-m", message)

    def status(self, repo):
        return self.git(repo, "status", "--porcelain").stdout.strip()

    def read_lock(self, repo):
        return json.loads((Path(repo) / ".claude" / "harness.lock").read_text())

    def verify(self, repo, *extra, shell=None):
        shell = shell or shutil.which("dash") or "sh"
        return run([shell, VERIFY, "--repo", repo, *extra], env=self.env, check=False)


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def is_executable(path):
    return bool(Path(path).stat().st_mode & stat.S_IXUSR)
