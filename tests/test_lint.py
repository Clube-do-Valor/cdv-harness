import unittest

from helpers import HarnessTestCase


def skill(name="cdv-ok", description="Does one thing.", extra="", version="0.1.0", owner="acme-team", metadata=True):
    meta = f"metadata:\n  version: {version}\n  owner: {owner}\n" if metadata else ""
    return f"---\nname: {name}\ndescription: {description}\n{meta}{extra}---\n\n# Body\n"


class LintTest(HarnessTestCase):
    def setUp(self):
        super().setUp()
        self.core = self.tmp / "lintcore"
        (self.core / "skills").mkdir(parents=True)

    def add(self, directory, text):
        (self.core / "skills" / directory).mkdir(parents=True, exist_ok=True)
        (self.core / "skills" / directory / "SKILL.md").write_text(text)

    def lint(self):
        return self.harness("lint", "--core", str(self.core))

    def assert_fails(self, needle):
        result = self.lint()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(needle, result.stdout)
        self.assertRegex(result.stdout, r"skills/[^:]+(/SKILL\.md)?:\d+: ")
        return result

    def test_a_valid_skill_passes(self):
        self.add("cdv-ok", skill())
        result = self.lint()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("lint: 1 skill(s) OK", result.stdout)

    def test_block_and_quoted_scalars_pass(self):
        folded = "---\nname: cdv-ok\ndescription: >-\n  Line one: with a colon\n  and a second # line.\nmetadata:\n  version: 0.1.0\n  owner: \"acme: team\"\n---\n"
        self.add("cdv-ok", folded)
        literal = "---\nname: cdv-two\ndescription: |\n  Literal: text\nmetadata:\n  version: '0.1.0'\n  owner: acme\n---\n"
        self.add("cdv-two", literal)
        result = self.lint()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_name_different_from_directory(self):
        self.add("cdv-dir", skill(name="cdv-other"))
        self.assert_fails("name 'cdv-other' does not match the directory 'cdv-dir'")

    def test_bad_name_pattern(self):
        self.add("Bad_Name", skill(name="Bad_Name"))
        self.assert_fails("must match ^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_name_longer_than_64(self):
        name = "a" * 65
        self.add(name, skill(name=name))
        self.assert_fails("name is longer than 64 characters (65)")

    def test_name_of_64_is_fine(self):
        name = "a" * 64
        self.add(name, skill(name=name))
        self.assertEqual(self.lint().returncode, 0)

    def test_description_longer_than_1024_after_folding(self):
        long = "word " * 206
        text = f"---\nname: cdv-ok\ndescription: >\n  {long.strip()}\nmetadata:\n  version: 1\n  owner: a\n---\n"
        self.add("cdv-ok", text)
        self.assert_fails("description is longer than 1024 characters (1029)")

    def test_description_of_exactly_1024_is_fine(self):
        text = f"---\nname: cdv-ok\ndescription: >\n  {'x' * 1024}\nmetadata:\n  version: 1\n  owner: a\n---\n"
        self.add("cdv-ok", text)
        self.assertEqual(self.lint().returncode, 0)

    def test_missing_description(self):
        self.add("cdv-ok", "---\nname: cdv-ok\nmetadata:\n  version: 1\n  owner: a\n---\n")
        self.assert_fails("missing description")

    def test_missing_metadata_version_and_owner(self):
        self.add("cdv-ok", skill(metadata=False))
        result = self.assert_fails("missing metadata.version")
        self.assertIn("missing metadata.owner", result.stdout)

    def test_missing_only_owner(self):
        self.add("cdv-ok", "---\nname: cdv-ok\ndescription: x\nmetadata:\n  version: 1\n---\n")
        result = self.assert_fails("missing metadata.owner")
        self.assertNotIn("missing metadata.version", result.stdout)

    def test_tab_character(self):
        self.add("cdv-ok", skill(extra="other:\tvalue\n"))
        result = self.assert_fails("tab character in frontmatter")
        self.assertIn("SKILL.md:7:", result.stdout)

    def test_unquoted_colon_space_in_description(self):
        self.add("cdv-ok", skill(description="Use when: the user asks"))
        self.assert_fails("plain scalar contains ': '")

    def test_unquoted_space_hash_in_description(self):
        self.add("cdv-ok", skill(description="Use for the #1 task"))
        self.assert_fails("plain scalar contains ' #'")

    def test_plain_scalar_starting_with_an_indicator_character(self):
        for first in "`!&*{}[]%@,?:":
            with self.subTest(first=first):
                self.add("cdv-ok", skill(description=f"{first}starts badly"))
                result = self.lint()
                self.assertEqual(result.returncode, 1, first)
                self.assertIn(f"plain scalar starts with '{first}'", result.stdout)

    def test_malformed_quotes_and_block_headers_are_errors(self):
        for description, needle in [
            ("'unterminated", "unterminated"),
            ('"done" trailing', "unexpected text after the closing quote"),
            ("|bad header", "invalid block scalar header"),
        ]:
            with self.subTest(description=description):
                self.add("cdv-ok", skill(description=description))
                self.assert_fails(needle)

    def test_backtick_start_is_reported_with_its_line(self):
        self.add("cdv-ok", skill(description="`code` first"))
        result = self.assert_fails("plain scalar starts with '`'")
        self.assertIn("SKILL.md:3:", result.stdout)

    def test_duplicate_keys(self):
        self.add("cdv-ok", skill(extra="name: again\n"))
        self.assert_fails("duplicate key 'name'")

    def test_missing_frontmatter_and_unclosed_frontmatter(self):
        self.add("cdv-ok", "# no frontmatter\n")
        self.assert_fails("missing frontmatter")
        self.add("cdv-ok", "---\nname: cdv-ok\n")
        self.assert_fails("not closed")

    def test_directory_without_skill_md(self):
        (self.core / "skills" / "cdv-empty").mkdir()
        self.assert_fails("missing SKILL.md")

    def test_a_plain_description_continued_on_the_next_line_is_checked_too(self):
        self.add("cdv-ok", skill(description="fine so far\n  but then: trouble"))
        self.assert_fails("plain scalar contains ': '")

    def test_every_error_is_reported_not_only_the_first(self):
        self.add("cdv-a", skill(name="cdv-b", description="bad: one"))
        self.add("cdv-c", skill(metadata=False, name="cdv-c"))
        result = self.lint()
        self.assertEqual(result.returncode, 1)
        self.assertGreaterEqual(len(result.stdout.strip().splitlines()), 4)


if __name__ == "__main__":
    unittest.main()
