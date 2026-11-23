"""The card pattern in the text of the core: the contract reference, the skills that write a card at
each moment, the house block, the changelog and the readme. Each test reads a sentence (as
`test_kickoff_profile.sentences` splits them) and requires every pattern of a rule in one of them."""

import json
import re
import subprocess
import unittest

from helpers import REPO_ROOT
from test_kickoff_profile import sentences

SKILLS = REPO_ROOT / "skills"
CONTRACT = SKILLS / "cdv-notion-ticket" / "references" / "card-contract.md"


def read(path):
    return path.read_text(encoding="utf-8")


def skill(name):
    return read(SKILLS / name / "SKILL.md")


def section(text, title):
    """The text of a markdown section from its heading to the next heading of the same level or above."""
    match = re.search(rf"^(#+) {re.escape(title)}\s*$", text, re.M)
    if not match:
        raise AssertionError(f"no section {title!r}")
    level = len(match.group(1))
    rest = text[match.end():]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


class SentenceCase(unittest.TestCase):
    def assertSentence(self, text, *patterns, where=""):
        regexes = [re.compile(p, re.I) for p in patterns]
        found = [s for s in sentences(text) if all(r.search(s) for r in regexes)]
        self.assertTrue(found, f"no sentence of {where or 'the text'} holds all of {patterns}")
        return found

    def assertNoSentence(self, text, *patterns, where=""):
        regexes = [re.compile(p, re.I) for p in patterns]
        found = [s for s in sentences(text) if all(r.search(s) for r in regexes)]
        self.assertFalse(found, f"{where or 'the text'} still says {found}")


class ContractTextTest(SentenceCase):
    def test_contract_reference_states_each_kind(self):
        text = read(CONTRACT)
        kinds = section(text, "The three kinds of card")
        for row in ("| Task card |", "| Form ticket |", "| Project page |"):
            self.assertIn(row, kinds)
        task = section(text, "Task card")
        positions = [task.index(z) for z in ("`## Pedido`", "`## Entrega`", "`## Fechamento`")]
        self.assertEqual(positions, sorted(positions))
        labels = ["`**Objetivo:**`", "`**Pronto quando:**`", "`**Fora desta entrega:**`", "`**Onde:**`",
                  "`**Plano:**`", "`**PRs:**`"]
        positions = [task.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertSentence(task, r"`## Pedido`", r"never rewritten")
        form = section(text, "Form ticket")
        self.assertSentence(form, r"form's sections stay as the form wrote them")
        self.assertSentence(form, r"`## Fechamento`", r"1\s+to 3", r"`PR: #<n>`")
        project = section(text, "Project page")
        headings = ["`### 🎯 Objetivo`", "`### ✅ O que será feito`", "`### 🚫 O que NÃO será feito`",
                    "`### 🔗 Dependências`", "`### 🔎 Decisões`", "`### 🧾 Mudanças de escopo`"]
        positions = [project.index(h) for h in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertSentence(project, r"request toggle", r"as it arrived", r"no skill writes")
        self.assertSentence(project, r"Mudanças de escopo", r"bold `dd/mm` date")
        self.assertIn("## The five moments of a task", text)

    def test_contract_states_the_three_limits(self):
        limits = section(read(CONTRACT), "Limits")
        self.assertSentence(limits, r"`\*\*Pronto quando:\*\*`|Pronto quando", r"1 to 5 list items")
        self.assertSentence(limits, r"`## Fechamento`", r"1 to 3 list items")
        self.assertSentence(limits, r"summary property", r"at most 200 characters on one line")
        data = json.loads(read(SKILLS / "cdv-notion-ticket" / "scripts" / "card-contract.json"))
        self.assertEqual(data["limits"], {"done_when": [1, 5], "closing": [1, 3], "summary_characters": 200})

    def test_contract_states_the_five_moments(self):
        table = section(read(CONTRACT), "The five moments of a task")
        rows = {}
        for line in table.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 3 and cells[0] not in ("Moment", "---"):
                rows[cells[0]] = cells
        expected = [
            ("Request arrives", r"properties only", r"^not started$"),
            ("Plan approved, or work starts on a track with no plan", r"`## Entrega`.*plan page", r"^in progress$"),
            ("Pull request open", r"`\*\*PRs:\*\*`.*pull request property.*summary", r"^pull request open$"),
            ("Merged or deployed", r"`## Fechamento`", r"^merged or deployed$"),
            ("Validated by who asked", r".", r"^done$"),
        ]
        self.assertEqual(list(rows), [moment for moment, _, _ in expected])
        for moment, writes, role in expected:
            with self.subTest(moment=moment):
                self.assertRegex(rows[moment][1], writes)
                self.assertRegex(rows[moment][2], role)

    def test_cdv_notion_keeps_workspace_ids_out_and_points_to_the_contract(self):
        text = skill("cdv-notion")
        self.assertSentence(text, r"ids and keys of a real workspace", r"never in this core",
                            r"card-contract\.md", where="cdv-notion/SKILL.md")
        self.assertNoSentence(text, r"property names of a real workspace", where="cdv-notion/SKILL.md")


if __name__ == "__main__":
    unittest.main()
