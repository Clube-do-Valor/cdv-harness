"""skills/cdv-finalize/scripts/lint-pr-description.sh over a passing description and one failing
description per check. The ticket key is built at runtime so the public scan never sees one."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT

LINT = REPO_ROOT / "skills" / "cdv-finalize" / "scripts" / "lint-pr-description.sh"
KEY = "AB" + "C-12"
NOTION_URL = "https://www.notion.so/Exportar-faturas-0123456789abcdef0123456789abcdef"
FIRST = "A equipe de cobrança baixa as faturas do mês numa planilha pela tela de faturas."
REST = "Antes ela copiava uma por uma. Sem mudanças em processos ou configuração."


def description(tldr=None, decisions=2, passos=3, filler=False, riscos=True, link=True, ticket="default",
                extras_after_ticket=False, pos_deploy=None, padding=24, tldr_first=True):
    tldr_block = ["## ⚡ TL;DR", "", tldr if tldr is not None else f"{FIRST} {REST}", ""]
    what = ["## 🔍 O que muda e por quê", "",
            "A equipe pediu a exportação" + (" (https://example.com/acme/app/issues/7)." if link else "."), ""]
    what += [f"- Comportamento novo número {i}." for i in range(1, padding + 1)] + [""]
    if filler:
        what += ["Sem dependências novas.", ""]
    body = (tldr_block + what) if tldr_first else (what + tldr_block)
    if decisions is not None:
        body += ["## 🎯 Decisões para o reviewer validar", ""] + [f"- Decisão {i}." for i in range(1, decisions + 1)] + [""]
    body += ["## 🧪 Como testar", "", "`make test` → **12 passed (30 assertions)**", ""]
    body += [f"- **Passo {i}:** abrir a tela. *Esperado:* a planilha sai." for i in range(1, passos + 1)] + [""]
    if riscos:
        body += ["## ⚠️ Riscos e impactos", "", "Nenhum risco identificado além do escopo descrito.", ""]
    if pos_deploy is not None:
        body += ["## 🚀 Pós-deploy", "", pos_deploy, ""]
    if ticket == "default":
        ticket = f"[{KEY} — Exportar faturas]({NOTION_URL})"
    if ticket is not None:
        body += ["## 🏷️ Ticket", "", ticket, ""]
    if extras_after_ticket:
        body += ["## 🛠️ Extras (out-of-band)", "", "- Ajuste de configuração do editor.", ""]
    return "\n".join(body)


class LintPrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lint-pr-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        profile = self.tmp / ".claude" / "harness" / "profile.yaml"
        profile.parent.mkdir(parents=True)
        profile.write_text('ticket_system: notion\nticket_key_pattern: "ABC-[0-9]+"\n')

    def lint(self, text, name="slug-pr.md"):
        (self.tmp / name).write_text(text, encoding="utf-8")
        return subprocess.run(["bash", str(LINT), name], cwd=str(self.tmp), capture_output=True, text=True)

    def fails(self, proc):
        return [line[5:] for line in proc.stdout.splitlines() if line.startswith("FAIL")]

    def assertPasses(self, text):
        proc = self.lint(text)
        self.assertEqual((proc.returncode, self.fails(proc)), (0, []), proc.stdout + proc.stderr)
        return proc

    def assertFailsOnly(self, text, *starts):
        proc = self.lint(text)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        failed = self.fails(proc)
        self.assertEqual(len(failed), len(starts), failed)
        for message, start in zip(failed, starts):
            self.assertTrue(message.startswith(start), f"{message!r} does not start with {start!r}")
        return proc

    def test_first_sentence_of_200_passes_and_201_fails(self):
        self.assertPasses(description())
        at_200 = "x" * 199 + "."
        proc = self.assertPasses(description(tldr=f"{at_200} {REST}"))
        self.assertIn("TL;DR first sentence has 200 characters", proc.stdout)
        accented = "ç" * 199 + "."
        self.assertPasses(description(tldr=f"{accented} {REST}"))
        self.assertFailsOnly(description(tldr=f"{'x' * 200}. {REST}"), "TL;DR first sentence has 201 characters")

    def test_a_one_sentence_tldr_without_a_period_is_measured_to_the_end(self):
        self.assertPasses(description(tldr="Uma frase só, sem ponto final, que diz o que mudou para quem pediu"))
        long_words = " ".join(["palavra"] * 25) + " " + "y" * 30
        self.assertGreater(len(long_words), 200)
        self.assertFailsOnly(description(tldr=long_words), "TL;DR first sentence has")
        dotted = "A versão 2.5 do relatório " + " ".join(["mostra"] * 30) + " os números do mês inteiro"
        self.assertGreater(len(dotted), 200)
        self.assertFailsOnly(description(tldr=dotted), f"TL;DR first sentence has {len(dotted)} characters")
        wrapped = "Uma frase que segue\nna linha de baixo sem ponto"
        proc = self.assertPasses(description(tldr=wrapped))
        self.assertIn(f"TL;DR first sentence has {len(' '.join(wrapped.split()))} characters", proc.stdout)

    def test_a_first_sentence_in_bold_or_italics_ends_at_its_own_period(self):
        rest = " Antes " + " ".join(["palavra"] * 22) + " no fim."  # with the first one, more than 200 characters
        at_100 = "x" * 99 + "."
        for text in (f"**{at_100}**", f"*{at_100}*", f"_{at_100}_", f"__{at_100}__", f"***{at_100}***", f"**{at_100}",
                     f"**{'x' * 99}**."):
            with self.subTest(text=text[:4] + text[-4:]):
                proc = self.assertPasses(description(tldr=text + rest))
                self.assertIn("TL;DR first sentence has 100 characters", proc.stdout)
        for marks in ("**", "*", "_"):
            with self.subTest(marks=marks):
                self.assertPasses(description(tldr=f"{marks}{'x' * 199}.{marks} {REST}"))
                self.assertFailsOnly(description(tldr=f"{marks}{'x' * 200}.{marks} {REST}"),
                                     "TL;DR first sentence has 201 characters")
        self.assertIn("TL;DR first sentence has 100 characters",
                      self.assertPasses(description(tldr=f"**{'x' * 100}**")).stdout)
        quoted = self.assertPasses(description(tldr="A tela diz “" + "x" * 60 + ".”" + rest))
        self.assertIn("TL;DR first sentence has 74 characters", quoted.stdout)

    def test_a_ticket_section_without_a_key_fails(self):
        self.assertFailsOnly(description(ticket=f"[Exportar faturas]({NOTION_URL})"),
                             "Ticket section holds no key matching ticket_key_pattern")
        self.assertPasses(description(ticket=None))

    def test_the_key_pattern_is_read_as_the_rest_of_the_core_reads_it(self):
        profile = self.tmp / ".claude" / "harness" / "profile.yaml"
        pattern = "ABC-[0-9]+"
        for value in (pattern, f'"{pattern}"', f"'{pattern}'", f"{pattern}  # the cards", f'"{pattern}"  # the "cards"',
                      f"'{pattern}' # the team's cards", "ABC-[[:digit:]]+", '"ABC-[[:digit:]]{2}"', f"#12|{KEY}"):
            with self.subTest(value=value):
                profile.write_text(f"ticket_system: notion  # the tracker\nticket_key_pattern: {value}\n", encoding="utf-8")
                if not value.startswith("#"):
                    self.assertPasses(description())
                    self.assertFailsOnly(description(ticket=f"[Exportar faturas]({NOTION_URL})"),
                                         "Ticket section holds no key matching ticket_key_pattern")
                else:  # the whole value is a comment: no pattern, so no key check
                    self.assertPasses(description(ticket=f"[Exportar faturas]({NOTION_URL})"))
                self.assertFailsOnly(description(ticket=f"[{KEY} — Exportar faturas](https://example.com/{KEY})"),
                                     "Ticket section without")
        profile.write_text('ticket_system: notion\nticket_key_pattern: "ABC #[0-9]+"  # a mark inside the quotes\n', encoding="utf-8")
        self.assertPasses(description(ticket=f"[ABC #12 — Exportar faturas]({NOTION_URL})"))
        self.assertFailsOnly(description(), "Ticket section holds no key matching ticket_key_pattern (ABC #[0-9]+)")

    def test_each_check_fails_alone(self):
        many_words = FIRST + " " + " ".join(["mais"] * 80) + "."
        cases = {
            "TL;DR first": (description(tldr_first=False), ["first section is"]),
            "TL;DR words": (description(tldr=many_words), ["TL;DR has"]),
            "too few lines": (description(padding=2), [""]),
            "too many lines": (description(padding=80), [""]),
            "Decisões missing": (description(decisions=None), ["missing '## 🎯", "Decisões has 0 bullets"]),
            "Decisões bullets": (description(decisions=5), ["Decisões has 5 bullets"]),
            "Passos": (description(passos=6), ["QA roteiro has 6 passos"]),
            "Riscos": (description(riscos=False), ["missing '## ⚠️ Riscos"]),
            "external link": (description(link=False, ticket=None), ["no external link"]),
            "filler": (description(filler=True), ["file-inventory"]),
            "ticket link": (description(ticket=f"[{KEY} — Exportar faturas](https://example.com/{KEY})"),
                            ["Ticket section without"]),
            "ticket last": (description(extras_after_ticket=True), ["Ticket must be the last section"]),
            "pós-deploy": (description(pos_deploy="`php artisan exportar <opções>`"), ["Pós-deploy contains"]),
            "first sentence": (description(tldr=f"{'z' * 201}. {REST}"), ["TL;DR first sentence has 202"]),
            "ticket key": (description(ticket=f"[Exportar faturas]({NOTION_URL})"), ["Ticket section holds no key"]),
        }
        for name, (text, starts) in cases.items():
            with self.subTest(check=name):
                proc = self.assertFailsOnly(text, *starts)
                if name.endswith("lines"):
                    self.assertRegex(self.fails(proc)[0], r"^\d+ lines \(target 40-80")
        missing = subprocess.run(["bash", str(LINT)], cwd=str(self.tmp), capture_output=True, text=True)
        self.assertEqual(missing.returncode, 2)
        absent = subprocess.run(["bash", str(LINT), "nope.md"], cwd=str(self.tmp), capture_output=True, text=True)
        self.assertEqual(absent.returncode, 2)


if __name__ == "__main__":
    unittest.main()
