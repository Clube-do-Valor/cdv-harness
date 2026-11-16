"""The four optional steps of a kickoff run are written down as recipes (S8)."""

import re
import unittest

from helpers import REPO_ROOT
from test_kickoff_profile import sentences

OPTIONAL = REPO_ROOT / "skills" / "cdv-kickoff" / "references" / "optional"
STEPS = ["slack-draft", "mock-before-after", "blind-judges", "validation-page"]
SECTIONS = ["Signal", "When it runs", "Recipe", "Output", "Stop"]


class OptionalStepsTest(unittest.TestCase):
    def text(self, step):
        return (OPTIONAL / f"{step}.md").read_text(encoding="utf-8")

    def assertSentence(self, step, *patterns):
        regexes = [re.compile(p, re.I) for p in patterns]
        found = [s for s in sentences(self.text(step)) if all(r.search(s) for r in regexes)]
        self.assertTrue(found, f"no sentence of optional/{step}.md holds all of {patterns}")
        return found

    def test_each_optional_step_has_the_five_sections(self):
        for step in STEPS:
            with self.subTest(step=step):
                self.assertTrue((OPTIONAL / f"{step}.md").is_file())
                headings = re.findall(r"^#{2,3} (.+?)\s*$", self.text(step), re.M)
                for section in SECTIONS:
                    self.assertIn(section, headings)
                self.assertEqual([h for h in headings if h in SECTIONS], SECTIONS)

    def test_slack_draft_reads_first_saves_a_draft_never_sends(self):
        self.assertSentence(
            "slack-draft", r"\bfirst\b", r"read the (whole )?thread", r"three messages the developer wrote to that person"
        )
        self.assertSentence("slack-draft", r"save (it as )?a draft")
        for sentence in sentences(self.text("slack-draft")):
            if re.search(r"\bsend(s|ing)?\b|\bpost(s|ing)?\b", sentence, re.I):
                with self.subTest(sentence=sentence):
                    self.assertRegex(sentence, re.compile(r"\bnever\b|\bnot\b|\bno\b|n't\b", re.I))

    def test_blind_judges_run_in_sequence_on_judge_blind_and_cleared(self):
        self.assertSentence("blind-judges", r"two judges", r"one after the other", r"role `judge`")
        self.assertSentence("blind-judges", r"without the other('s| judge's) output")
        self.assertSentence("blind-judges", r"clear the screen's data", r"between (the two judges|them)")

    def test_mock_before_after_one_switching_page_before_the_plan(self):
        self.assertSentence("mock-before-after", r"one page", r"switch(es)? between today and the proposal")
        self.assertSentence("mock-before-after", r"application's own tokens", r"real labels")
        self.assertSentence("mock-before-after", r"show (it|the page) (to the developer )?before the plan")

    def test_validation_page_given_when_then_no_estimates_names_checked(self):
        self.assertSentence("validation-page", r"each rule", r"Given, When, Then", r"realistic mock beside it")
        self.assertSentence("validation-page", r"leave (every )?estimates? out")
        self.assertSentence("validation-page", r"check (every )?invented names? against the local data", r"before publishing")


if __name__ == "__main__":
    unittest.main()
