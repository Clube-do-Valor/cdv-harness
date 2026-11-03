import json
import unittest

from helpers import HarnessTestCase


def tp_skill(name, body="Upstream body.\n"):
    return f"---\nname: {name}\ndescription: An upstream skill.\nlicense: CC-BY-4.0\n---\n\n{body}"


class ThirdPartyTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.core = self.tmp / "tpcore"
        (self.core / "skills").mkdir(parents=True)
        self.upstream = self.tmp / "upstream"
        (self.upstream / "reg").mkdir(parents=True)
        self.env = dict(self.env, HARNESS_THIRD_PARTY_BASE=f"file://{self.upstream}")
        self.write_list({"up-skill": {"owner": "upstream (third party)", "path": "", "contentHash": "", "version": ""}})

    def write_list(self, skills):
        data = {
            "schema": 1,
            "upstream": {"repo": "acme/skills", "ref": "main", "registry": "reg/registry.json", "skills_root": "tree"},
            "skills": skills,
        }
        (self.core / "third-party.json").write_text(json.dumps(data))

    def publish(self, name, files, content_hash, version="1.0.0", path="(cat)/up-skill"):
        for relative, text in files.items():
            target = self.upstream / "tree" / path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        registry = {"skills": [{"name": name, "path": path, "files": sorted(files), "contentHash": content_hash, "version": version}]}
        (self.upstream / "reg" / "registry.json").write_text(json.dumps(registry))

    def tp(self, *extra):
        return self.harness("third-party", "--core", str(self.core), *extra)

    def listed(self):
        return json.loads((self.core / "third-party.json").read_text())["skills"]["up-skill"]

    def test_copies_a_changed_skill_and_records_its_hash(self):
        self.publish("up-skill", {"SKILL.md": tp_skill("up-skill"), "references/a.md": "ref\n"}, "h1")
        result = self.tp()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.core / "skills/up-skill/references/a.md").read_text(), "ref\n")
        self.assertEqual(self.listed()["contentHash"], "h1")
        self.assertEqual(self.listed()["version"], "1.0.0")

    def test_removes_files_the_upstream_dropped(self):
        self.publish("up-skill", {"SKILL.md": tp_skill("up-skill"), "old.md": "x\n"}, "h1")
        self.tp()
        (self.upstream / "tree/(cat)/up-skill/old.md").unlink()
        self.publish("up-skill", {"SKILL.md": tp_skill("up-skill", "New body.\n")}, "h2")
        self.assertEqual(self.tp().returncode, 0)
        self.assertFalse((self.core / "skills/up-skill/old.md").exists())
        self.assertIn("New body.", (self.core / "skills/up-skill/SKILL.md").read_text())

    def test_unchanged_hash_touches_nothing(self):
        self.publish("up-skill", {"SKILL.md": tp_skill("up-skill")}, "h1")
        self.tp()
        before = (self.core / "third-party.json").read_text()
        (self.core / "skills/up-skill/SKILL.md").write_text("local marker\n")
        result = self.tp()
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("up-skill", result.stdout)
        self.assertEqual((self.core / "third-party.json").read_text(), before)
        self.assertEqual((self.core / "skills/up-skill/SKILL.md").read_text(), "local marker\n")

    def test_check_exits_1_when_out_of_date_and_writes_nothing(self):
        self.publish("up-skill", {"SKILL.md": tp_skill("up-skill")}, "h1")
        result = self.tp("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("up-skill", result.stdout)
        self.assertFalse((self.core / "skills/up-skill").exists())
        self.assertEqual(self.listed()["contentHash"], "")

    def test_skill_missing_upstream_is_an_error(self):
        self.publish("other", {"SKILL.md": tp_skill("other")}, "h1")
        result = self.tp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("no longer in the upstream registry", result.stderr)

    def test_unsafe_upstream_path_is_refused(self):
        self.publish("up-skill", {"SKILL.md": tp_skill("up-skill")}, "h1")
        registry = json.loads((self.upstream / "reg/registry.json").read_text())
        registry["skills"][0]["files"].append("../escape.md")
        (self.upstream / "reg/registry.json").write_text(json.dumps(registry))
        result = self.tp()
        self.assertEqual(result.returncode, 1)
        self.assertIn("unsafe path", result.stderr)
        self.assertFalse((self.core / "escape.md").exists())

    def test_lint_and_catalog_take_owner_and_version_from_the_list(self):
        self.publish("up-skill", {"SKILL.md": tp_skill("up-skill")}, "h1", version="2.2.0")
        self.tp()
        lint = self.harness("lint", "--core", str(self.core))
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        catalog = self.harness("catalog", "--core", str(self.core))
        self.assertEqual(catalog.returncode, 0, catalog.stderr)
        self.assertIn("| `up-skill` | 2.2.0 | upstream (third party) |", (self.core / "CATALOG.md").read_text())

    def test_lint_still_requires_metadata_for_house_skills(self):
        (self.core / "skills/cdv-own").mkdir(parents=True)
        (self.core / "skills/cdv-own/SKILL.md").write_text("---\nname: cdv-own\ndescription: Ours.\n---\n")
        lint = self.harness("lint", "--core", str(self.core))
        self.assertEqual(lint.returncode, 1)
        self.assertIn("missing metadata.owner", lint.stdout)


class VendoredSelectionTest(HarnessTestCase):
    def test_every_skill_under_skills_is_vendored(self):
        tool = self.tool if hasattr(self, "tool") else __import__("helpers").load_tool()

        class Tree:
            entries = {
                "skills/cdv-debug/SKILL.md": ("100644", "a"),
                "skills/tlc-spec-lean/SKILL.md": ("100644", "b"),
                "skills/tlc-spec-lean/scripts/run.py": ("100755", "c"),
                "README.md": ("100644", "d"),
            }

        selected = tool.select_vendored(Tree())
        self.assertIn(".claude/skills/tlc-spec-lean/SKILL.md", selected)
        self.assertTrue(selected[".claude/skills/tlc-spec-lean/scripts/run.py"][1])
        self.assertIn(".claude/skills/cdv-debug/SKILL.md", selected)
        self.assertNotIn(".claude/README.md", selected)


class UserOnlyTest(HarnessTestCase):
    def test_vendor_false_skips_the_skill_in_sync(self):
        tool = __import__("helpers").load_tool()

        class Tree:
            entries = {
                "skills/cdv-debug/SKILL.md": ("100644", "a"),
                "skills/tlc-spec-lean/SKILL.md": ("100644", "b"),
                "skills/create-adr/SKILL.md": ("100644", "c"),
                "third-party.json": ("100644", "d"),
            }

            def read(self, path):
                return b'{"skills": {"tlc-spec-lean": {"vendor": false, "user": true}, "create-adr": {"user": true}}}'

        selected = tool.select_vendored(Tree())
        self.assertNotIn(".claude/skills/tlc-spec-lean/SKILL.md", selected)
        self.assertIn(".claude/skills/create-adr/SKILL.md", selected)
        self.assertIn(".claude/skills/cdv-debug/SKILL.md", selected)


if __name__ == "__main__":
    unittest.main()
