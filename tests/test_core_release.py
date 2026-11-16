"""The core at HEAD, synced into a fixture consumer: what travels with the checkout."""

import json
import re
import subprocess
import unittest
import urllib.parse
from pathlib import Path

from helpers import REPO_ROOT, HarnessTestCase, load_tool, skill_text

# Built by concatenation so that this file does not itself name the removed skills.
REMOVED = ["cdv-" + "plan-feature", "cdv-" + "flows", "cdv-" + "interactive-qa"]
REFERENCES = [
    "naming-language.md",
    "module-opt-in.md",
    "production-safety.md",
    "worktree-safe-commands.md",
    "qa-fixtures.md",
]
# The one relative link no core change can resolve: a selftest fixture of the third-party
# tlc-spec-lean embeds an image that its selftest.py writes at run time, and third-party skills are
# copied verbatim from upstream, never edited here. Any other broken link fails.
THIRD_PARTY_UNRESOLVED = {".claude/skills/tlc-spec-lean/scripts/fixtures/plan.md -> captures/billing--card-form.png"}
LINK_RE = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
PROFILE_KEY_RE = re.compile(r"(?<![\w/.-])profile\.([a-z][a-z0-9_]*)(?![a-z0-9_])(<[a-z_]+>)?(?!\.[a-z])")


def core_files():
    """Every file of the core checkout: tracked, or untracked and not ignored."""
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    )
    names = sorted({n for n in proc.stdout.decode().split("\0") if n})
    return [n for n in names if (REPO_ROOT / n).is_file() and not (REPO_ROOT / n).is_symlink()]


def strip_code(text):
    out, fence = [], None
    for line in text.splitlines():
        marker = line.lstrip()[:3]
        if marker in ("```", "~~~"):
            fence = None if fence == marker else (fence or marker)
            out.append("")
            continue
        out.append("" if fence else re.sub(r"`[^`]*`", "", line))
    return "\n".join(out)


def relative_links(text):
    for target in LINK_RE.findall(strip_code(text)):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith(("#", "/")):
            continue
        if any(c in target for c in "<>{}*"):
            continue  # a placeholder, not a path
        path = urllib.parse.unquote(target.split("#", 1)[0].split("?", 1)[0])
        if path:
            yield target, path


class CoreReleaseTest(HarnessTestCase):
    def snapshot(self, extra=None, skip=()):
        files = {}
        for name in core_files():
            if name in skip:
                continue
            path = REPO_ROOT / name
            files[name] = (path.read_bytes().decode("utf-8", "surrogateescape"), bool(path.stat().st_mode & 0o111))
        files.update(extra or {})
        return files

    def make_release_core(self, previous=None):
        """A core whose tag v9.0.0 holds the files of this checkout; with `previous`, v8.0.0 holds
        those files plus `previous` first."""
        core = self.tmp / "release-core"
        core.mkdir()
        self.git(core, "init", "-q", "-b", "main")
        if previous is not None:
            self.write_snapshot(core, self.snapshot(previous))
            self.git(core, "add", "-A")
            self.git(core, "commit", "-q", "-m", "chore: previous")
            self.git(core, "tag", "-a", "v8.0.0", "-m", "v8.0.0")
            for relative in previous:
                (core / relative).unlink()
        self.write_snapshot(core, self.snapshot())
        self.git(core, "add", "-A")
        self.git(core, "commit", "-q", "-m", "chore: release")
        self.git(core, "tag", "-a", "v9.0.0", "-m", "v9.0.0")
        return core

    def write_snapshot(self, root, files):
        for relative, (content, executable) in files.items():
            path = Path(root) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8", "surrogateescape"))
            path.chmod(0o755 if executable else 0o644)

    def synced(self, previous=None):
        core = self.make_release_core(previous)
        repo = self.make_consumer()
        if previous is not None:
            first = self.sync(repo, core, "v8.0.0")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.commit_all(repo, "chore: sync previous")
        result = self.sync(repo, core, "v9.0.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        return repo

    def test_sync_vendors_tlc_spec_lean_and_locks_it(self):
        repo = self.synced()
        self.assertTrue((repo / ".claude/skills/tlc-spec-lean/SKILL.md").is_file())
        self.assertIn(".claude/skills/tlc-spec-lean", self.read_lock(repo)["paths"])
        entry = json.loads((REPO_ROOT / "third-party.json").read_text())["skills"]["tlc-spec-lean"]
        self.assertNotIn("vendor", entry)

    def test_sync_over_the_previous_tag_removes_the_three_skills(self):
        previous = {f"skills/{name}/SKILL.md": (skill_text(name), False) for name in REMOVED}
        previous[f"skills/{REMOVED[0]}/references/notes.md"] = ("Notes.\n", False)
        core = self.make_release_core(previous)
        repo = self.make_consumer()
        self.sync(repo, core, "v8.0.0")
        self.commit_all(repo, "chore: sync previous")
        for name in REMOVED:
            self.assertTrue((repo / ".claude/skills" / name / "SKILL.md").is_file(), name)
        result = self.sync(repo, core, "v9.0.0")
        self.assertEqual(result.returncode, 0, result.stderr)
        lock = self.read_lock(repo)
        for name in REMOVED:
            with self.subTest(skill=name):
                self.assertFalse((repo / ".claude/skills" / name).exists())
                self.assertNotIn(f".claude/skills/{name}", lock["paths"])
                self.assertFalse(any(p.startswith(f".claude/skills/{name}/") for p in lock["files"]))

    def test_no_core_file_but_the_changelog_names_a_removed_skill(self):
        found = []
        for name in core_files():
            if name == "CHANGELOG.md":
                continue
            text = (REPO_ROOT / name).read_bytes().decode("utf-8", "replace")
            for number, line in enumerate(text.splitlines(), 1):
                for removed in REMOVED:
                    if removed in line:
                        found.append(f"{name}:{number}: {removed}")
            for removed in REMOVED:
                if removed in name:
                    found.append(f"{name}:0: {removed}")
        self.assertEqual(found, [])

    def test_sync_vendors_the_five_references_and_locks_them(self):
        repo = self.synced()
        for name in REFERENCES:
            with self.subTest(reference=name):
                self.assertTrue((repo / ".claude/harness/references" / name).is_file())
        self.assertIn(".claude/harness/references", self.read_lock(repo)["paths"])

    def test_every_relative_link_in_the_synced_consumer_resolves(self):
        repo = self.synced()
        sources = sorted((repo / ".claude/skills").rglob("*.md")) + sorted((repo / ".claude/harness/references").rglob("*.md"))
        self.assertTrue(sources)
        broken = []
        checked = 0
        for source in sources:
            for target, path in relative_links(source.read_text(encoding="utf-8")):
                checked += 1
                if not (source.parent / path).is_file():
                    broken.append(f"{source.relative_to(repo)} -> {target}")
        instructions = (repo / "CLAUDE.md").read_text()
        house = load_tool().extract_house(instructions)
        self.assertIsNotNone(house)
        for target, path in relative_links(house):
            checked += 1
            if not (repo / path).is_file():
                broken.append(f"CLAUDE.md (house block) -> {target}")
        self.assertGreater(checked, 0)
        self.assertEqual([b for b in broken if b not in THIRD_PARTY_UNRESOLVED], [])

    def test_schema_declares_every_cited_profile_key(self):
        schema = load_tool().parse_schema_text((REPO_ROOT / "profile.schema.yaml").read_text())
        variables = schema["variables"]
        families = schema.get("families") or {}
        missing = set()
        cited = 0
        for name in core_files():
            if not (name.startswith(("skills/", "references/")) or name == "instructions/house.md"):
                continue
            text = (REPO_ROOT / name).read_bytes().decode("utf-8", "replace")
            for key, placeholder in PROFILE_KEY_RE.findall(text):
                if key == "yaml":
                    continue
                cited += 1
                if placeholder:
                    if key not in families:
                        missing.add(f"{key}{placeholder} ({name})")
                elif key not in variables:
                    missing.add(f"{key} ({name})")
        self.assertGreater(cited, 50)
        self.assertEqual(sorted(missing), [])

    def test_verify_passes_on_a_consumer_synced_at_head(self):
        repo = self.synced()
        lock = self.read_lock(repo)
        self.assertEqual(lock["schema"], 1)
        self.assertIsInstance(lock["hooks"], list)
        self.assertTrue(lock["hooks"])
        self.assertIn(".claude/harness/hooks", lock["paths"])
        self.assertIn(".claude/harness/references", lock["paths"])
        result = self.verify(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("harness: vendored core matches v9.0.0", result.stdout)

    def test_deny_covers_the_new_vendored_directories(self):
        repo = self.synced()
        deny = json.loads((repo / ".claude/settings.json").read_text())["permissions"]["deny"]
        self.assertIn("Edit(/.claude/harness/hooks/**)", deny)
        self.assertIn("Edit(/.claude/harness/references/**)", deny)


def house_text():
    return (REPO_ROOT / "instructions" / "house.md").read_text()


def skill(name):
    return (REPO_ROOT / "skills" / name / "SKILL.md").read_text()


def one_line(text):
    return " ".join(text.split())


class HouseBlockTest(unittest.TestCase):
    def test_house_block_drops_the_two_asks_and_states_the_five_rules(self):
        text = one_line(house_text())
        for absent in (
            r"ask the programmer whether to search",
            r"whether documentation should be created or updated",
            r"ask (the programmer|the user|them) whether to (search|look)",
        ):
            with self.subTest(absent=absent):
                self.assertNotRegex(text, re.compile(absent, re.I))
        for present in (
            r"search first, always",
            r"every child.{0,40}names? its model.{0,80}role table",
            r"fable only when the user names it",
            r"plan with `tlc-spec-lean`",
            r"start a feature with `cdv-kickoff`",
        ):
            with self.subTest(present=present):
                self.assertRegex(text, re.compile(present, re.I))


class SkillProseTest(unittest.TestCase):
    def test_debug_hands_a_larger_fix_to_kickoff(self):
        text = one_line(skill("cdv-debug"))
        self.assertRegex(text, re.compile(r"larger than small.{0,120}hands? (it )?off to `cdv-kickoff`", re.I))
        self.assertRegex(text, re.compile(r"invoke `cdv-kickoff`", re.I))

    def test_finalize_gate_reads_validate_verification_or_capped(self):
        text = one_line(skill("cdv-finalize"))
        gate = re.search(r"Verifier gate.{0,1200}", text, re.I)
        self.assertIsNotNone(gate)
        gate = gate.group(0)
        self.assertIn(".specs/features/<f>/verification.md", gate)
        self.assertRegex(gate, r"`validate_verification\.py[^`]*`.{0,80}(exits? `?0`?|green)")
        self.assertRegex(gate, re.compile(r"`capped`.{0,200}open items.{0,120}pull request description", re.I))
        self.assertRegex(gate, re.compile(r"otherwise.{0,80}refuse to commit", re.I))

    def test_code_review_offers_apply_on_a_colleagues_branch_and_asks_before_push(self):
        text = one_line(skill("cdv-code-review"))
        self.assertRegex(text, re.compile(r"colleague's branch.{0,300}offer.{0,120}apply(ing)? the findings on that branch", re.I))
        self.assertRegex(text, re.compile(r"ask before pushing", re.I))
        self.assertNotRegex(text, re.compile(r"never\*\* routed to `cdv-apply-review`", re.I))


if __name__ == "__main__":
    unittest.main()
