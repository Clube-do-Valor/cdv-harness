"""The card contract checker (skills/cdv-notion-ticket/scripts/card_contract.py) against synthetic cards.

The checker and the cdv-notion client are loaded as modules; the client's transport is a fake Notion
(card_fixtures.CardNotion) and HOME is a temporary directory, so nothing reaches Notion."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import card_fixtures as cf
from card_fixtures import ANA, BRUNO, ME, NOBODY_KNOWN, TOKEN, uid
from helpers import REPO_ROOT
from test_notion import child_page

REFERENCE = REPO_ROOT / "skills" / "cdv-notion-ticket" / "references" / "card-contract.md"

# Door 1 of the plan, as the plan writes it (blank lines are not part of the contract).
DOOR_1 = {
    "task": """## Pedido
<the request as it arrived, in the words of who asked; never rewritten>

## Entrega
**Objetivo:** <one sentence>
**Pronto quando:**
- <1 to 5 criteria someone can observe>
**Fora desta entrega:** <what does not enter, and where it goes>
**Onde:** <repository>, <repository>
**Plano:** <mention of the child page>
**PRs:** <repository> #<n> · <repository> #<n>

## Fechamento
- <what changed for who asked>
- Fora do código: <what was done or is pending outside the code>
""",
    "form-closing": """## Fechamento
- <what changed for who asked>
- Fora do código: <what was done or is pending outside the code>
PR: #<n>
""",
    "project": """### 🎯 Objetivo
<one paragraph, present tense>
### ✅ O que será feito
- <...>
### 🚫 O que NÃO será feito
- <...>
### 🔗 Dependências
- <...>
### 🔎 Decisões
<pointer to the decisions and, per slice, to the task that holds its plan>
### 🧾 Mudanças de escopo
- **<dd/mm>** · Entrou: <...>. Saiu: <...>. <who decided, or where it came from>. CES de <x> para <y>.
""",
}
DOOR_1["task-small"] = "\n".join(l for l in DOOR_1["task"].splitlines() if not l.startswith("**Plano:**")) + "\n"

REQUEST = "## Pedido\n\nA equipe de cobrança quer baixar as faturas do mês numa planilha.\n\n"


def entrega(items=3, objective="Exportar as faturas do mês numa planilha.", prs="billing-api #12"):
    lines = ["## Entrega", "", f"**Objetivo:** {objective}", "", "**Pronto quando:**", ""]
    lines += [f"- Critério observável {i}." for i in range(1, items + 1)]
    lines += ["", "**Fora desta entrega:** notas fiscais.", "", "**Onde:** billing-api", ""]
    if prs is not None:
        lines += [f"**PRs:** {prs}", ""]
    return "\n".join(lines) + "\n"


def fechamento(items=2):
    lines = ["## Fechamento", ""] + [f"- Mudou a coisa {i} para quem pediu." for i in range(1, items + 1)]
    return "\n".join(lines) + "\n"


def full_task(items=3, closing=2, prs="billing-api #12"):
    return REQUEST + entrega(items, prs=prs) + "\n" + (fechamento(closing) if closing else "")


def nonblank(text):
    return [line for line in text.splitlines() if line.strip()]


PR_URL = "https://example.com/acme/billing-api/pull/12"
SUMMARY = "A equipe de cobrança baixa as faturas do mês numa planilha."


class CardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="card-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "NOTION_API_TOKEN": TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.n = cf.real_client()
        self.fake = cf.CardNotion()
        self.n.TRANSPORT = self.fake
        self.n.SLEEP = lambda seconds: None
        self.cc = cf.load_checker(self.n)
        self.settings({"me": ME, "card": {"since": cf.SINCE}})

    def settings(self, value):
        path = self.home / ".config" / "cdv-notion" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")

    def add(self, built):
        page, body = built
        self.fake.add(page, body)
        return page["id"]

    def check(self, ref, *flags):
        return cf.run_main(self.cc, ["check", ref, *flags])

    def rules(self, ref, *flags):
        code, out, err = self.check(ref, "--json", *flags)
        self.assertIn(code, (0, 1), err)
        found = json.loads(out)
        self.assertEqual(code, 1 if found else 0)
        return [f["rule"] for f in found]

    def assertClean(self, ref, *flags):
        code, out, err = self.check(ref, *flags)
        self.assertEqual((code, out), (0, ""), err)

    def set_body(self, page_id, body):
        self.fake.markdown[page_id] = body


class SkeletonTest(CardCase):
    def test_skeleton_prints_each_kind_as_door_1(self):
        reference = REFERENCE.read_text(encoding="utf-8")
        for kind, block in DOOR_1.items():
            with self.subTest(kind=kind):
                code, out, err = cf.run_main(self.cc, ["skeleton", kind])
                self.assertEqual(code, 0, err)
                self.assertEqual(nonblank(out), nonblank(block))
                self.assertIn(out.strip(), reference)
        code, out, _ = cf.run_main(self.cc, ["skeleton", "task"])
        self.assertTrue(out.startswith("## Pedido"))
        self.assertTrue(nonblank(out)[-1].startswith("- Fora do código:"))
        self.assertNotIn("**Plano:**", cf.run_main(self.cc, ["skeleton", "task-small"])[1])

    def test_the_checker_runs_by_its_path_with_no_interpreter_in_front(self):
        ran = subprocess.run([str(cf.CHECKER), "skeleton", "task-small"], cwd=str(self.tmp), capture_output=True,
                             text=True, timeout=60)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(nonblank(ran.stdout), nonblank(DOOR_1["task-small"]))
        listed = subprocess.run(["git", "ls-files", "-s", "skills"], cwd=str(REPO_ROOT), capture_output=True, text=True,
                                check=True).stdout.splitlines()
        seen = []
        for mode, _sha, _stage, name in (line.split(maxsplit=3) for line in listed):
            # a script with an interpreter line is called by its path; tlc-spec-lean's are called through python3
            if "/scripts/" not in name or name.startswith("skills/tlc-spec-lean/"):
                continue
            if (REPO_ROOT / name).read_bytes().startswith(b"#!"):
                seen.append(name)
                self.assertEqual(mode, "100755", f"{name} is committed as {mode}")
        self.assertIn("skills/cdv-notion-ticket/scripts/card_contract.py", seen)
        for text in REPO_ROOT.glob("skills/cdv-*/**/*.md"):
            for match in re.finditer(r"(python3 )?\S*tlc-spec-lean/scripts/\w+\.py", text.read_text(encoding="utf-8")):
                self.assertTrue(match.group(1), f"{text.name} names {match.group(0)} with no python3 in front")

    def test_skeleton_of_an_unknown_kind_exits_2_naming_the_four(self):
        code, out, err = cf.run_main(self.cc, ["skeleton", "unknown"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        for kind in ("task", "task-small", "form-closing", "project"):
            self.assertIn(kind, err)

    def test_each_skeleton_filled_with_its_examples_has_no_finding(self):
        skeletons = cf.contract()["skeletons"]
        status = {"merged": "Rollout", "done": "Done"}
        for number, kind in enumerate(("task", "task-small"), start=1):
            with self.subTest(kind=kind):
                entry = skeletons[kind]
                props = entry["example_properties"]
                page = self.add(cf.task(number, entry["example"], status=status[entry["moment"]],
                                        pr=props["pull_request"], summary=props["summary"]))
                self.assertClean(page)
        with self.subTest(kind="form-closing"):
            entry = skeletons["form-closing"]
            props = entry["example_properties"]
            body = "## Prazo\n\nAté sexta.\n\n## Impacto\n\nAlto.\n\n" + entry["example"]
            page = self.add(cf.task(3, body, status=status[entry["moment"]], email="cliente@example.com",
                                    pr=props["pull_request"], summary=props["summary"]))
            self.assertClean(page)
        with self.subTest(kind="project"):
            page = self.add(cf.project(4, cf.project_body(current=skeletons["project"]["example"])))
            self.assertClean(page)


class NamesMapTest(CardCase):
    def test_names_map_holds_the_door_4_defaults(self):
        names = self.cc.names({})
        self.assertEqual(names["tasks"]["source"], "Tasks")
        self.assertEqual(names["tasks"]["properties"], {
            "status": "Status", "summary": "Resumo", "requester": "Requester", "assignee": "Assignee",
            "pull_request": "Pull Request", "tags": "Tags", "type": "Type", "sprint": "Sprint",
            "project": "Project", "email": "Email"})
        self.assertEqual(names["tasks"]["tag"], "Helpdesk")
        self.assertEqual(names["tasks"]["types"], {"task": "Tarefa", "bug": "Bug"})
        self.assertEqual(names["status"], {
            "not_started": "Not started", "in_progress": "In progress", "pull_request_open": "Code Review",
            "merged": "Rollout", "deployed": "Rollout", "done": "Done", "archived": "Archived"})
        self.assertEqual(names["sprints"], {"source": "Sprints", "status_property": "Sprint status", "current": "Current"})
        self.assertEqual(names["projects"]["source"], "Projects")
        self.assertEqual(names["projects"]["toggles"], {
            "request": "Descrição do Projeto", "current": "Discovery & Define",
            "checklist": "Checklist de Desenvolvimento"})
        self.assertEqual(names["projects"]["properties"], {"executors": "Executores", "score": "Pontuação Total Projeto"})
        self.assertGreater(names["since"], "2900-01-01")

    def test_card_setting_replaces_a_default_and_bad_settings_exit_2(self):
        review = self.add(cf.task(1, full_task(), status="Code Review", summary=SUMMARY))
        renamed = self.add(cf.task(2, full_task(), status="Em revisão", summary=SUMMARY))
        self.assertIn("pr-property", self.rules(review))
        self.assertEqual(self.rules(renamed), [])
        self.settings({"me": ME, "card": {"since": cf.SINCE, "status": {"pull_request_open": "Em revisão"}}})
        self.assertIn("pr-property", self.rules(renamed))
        self.assertEqual(self.rules(review), [])
        self.settings({"card": {"status": {"reviewing": "Em revisão"}}})
        code, out, err = self.check(review)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("card.status.reviewing", err)
        self.settings("{not json")
        code, out, err = self.check(review)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(str(self.home / ".config" / "cdv-notion" / "config.json"), err)


class ClassifyTest(CardCase):
    def test_a_page_outside_tasks_and_projects_is_not_a_card(self):
        task_page = self.add(cf.task(1, full_task()))
        plan = child_page(uid(0x6001), "Plano técnico: exportar faturas", task_page)
        self.fake.add(plan, "Status: Done\n\n## Entrega\n")
        wiki = cf.row(1, cf.DS_WIKI)
        self.fake.add(wiki, "Status: Done\n")
        sprint = cf.row(2, cf.DS_SPRINTS)
        self.fake.add(sprint, "Status: Done\n")
        for ref in (plan["id"], wiki["id"], sprint["id"], cf.DS_TASKS):
            with self.subTest(ref=ref):
                self.assertClean(ref)

    def test_a_card_created_before_since_is_exempt_unless_its_body_was_replaced(self):
        before = self.add(cf.task(1, "", created="2026-10-31T23:59:00.000Z"))
        on_the_day = self.add(cf.task(2, "", created="2026-11-01T00:00:00.000Z"))
        self.assertClean(before)
        self.assertEqual(self.check(before, "--body-replaced")[0], 1)
        self.assertEqual(self.check(on_the_day)[0], 1)
        self.settings({"me": ME})
        for ref in (before, on_the_day):
            self.assertClean(ref)

    def test_a_card_of_someone_else_is_exempt_unless_its_body_was_replaced(self):
        other = self.add(cf.task(1, "", assignee=(BRUNO,)))
        nobody = self.add(cf.task(2, "", assignee=()))
        both = self.add(cf.task(3, "", assignee=(BRUNO, ANA)))
        unknown = self.add(cf.task(4, "", assignee=(NOBODY_KNOWN,)))
        self.assertClean(other)
        self.assertEqual(self.check(other, "--body-replaced")[0], 1)
        for ref in (nobody, both, unknown):
            with self.subTest(ref=ref):
                self.assertEqual(self.check(ref)[0], 1)
        their_project = self.add(cf.project(5, cf.project_body(request=None), executors=(BRUNO,)))
        self.assertClean(their_project)
        self.settings({"card": {"since": cf.SINCE}})  # no `me`, and git gives no e-mail
        self.assertEqual(self.check(other)[0], 1)


class TaskRulesTest(CardCase):
    def test_not_started_archived_or_unmapped_status_owes_no_zone(self):
        for number, status in enumerate(("Not started", "Archived", "On Hold/Blocked"), start=1):
            with self.subTest(status=status):
                page = self.add(cf.task(number, "", status=status, assignee=(), requester=(), type_=None))
                self.assertClean(page)
                self.set_body(page, "Status: Done\n")
                self.assertEqual(self.rules(page), ["status-in-body"])
        page = self.add(cf.task(9, "## Pedido\n\nPrimeiro texto.\n", status="Not started"))
        self.assertClean(page)
        self.set_body(page, "## Pedido\n\nOutro texto.\n")
        self.assertEqual(self.rules(page), ["request-changed"])

    def test_an_in_progress_task_owes_request_delivery_objective_done_when_and_people(self):
        empty = self.add(cf.task(1, "Um texto solto.\n", assignee=(), requester=(), type_=None))
        self.assertEqual(sorted(self.rules(empty)),
                         sorted(["request-zone", "delivery-zone", "objective", "done-when", "people", "people", "type"]))
        complete = self.add(cf.task(2, full_task()))
        self.assertEqual(self.rules(complete), [])
        above = self.add(cf.task(3, entrega() + "\n" + REQUEST))
        self.assertEqual(self.rules(above), ["delivery-zone"])
        headed = self.add(cf.task(4, "## Pedido\n\n## Contexto\n\nTexto.\n\n## Critério de pronto\n\nOutro.\n\n" + entrega()))
        self.assertEqual(self.rules(headed), [])
        bare = self.add(cf.task(5, REQUEST + entrega(objective="")))
        self.assertEqual(self.rules(bare), ["objective"])

    def test_done_when_holds_1_to_5_items(self):
        for number, (items, expected) in enumerate(((0, ["done-when"]), (1, []), (5, []), (6, ["done-when"])), start=1):
            with self.subTest(items=items):
                page = self.add(cf.task(number, REQUEST + entrega(items)))
                self.assertEqual(self.rules(page), expected)

    def test_the_pr_line_and_the_pr_property_agree(self):
        body_only = self.add(cf.task(1, full_task(prs="ledger-api #12"), status="Code Review", summary=SUMMARY))
        self.assertIn("pr-link", self.rules(body_only))
        property_only = self.add(cf.task(2, full_task(prs=None), status="Rollout", pr=PR_URL, summary=SUMMARY))
        self.assertEqual(self.rules(property_only), ["pr-link"])
        no_code = self.add(cf.task(3, full_task(prs=None, closing=0), status="Done", summary=SUMMARY))
        self.assertEqual(self.rules(no_code), [])
        form = self.add(cf.task(4, "## Prazo\n\nSexta.\n\n" + fechamento(), status="Done", email="c@example.com",
                                pr=PR_URL, summary=SUMMARY))
        self.assertEqual(self.rules(form), ["pr-link"])
        self.set_body(form, "## Prazo\n\nSexta.\n\n" + fechamento() + "\nPR: #12\n")
        self.assertEqual(self.rules(form), [])

    def test_pr_open_owes_the_property_and_a_summary_of_at_most_200_characters(self):
        empty = self.add(cf.task(1, full_task(), status="Code Review", summary=SUMMARY))
        self.assertIn("pr-property", self.rules(empty))
        cases = {"x" * 200: [], "x" * 201: ["summary"], "uma linha\noutra linha": ["summary"], "": ["summary"]}
        for number, (summary, expected) in enumerate(cases.items(), start=2):
            with self.subTest(length=len(summary)):
                page = self.add(cf.task(number, full_task(), status="Code Review", pr=PR_URL, summary=summary or None))
                self.assertEqual(self.rules(page), expected)

    def test_merged_deployed_or_done_owes_the_summary_and_a_closing_of_1_to_3_items(self):
        done = self.add(cf.task(1, full_task(prs=None, closing=0), status="Done", summary=SUMMARY))
        self.assertEqual(self.rules(done), [])
        merged = self.add(cf.task(2, full_task(closing=0), status="Rollout", pr=PR_URL, summary=SUMMARY))
        self.assertEqual(self.rules(merged), ["closing"])
        for number, (items, expected) in enumerate(((1, []), (3, []), (4, ["closing"])), start=3):
            with self.subTest(items=items):
                page = self.add(cf.task(number, full_task(closing=items), status="Rollout", pr=PR_URL, summary=SUMMARY))
                self.assertEqual(self.rules(page), expected)
        no_summary = self.add(cf.task(9, full_task(), status="Done", pr=PR_URL))
        self.assertEqual(self.rules(no_summary), ["summary"])
        long_summary = self.add(cf.task(10, full_task(), status="Rollout", pr=PR_URL, summary="y" * 201))
        self.assertEqual(self.rules(long_summary), ["summary"])

    def test_a_form_ticket_owes_no_request_zone_and_closes_with_the_pr_line(self):
        form_body = "## Resultado Obtido Vs Esperado\n\nA tela mostra um erro.\n\n## Prazo\n\nSexta.\n"
        working = self.add(cf.task(1, form_body, email="c@example.com"))
        self.assertEqual(self.rules(working), [])
        review = self.add(cf.task(2, form_body, status="Code Review", email="c@example.com", pr=PR_URL))
        self.assertEqual(sorted(self.rules(review)), ["pr-link", "summary"])
        closed = self.add(cf.task(3, form_body + "\n" + fechamento(2) + "\nPR: [#12](" + PR_URL + ")\n", status="Done",
                                  email="c@example.com", pr=PR_URL, summary=SUMMARY))
        self.assertEqual(self.rules(closed), [])
        no_closing = self.add(cf.task(4, form_body + "\nPR: #12\n", status="Done", email="c@example.com", pr=PR_URL,
                                      summary=SUMMARY))
        self.assertEqual(self.rules(no_closing), ["closing"])
        with_request = self.add(cf.task(5, REQUEST, email="c@example.com"))
        self.assertEqual(sorted(self.rules(with_request)), ["delivery-zone", "done-when", "objective"])

    def test_a_status_written_in_the_body_is_a_finding(self):
        under_entrega = REQUEST + entrega().replace("**Onde:**", "**Status:** em rollout\n\n**Onde:**") + "\n" + fechamento()
        under_closing = full_task() + "\nStatus: Done\n"
        for number, (body, line) in enumerate(((under_entrega, "**Status:** em rollout"), (under_closing, "Status: Done")),
                                              start=1):
            with self.subTest(line=line):
                page = self.add(cf.task(number, body))
                code, out, _ = self.check(page)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("status-in-body: "), out)
                self.assertIn(line.replace("**", ""), out)
        prose = self.add(cf.task(5, REQUEST.replace("planilha.", "planilha; o status do pedido aparece na tela.") + entrega()))
        self.assertEqual(self.rules(prose), [])

    def test_a_status_line_in_the_request_zone_is_the_words_of_who_asked(self):
        said = "Status: o sistema caiu de novo hoje."
        request = self.add(cf.task(1, "## Pedido\n\n" + said + "\n\n" + entrega()))
        self.assertEqual(self.rules(request), [])
        form_body = "## Resultado Obtido Vs Esperado\n\n" + said + "\n\n## Prazo\n\nSexta.\n"
        form = self.add(cf.task(2, form_body, email="c@example.com"))
        self.assertEqual(self.rules(form), [])
        closed = self.add(cf.task(3, form_body + "\n" + fechamento(2) + "\nPR: #12\nStatus: Done\n", status="Done",
                                  email="c@example.com", pr=PR_URL, summary=SUMMARY))
        self.assertEqual(self.rules(closed), ["status-in-body"])
        toggle = self.add(cf.project(4, cf.project_body(current=CURRENT, request="Pedido de quem pediu.\n" + said)))
        self.assertEqual(self.rules(toggle), [])
        current = self.add(cf.project(5, cf.project_body(current=CURRENT.replace("Na pesquisa.", "Status: Done"))))
        self.assertEqual(self.rules(current), ["status-in-body"])


SCOPE_OK = "- **12/11** · Entrou: a tela de regras. Decidido com quem pediu. CES de 7 para 9.\n"
CURRENT = ("### 🎯 Objetivo\n\nA equipe acompanha as faturas numa tela.\n\n### ✅ O que será feito\n\n- A tela.\n\n"
           "### 🚫 O que NÃO será feito\n\n- A cobrança por e-mail.\n\n### 🔗 Dependências\n\n- O acesso.\n\n"
           "### 🔎 Decisões\n\nNa pesquisa.\n\n### 🧾 Mudanças de escopo\n\n" + SCOPE_OK)


class ProjectRulesTest(CardCase):
    def test_a_project_page_owes_its_toggles_headings_order_and_dated_scope_lines(self):
        cases = [
            (cf.project_body(current=CURRENT), []),
            (cf.project_body(current=CURRENT, request=None), ["project-toggle"]),
            (cf.project_body(current=None), ["project-toggle"]),
            (cf.project_body(current=""), []),
            (cf.project_body(current="### 🔗 Dependências\n\n- O acesso.\n"), ["project-headings"] * 3),
            (cf.project_body(current=CURRENT.replace("### 🔎 Decisões\n\nNa pesquisa.\n\n", "")
                             + "\n### 🔎 Decisões\n\nNa pesquisa.\n"), ["project-order"]),
            (cf.project_body(current=CURRENT + "- 12/11 entrou a tela\n"), ["scope-log"]),
        ]
        for number, (body, expected) in enumerate(cases, start=1):
            with self.subTest(case=number):
                page = self.add(cf.project(number, body))
                self.assertEqual(self.rules(page), expected)


class RequestPinTest(CardCase):
    def pins(self):
        folder = self.home / ".cache" / "cdv-notion" / "card-pins"
        return sorted(folder.glob("*.json")) if folder.is_dir() else []

    def test_the_first_check_pins_a_digest_of_the_request_zone_not_its_text(self):
        request = "## Pedido\n\nO time de Zanzibar quer   a planilha\nde faturas.\n\n"
        page = self.add(cf.task(1, request + entrega()))
        self.assertClean(page)
        pins = self.pins()
        self.assertEqual(len(pins), 1)
        expected = hashlib.sha256("O time de Zanzibar quer a planilha de faturas.".encode()).hexdigest()
        self.assertEqual(json.loads(pins[0].read_text())["digest"], expected)
        project = self.add(cf.project(2, cf.project_body(current=CURRENT, request="Zanzibar pede uma tela.")))
        self.assertClean(project)
        self.assertEqual(len(self.pins()), 2)
        digests = {json.loads(p.read_text())["digest"] for p in self.pins()}
        self.assertIn(hashlib.sha256("Zanzibar pede uma tela.".encode()).hexdigest(), digests)
        for path in (self.home / ".cache" / "cdv-notion").rglob("*"):
            if path.is_file():
                self.assertNotIn("Zanzibar", path.read_text(encoding="utf-8", errors="replace"), path)

    def test_a_changed_request_zone_is_reported_until_accepted(self):
        page = self.add(cf.task(1, REQUEST + entrega()))
        self.assertClean(page)
        self.set_body(page, REQUEST + "\n\n" + entrega())
        self.assertClean(page)
        self.set_body(page, REQUEST.replace("planilha", "tabela") + entrega())
        code, out, _ = self.check(page)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("request-changed: "), out)
        self.assertIn("accept-request", out)
        code, out, err = cf.run_main(self.cc, ["accept-request", page])
        self.assertEqual(code, 0, err)
        self.assertClean(page)
        shutil.rmtree(self.home / ".cache" / "cdv-notion")
        self.set_body(page, REQUEST + entrega())
        self.assertClean(page)
        self.assertEqual(len(self.pins()), 1)

    def build(self, kind, number, request):
        """A clean card of this kind whose request is `request`; (page id, function that builds its body)."""
        if kind == "task":
            def body(text):
                return f"## Pedido\n\n{text}\n\n" + entrega()
            return self.add(cf.task(number, body(request))), body

        def body(text):
            return cf.project_body(current=CURRENT, request=text)
        return self.add(cf.project(number, body(request))), body

    def assertRequest(self, pairs, expected):
        """Each (name, text as pinned, text as read later) gives the rules `expected`, on both kinds."""
        for name, before, after in pairs:
            for kind in ("task", "project"):
                with self.subTest(kind=kind, change=name):
                    page, body = self.build(kind, 100 + len(self.fake.pages), before)  # a page of its own
                    self.assertClean(page)
                    self.set_body(page, body(after))
                    self.assertEqual(self.rules(page), expected)

    def test_a_change_inside_a_code_fence_of_the_request_is_reported(self):
        log = "O erro:\n\n```\nfalha no boleto 10\n```\n\nObrigado."
        nested = "````\n```\n## Entrega\n```\nfalha no boleto 10\n````"
        self.assertRequest([
            ("one word", log, log.replace("boleto 10", "boleto 99")),
            ("with a language", log.replace("```\nf", "```text\nf"), log.replace("```\nf", "```text\nf").replace("10", "99")),
            ("a tilde fence", log.replace("```", "~~~"), log.replace("```", "~~~").replace("10", "99")),
            ("inside a list item", "- O erro:\n\n  ```\n  boleto 10\n  ```", "- O erro:\n\n  ```\n  boleto 99\n  ```"),
            ("stars are text in a fence", "```\nselect **\n```", "```\nselect\n```"),
            ("a tag is text in a fence", "```\n<b>x</b>\n```", "```\nx\n```"),
            ("a longer fence around a shorter one", nested, nested.replace("boleto 10", "boleto 99")),
            ("after a line that only starts like the closing mark", "```\na\n```js\n**10**\n```", "```\na\n```js\n10\n```"),
        ], ["request-changed"])
        self.assertRequest([
            ("after a line with the marks inline", "```x``` é o nome.\n\n**fim**", "```x``` é o nome.\n\n<b>fim</b>"),
            ("whitespace", log, log.replace("falha no", "falha   no")),
            ("the language alone", log, log.replace("```\nf", "```text\nf")),
            ("the fence's own marks", log, log.replace("```", "~~~~")),
            ("the same", nested, nested),
        ], [])
        for number, kind in enumerate(("task", "project"), start=1):
            with self.subTest(fetched=kind):
                page, body = self.build(kind, number, nested)
                code, out, err = cf.run_main(self.n, ["fetch", page])
                self.assertEqual(code, 0, err)
                self.assertTrue(self.cc.pin_from_fetch_output(out))
                self.assertClean(page)
                self.set_body(page, body(nested.replace("boleto 10", "boleto 99")))
                self.assertEqual(self.rules(page), ["request-changed"])

    def test_a_repointed_link_mention_or_date_in_the_request_is_reported(self):
        one, two = "a" * 32, "b" * 32
        repointed = {
            "a mention of a page": '<mention url="https://app.notion.com/p/{}">Plano</mention>',
            "a mention of a person": 'Com <mention url="user://{}">Ana Lima</mention>, hoje.',
            "a mention with no text": '<mention url="https://app.notion.com/p/{}" />',
            "single quotes": "<mention url='user://{}'>Ana</mention>",
            "a mention inside bold": '**veja <mention url="user://{}">Ana</mention>**',
            "a markdown link": "[o plano](https://app.notion.com/p/{})",
            "a markdown link with a title": '[o plano](https://app.notion.com/p/{} "Plano")',
            "a link tag": '<a href="https://example.com/{}">o plano</a>',
            "underscores in a link": "[x](https://example.com/__{}__/y)",
            "a bare address": "https://example.com/{}",
            "the query of a link": "[x](https://example.com/y?id={})",
            "the query of a bookmark": '<bookmark source="https://example.com/y?id={}" />',
            "a child page": '<page url="https://app.notion.com/p/{}">Anexo</page>',
            "a database": '<database url="https://app.notion.com/p/{}">Base</database>',
            "an embed": '<embed source="https://example.com/{}" />',
            "a file": '<file source="https://example.com/{}.txt">nota</file>',
            "a block not loaded": '<unknown url="https://app.notion.com/p/{}" alt="x" />',
        }
        pairs = [(name, text.format(one), text.format(two)) for name, text in repointed.items()]
        day = '<date start="2026-11-22" />'
        pairs += [
            ("the day of a date", "Até " + day, "Até " + day.replace("11-22", "12-30")),
            ("the end of a date", '<date start="2026-11-22" end="2026-11-23" />', '<date start="2026-11-22" end="2026-11-24" />'),
            ("the hour of a date", '<date start="2026-11-22" start-time="09:00" />', '<date start="2026-11-22" start-time="18:00" />'),
            ("a mention taken out", f'<mention url="user://{one}">Ana</mention> pediu', "Ana pediu"),
            ("a link taken out", f"[Ana](https://example.com/{one}) pediu", "Ana pediu"),
            ("a word that only looks like a tag", "envie para <cliente> hoje", "envie para <fornecedor> hoje"),
            ("words behind the name of a tag", "envie <file do cliente> hoje", "envie <file do fornecedor> hoje"),
            ("a tag as text in inline code", "use `<b>` aqui", "use `<i>` aqui"),
            ("an escaped tag", "use \\<b> aqui", "use \\<i> aqui"),
            ("stars in inline code", "`**x**`", "`x`"),
            ("stars typed by hand", "\\*x\\*", "x"),
            ("marks that only close", "5* x* y", "5 x y"),
            ("marks that only open", "*a *b", "a b"),
            ("a mark alone", "*a b", "a b"),
            ("underscores in a bare address", "https://example.com/_a_/y", "https://example.com/a/y"),
            ("a caption in an attribute", '<img src="https://example.com/x.png" alt="boleto" />', '<img src="https://example.com/x.png" alt="extrato" />'),
            ("a cell of a table", "<table>\n<tr><td>10</td><td>0</td></tr>\n</table>", "<table>\n<tr><td>1</td><td>00</td></tr>\n</table>"),
            ("a caption", "![tela do boleto](https://example.com/x.png)", "![tela do extrato](https://example.com/x.png)"),
        ]
        self.assertRequest(pairs, ["request-changed"])
        self.assertRequest([
            ("bold", "o **pedido** chegou", "o pedido chegou"),
            ("bold as a tag", "o pedido chegou", "o <b>pedido</b> chegou"),
            ("bold around a space", "**Nota: **urgente", "<b>Nota: </b>urgente"),
            ("italics", "o *pedido* e o _prazo_", "o <i>pedido</i> e o <em>prazo</em>"),
            ("bold italics", "***pedido***", "pedido"),
            ("strikethrough", "o ~~pedido~~", "o <s>pedido</s>"),
            ("underline", "o <u>pedido</u>", "o pedido"),
            ("colour", 'o <span color="red">pedido</span>', 'o <span color="blue_bg">pedido</span>'),
            ("colour alone", 'o <span color="red">pedido</span>', "o pedido"),
            ("the colour of a callout", '<callout icon="⚡" color="red">\nAviso\n</callout>', '<callout color="blue_bg">\nAviso\n</callout>'),
            ("inline code as a tag", "a `SELECT * FROM x_y` b", "a <code>SELECT \\* FROM x\\_y</code> b"),
            ("bold around a link", f"**[x](https://example.com/{one})**", f"<b>[x](https://example.com/{one})</b>"),
            ("bold around an address", "**https://example.com/x**", "https://example.com/x"),
            ("bold in the words of a mention", f'<mention url="user://{one}">**Ana**</mention>', f'<mention url="user://{one}">Ana</mention>'),
            ("an entity in an address", "[x](https://example.com/y?a=1&b=2)", "[x](https://example.com/y?a=1&amp;b=2)"),
            ("an entity in a tag", '<a href="https://example.com/y?a=1&b=2">x</a>', '<a href="https://example.com/y?a=1&amp;b=2">x</a>'),
            ("an underscore escaped in a link", "[x](https://example.com/a_b)", "[x](https://example.com/a\\_b)"),
            ("the order of a tag's attributes", '<date start="2026-11-22" end="2026-11-23" />', '<date end="2026-11-23" start="2026-11-22"/>'),
            ("two bold words", "**a** e **b**", "<b>a</b> e b"),
            ("bold with italics inside", "**a *b* c**", "a b c"),
            ("a mark with no pair", "**a** 5* b", "a 5\\* b"),
            ("stars that are text", "2 * 3 e snake__case", "2 \\* 3 e snake\\_\\_case"),
        ], [])
        page = self.add(cf.task(9, "## Pedido\n\nO pedido.\n\n" + entrega().replace("**Objetivo:**", '<a href="https://x">**Objetivo:**</a>')))
        self.assertClean(page)  # labels are compared as plain text, every tag dropped
        # A long pasted line of loose marks is read in one pass (about 0.1 s; a search per mark takes minutes)
        started = time.monotonic()
        for mark in ("_a ", "*a ", "**a ", "~~a ", "__a "):
            self.cc.digest(mark * 40000)
        self.assertLess(time.monotonic() - started, 60)

    def test_a_renamed_mention_in_the_request_is_the_same_request(self):
        one, two = "a" * 32, "b" * 32
        page = f'<mention url="https://app.notion.com/p/{one}">Plano</mention>'
        person = f'<mention url="user://{one}">Ana Lima</mention>'
        self.assertRequest([
            ("a page renamed", f"Veja {page} hoje", f"Veja {page} hoje".replace("Plano", "Plano de faturas")),
            ("a person renamed", f"Com {person}, hoje", f"Com {person}, hoje".replace("Ana Lima", "Ana Costa")),
            ("no name shown", page, page.replace("Plano", "")),
            ("a mention that closes itself", page, f'<mention url="https://app.notion.com/p/{one}" />'),
            ("single quotes", page.replace('"', "'"), page.replace("Plano", "Outro")),
            ("two on one line", f"{page} e {person}", f"{page} e {person}".replace("Plano", "Outro").replace("Ana", "Bia")),
            ("inside bold", f"**veja {page}**", f"<b>veja {page}</b>".replace("Plano", "Outro")),
            ("in a list item", f"- {page}: ver", f"- {page}: ver".replace("Plano", "Outro")),
            ("in a table cell", f"<tr><td>{page}</td></tr>", f"<tr><td>{page}</td></tr>".replace("Plano", "Outro")),
            ("a name with a bracket", page, page.replace("Plano", "Plano [1")),
            ("a name with a backquote", f"{page} e `x`", f"{page} e `x`".replace("Plano", "O ` Plano")),
            ("a name with a star and one after", f"{page} 5 * 3 *fim", f"{page} 5 * 3 *fim".replace("Plano", "*Plano")),
            ("a name with an escaped tag", page, page.replace("Plano", "Plano \\</mention> \\<mention>")),
            ("a name with a tag", page, page.replace("Plano", "<b>Plano</b><br />novo")),
        ], [])
        self.assertRequest([
            ("a page, another target", page, page.replace(one, two)),
            ("a person, another target", person, person.replace(one, two)),
            ("another target and the same name", f"{page} e {person}", f"{page} e {person}".replace(f"user://{one}", f"user://{two}")),
            ("the words around it", f"Veja {page} hoje", f"Veja {page} amanhã"),
            ("the words between two", f"{page} e {person}", f"{page} ou {person}"),
            ("the words after one that closes itself", f'<mention url="user://{one}" /> pediu {page}',
             f'<mention url="user://{one}" /> cancelou {page}'),
            ("the words after one with no end", f'<mention url="user://{one}"> pediu {page}',
             f'<mention url="user://{one}"> cancelou {page}'),
            ("the target after one with no end", f'<mention url="user://{one}"> pediu {page}',
             f'<mention url="user://{one}"> pediu {page}'.replace(f"/p/{one}", f"/p/{two}")),
            ("the words up to a loose end", f'<mention url="user://{one}" /> pediu</mention> hoje',
             f'<mention url="user://{one}" /> cancelou</mention> hoje'),
            ("the words of a link up to a loose end", f'<a href="https://example.com/{one}">plano</a></mention>',
             f'<a href="https://example.com/{one}">texto</a></mention>'),
            ("a mention with no target","<mention>Ana</mention>", "<mention>Bia</mention>"),
            ("a mention with an empty target", '<mention url="">Ana</mention>', '<mention url="">Bia</mention>'),
            ("a mention as text in inline code", f"`{page}`", f"`{page}`".replace("Plano", "Outro")),
            ("a mention as text in a fence", f"```\n{page}\n```", f"```\n{page}\n```".replace("Plano", "Outro")),
            ("the words of a markdown link", f"[o plano](https://app.notion.com/p/{one})", f"[o texto](https://app.notion.com/p/{one})"),
            ("the words of a link tag", f'<a href="https://example.com/{one}">plano</a>', f'<a href="https://example.com/{one}">texto</a>'),
            ("the hour of a date", '<date start="2026-11-22" start-time="09:00" />', '<date start="2026-11-22" start-time="18:00" />'),
        ], ["request-changed"])
        # A long line of mentions that never close is read in one pass
        started = time.monotonic()
        self.cc.digest(f'<mention url="user://{one}">a ' * 20000)
        self.assertLess(time.monotonic() - started, 60)

    def test_a_picture_or_file_read_again_with_another_signature_is_the_same_request(self):
        signed = "https://files.example.com/space/tela.png?X-Sig=111&X-Date=1"
        again = "https://files.example.com/space/tela.png?X-Sig=222&amp;X-Date=2"
        held = {
            "a picture": "![tela do boleto]({})",
            "a picture with no caption": "![]({})",
            "a picture with a title": '![tela]({} "Tela")',
            "a picture in a list": "- veja ![tela]({}) aqui",
            "brackets in the caption": "![tela \\[1\\] do [boleto]]({})",
            "a picture inside a link": "[![tela]({})](https://example.com/y?id=1)",
            "a picture tag": '<image source="{}">tela</image>',
            "an img tag": '<img src="{}" alt="tela" />',
            "a file": '<file source="{}">tela.png</file>',
            "a pdf": '<pdf source="{}">tela</pdf>',
            "an audio": '<audio source="{}">tela</audio>',
            "a video": '<video source="{}">tela</video>',
        }
        self.assertRequest([(name, text.format(signed), text.format(again)) for name, text in held.items()], [])
        self.assertRequest([(name + ", another address", text.format(signed), text.format(signed.replace("tela.png", "nota.png")))
                            for name, text in held.items()], ["request-changed"])
        self.assertRequest([
            ("the caption", f"![tela do boleto]({signed})", f"![tela do extrato]({signed})"),
            ("the caption of a file", f'<file source="{signed}">boleto</file>', f'<file source="{signed}">extrato</file>'),
            ("the link around a picture", f"[![tela]({signed})](https://example.com/y?id=1)", f"[![tela]({signed})](https://example.com/y?id=2)"),
            ("a link after a picture", f"![tela]({signed}) [x](https://example.com/y?id=1)", f"![tela]({signed}) [x](https://example.com/y?id=2)"),
            ("a link after a loose mark", "ok![ e [x](https://example.com/y?id=1)", "ok![ e [x](https://example.com/y?id=2)"),
            ("the page of a pdf", f'<pdf source="{signed}#page=2">x</pdf>', f'<pdf source="{signed}#page=3">x</pdf>'),
            ("a video on a player's page", '<video source="https://video.example.com/watch?v=1">x</video>',
             '<video source="https://video.example.com/watch?v=2">x</video>'),
            ("a picture taken out", f"antes ![tela]({signed})", "antes"),
        ], ["request-changed"])


class ReadingTimeTest(CardCase):
    """The time a reading takes follows the length of the text, not the shape of one line. Each input is
    long enough that a pattern which retries cannot end inside the limit, and is read in a small part of it."""

    def test_runs_of_backquotes_in_the_request(self):
        for line, words in (
            ("a `*x*` b", "a *x* b"), ("a ``x ` *y*`` b", "a x ` *y* b"), ("`*a*` e `*b*`", "*a* e *b*"),
            ("\\``*a*` b", "`*a* b"), ("`a\\` *b*", "a\\ b"),  # a run after an escaped one; no escape inside the code
            ("``*a*` b", "``a` b"), ("`*a*`` b", "`a`` b"), ("``` `*a*` ``", "``` *a* ``"),  # a run nothing closes is text
        ):
            with self.subTest(line=line):
                self.assertEqual(self.cc.request_words(line), words)
        with cf.cpu_limit():
            self.cc.digest("a" + "`" * 100000)
            self.cc.digest(" ".join("`" * length for length in range(1, 1501)))

    def test_spaces_and_marks_inside_a_heading(self):
        for line, read in (("## x ##", (2, "x")), ("  ## Entrega  ", (2, "Entrega")), ("# a # #", (1, "a #")), ("### a#", (3, "a")),
                           ("## ##", (2, "")), ("# a  b", (1, "a  b")), ("##", None), ("##x", None), ("####### x", None)):
            with self.subTest(line=line):
                self.assertEqual(self.cc.heading(line), read)
        with cf.cpu_limit():
            for run in (" " * 100000, "#" * 100000, " #" * 50000):
                self.assertEqual(self.cc.heading(f"# a{run}x")[0], 1)

    def test_open_tags_in_the_title_of_a_toggle(self):
        for title, read in (("## <b>O pedido</b>", "O pedido"), ('<span color="red">x</span> < y', "x < y"), ("a <b", "a <b"), ("<> a", "<> a")):
            with self.subTest(title=title):
                self.assertEqual(self.cc.toggles(["<toggle>", title, "\tx", "</toggle>"]), [(read, ["\tx"])])
        with cf.cpu_limit():
            self.cc.toggles(["<toggle>", "a" + "<" * 200000, "</toggle>"])

    def test_spaces_in_the_parent_line_of_a_fetch_output(self):
        output = f"id: {uid(0xE1)}\nparent: data source Tasks%s({cf.DS_TASKS})\nbody:\n## Pedido\n\nO pedido.\n\n## Entrega\n"
        with cf.cpu_limit():
            self.assertTrue(self.cc.pin_from_fetch_output(output % (" " * 200000)))
            self.assertFalse(self.cc.pin_from_fetch_output(output.replace(uid(0xE1), uid(0xE2)) % (" " * 200000 + "x ")))


class FailureTest(CardCase):
    def test_no_token_exits_3_and_an_unreadable_page_exits_4_with_the_client_message(self):
        page = self.add(cf.task(1, ""))
        with mock.patch.dict(os.environ, {"NOTION_API_TOKEN": ""}):
            for verb in ("check", "accept-request"):
                code, out, err = cf.run_main(self.cc, [verb, page])
                self.assertEqual((code, out), (3, ""), verb)
                self.assertIn("notion auth login", err)
        code, out, err = self.check(uid(0x6999))
        self.assertEqual((code, out), (4, ""))
        self.assertIn("404", err)
        self.fake.on("GET", f"/v1/pages/{page}", lambda r: (403, {"object": "error", "status": 403,
                                                               "code": "restricted_resource", "message": "no"}))
        code, out, err = self.check(page)
        self.assertEqual((code, out), (4, ""))
        self.assertIn("403", err)

        def unreachable(*args, **kwargs):
            raise ConnectionError("network is down")

        self.n.TRANSPORT = unreachable
        code, out, err = self.check(page)
        self.assertEqual((code, out), (4, ""))
        self.assertIn("could not reach", err)


class CutBodyTest(CardCase):
    """A page whose body the client could not read whole (the read is marked `truncated`)."""

    LINE = re.compile(r"\A[^\n]*body[^\n]*too long to read whole[^\n]*\n\Z")

    def cut(self, built):
        page = self.add(built)
        self.fake.cut.append(page)
        return page

    def pins(self):
        folder = self.home / ".cache" / "cdv-notion" / "card-pins"
        return sorted(folder.glob("*.json")) if folder.is_dir() else []

    def test_a_cut_body_has_its_properties_judged_and_nothing_of_its_body(self):
        nobody = {"assignee": (), "requester": (), "type_": None}
        people = ["people", "people", "type"]
        status = "**Status:** em andamento\n"
        cases = [
            ("an empty body", cf.task(1, ""), ["request-zone", "delivery-zone", "objective", "done-when"], []),
            ("labels and people", cf.task(2, REQUEST + "## Entrega\n", **nobody), ["objective", "done-when"] + people, people),
            ("too many criteria", cf.task(3, REQUEST + entrega(items=6)), ["done-when"], []),
            ("a status in the body", cf.task(4, REQUEST + entrega() + status), ["status-in-body"], []),
            ("a status in the body, not started", cf.task(5, status, status="Not started"), ["status-in-body"], []),
            ("a pull request only in the body", cf.task(6, REQUEST + entrega(), status="Code Review", summary=SUMMARY),
             ["pr-link", "pr-property"], ["pr-property"]),
            ("a pull request only in the property", cf.task(7, REQUEST + entrega(prs=None), status="Code Review", pr=PR_URL,
                                                            summary=SUMMARY), ["pr-link"], []),
            ("pull request open with nothing filled", cf.task(8, full_task(closing=0, prs=None), status="Code Review", **nobody),
             people + ["pr-property", "summary"], people + ["pr-property", "summary"]),
            ("a long summary and no closing", cf.task(9, full_task(closing=0), status="Rollout", pr=PR_URL, summary="z" * 201),
             ["summary", "closing"], ["summary"]),
            ("too many closing items", cf.task(10, full_task(closing=4), status="Done", pr=PR_URL, summary=SUMMARY), ["closing"], []),
            ("a form ticket", cf.task(11, "## Prazo\n\nSexta.\n", status="Done", email="c@example.com", pr=PR_URL),
             ["pr-link", "summary", "closing"], ["summary"]),
            ("a project with no toggle", cf.project(1, "Texto.\n"), ["project-toggle", "project-toggle"], []),
            ("a project with no heading", cf.project(2, cf.project_body(current="Texto.\n\n### 🧾 Mudanças de escopo\n12/11 entrou")),
             ["project-headings"] * 3 + ["scope-log"], []),
        ]
        for name, built, whole, expected in cases:
            with self.subTest(case=name):
                page = self.add(built)
                self.assertEqual(sorted(self.rules(page)), sorted(whole))
                self.assertEqual(self.check(page)[2], "")  # a body read whole says nothing
                self.fake.cut.append(page)
                self.assertEqual(self.rules(page), expected)
                code, out, err = self.check(page)
                self.assertEqual((code, len(out.splitlines())), (1 if expected else 0, len(expected)))
                self.assertRegex(err, self.LINE)
                self.assertEqual(self.rules(page, "--body-replaced"), expected)

    def test_a_cut_body_pins_no_request_and_compares_none(self):
        for number, (kind, body) in enumerate((("task", REQUEST + entrega()), ("project", cf.project_body(current=CURRENT))), 1):
            with self.subTest(kind=kind):
                page = self.add(getattr(cf, kind)(number, body))
                before = len(self.pins())
                self.fake.cut.append(page)
                code, out, err = self.check(page)
                self.assertEqual((code, out), (0, ""))
                self.assertRegex(err, self.LINE)
                self.assertEqual(len(self.pins()), before)
                code, out, err = cf.run_main(self.cc, ["accept-request", page])
                self.assertEqual(code, 0, err)
                self.assertIn("nothing was pinned", out)
                self.assertRegex(err, self.LINE)
                self.assertEqual(len(self.pins()), before)
                self.fake.cut.remove(page)
                self.assertClean(page)
                self.assertEqual(len(self.pins()), before + 1)
                pinned = [path.read_text() for path in self.pins()]
                changed = body.replace("planilha", "tabela").replace("O pedido como chegou", "Outro pedido")
                self.set_body(page, changed)
                self.fake.cut.append(page)
                code, out, err = self.check(page)
                self.assertEqual((code, out), (0, ""))
                self.assertRegex(err, self.LINE)
                cf.run_main(self.cc, ["accept-request", page])
                self.assertEqual([path.read_text() for path in self.pins()], pinned)
                self.fake.cut.remove(page)
                self.assertEqual(self.rules(page), ["request-changed"])

        early = self.cut(cf.task(9, "Cortado antes do pedido.\n"))
        code, out, err = cf.run_main(self.cc, ["accept-request", early])
        self.assertEqual((code, out), (0, f"{early} was not read whole; nothing was pinned\n"))
        self.assertRegex(err, self.LINE)

    def test_a_cut_body_of_a_page_that_is_not_judged_says_nothing(self):
        for name, built in (("not a card", cf.row(1, cf.DS_WIKI)), ("older than the pattern", cf.task(1, "", created="2026-10-31T10:00:00.000Z")),
                            ("someone else's", cf.task(2, "", assignee=(BRUNO,)))):
            with self.subTest(page=name):
                page = self.cut(built if isinstance(built, tuple) else (built, ""))
                self.assertEqual(self.check(page), (0, "", ""))


FINDING = re.compile(r"^[a-z][a-z-]+: [^\n]+\. [^\n]+$")


class OutputTest(CardCase):
    def everything_wrong(self):
        body = "Status: em andamento\n\n" + entrega(items=7) + "\n" + REQUEST + fechamento(5)
        return self.add(cf.task(1, body, status="Rollout", assignee=(), requester=(), type_=None, pr=PR_URL,
                                summary="z" * 230))

    def test_findings_are_one_line_each_in_at_most_2000_characters(self):
        page = self.everything_wrong()
        code, out, _ = self.check(page)
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertGreaterEqual(len(lines), 6)
        for line in lines:
            self.assertRegex(line, FINDING)
        self.assertLessEqual(len(out), 2000)
        self.assertIn("Status: em andamento", out)
        long_scope = "".join(f"- 1{i % 10}/11 entrou uma parte grande do escopo que ninguém datou direito\n"
                             for i in range(80))
        project = self.add(cf.project(2, cf.project_body(current=CURRENT + long_scope)))
        code, out, _ = self.check(project)
        self.assertEqual(code, 1)
        self.assertLessEqual(len(out), 2000)
        self.assertTrue(out.splitlines()[-1].startswith("more: "), out[-200:])

    def test_json_lists_rule_message_and_fix(self):
        page = self.everything_wrong()
        code, text, _ = self.check(page)
        code_json, out, _ = self.check(page, "--json")
        self.assertEqual((code, code_json), (1, 1))
        found = json.loads(out)
        self.assertIsInstance(found, list)
        for item in found:
            self.assertEqual(sorted(item), ["fix", "message", "rule"])
        self.assertEqual([f"{i['rule']}: {i['message']}. {i['fix']}" for i in found], text.splitlines())


class ReadOnlyTest(CardCase):
    def test_the_checker_reads_through_fetch_only_and_writes_nothing(self):
        verbs = []
        real_main = self.n.main

        def spy(argv=None):
            verbs.append(argv[0])
            return real_main(argv)

        self.n.main = spy
        page = self.add(cf.task(1, full_task(), status="Rollout", pr=PR_URL))
        project = self.add(cf.project(2, cf.project_body(current=CURRENT)))
        for argv in (["check", page], ["check", page, "--body-replaced", "--json"], ["accept-request", page],
                     ["check", project], ["accept-request", project]):
            cf.run_main(self.cc, argv)
        self.assertTrue(verbs)
        self.assertEqual(set(verbs), {"fetch"})
        for call in self.fake.calls:
            self.assertNotIn(call.method, ("PATCH", "DELETE", "PUT"), call.path)
            if call.method == "POST":
                self.assertFalse(call.path.startswith(("/v1/pages", "/v1/comments")), call.path)


EMPTY_PARAGRAPHS = ("<p />", "<p/>", "<empty-block/>")


class ReadBackTest(CardCase):
    """Notion reads bold back as <b>...</b>, escapes an underscore and an ampersand, wraps a coloured
    label in a span and writes an empty paragraph as a tag line: the same card, the same result."""

    @staticmethod
    def read_back(body):
        body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", body)
        return body.replace("_", "\\_")

    def test_the_read_back_form_reads_as_the_written_one(self):
        written = full_task().replace("Critério observável 1.", "Critério observável em snake_case 1.")
        number = 0
        for objective in ("Exportar as faturas.", ""):
            for body in (written.replace("Exportar as faturas do mês numa planilha.", objective),):
                both = []
                for form in (body, self.read_back(body)):
                    number += 1
                    page = self.add(cf.task(number, form, status="Rollout", pr=PR_URL, summary=SUMMARY))
                    both.append(self.rules(page))
                self.assertEqual(both[0], both[1])
                self.assertEqual(both[0], [] if objective else ["objective"])
        self.assertIn("<b>Objetivo:</b>", self.read_back(written))
        prs = self.add(cf.task(20, self.read_back(full_task(prs="ledger-api #12")), status="Code Review", summary=SUMMARY))
        self.assertIn("pr-link", self.rules(prs))
        form = self.add(cf.task(21, "## Prazo\n\nSexta.\n\n" + fechamento() + "\n<b>PR:</b> #12\n", status="Done",
                                email="c@example.com", pr=PR_URL, summary=SUMMARY))
        self.assertEqual(self.rules(form), [])
        scope = self.add(cf.project(22, cf.project_body(current=CURRENT.replace("**12/11**", "<b>12/11</b>"))))
        self.assertEqual(self.rules(scope), [])
        status = self.add(cf.task(23, full_task() + "\n<b>Status:</b> Done\n"))
        self.assertEqual(self.rules(status), ["status-in-body"])
        for offset, empty in enumerate(EMPTY_PARAGRAPHS):
            with self.subTest(empty=empty):
                body = full_task().replace("**Pronto quando:**\n\n", "**Pronto quando:**\n" + empty + "\n")
                body = body.replace("## Entrega\n\n", "## Entrega\n" + empty + "\n")
                page = self.add(cf.task(30 + offset, body, status="Rollout", pr=PR_URL, summary=SUMMARY))
                self.assertEqual(self.rules(page), [])
                log = self.add(cf.project(40 + offset, cf.project_body(current=CURRENT + empty + "\n")))
                self.assertEqual(self.rules(log), [])
        coloured = full_task().replace("**Objetivo:**", '<span color="blue"><b>Objetivo:</b></span>')
        self.assertEqual(self.rules(self.add(cf.task(50, coloured, status="Rollout", pr=PR_URL, summary=SUMMARY))), [])
        for offset, date in enumerate(('<span color="red"><b>12/11</b></span>', '**<span color="red">12/11</span>**')):
            with self.subTest(date=date):
                body = cf.project_body(current=CURRENT.replace("**12/11**", date))
                self.assertEqual(self.rules(self.add(cf.project(60 + offset, body))), [])
        unbold = cf.project_body(current=CURRENT.replace("**12/11**", '<span color="red">12/11</span>'))
        self.assertEqual(self.rules(self.add(cf.project(62, unbold))), ["scope-log"])
        entity = cf.project_body(current=CURRENT).replace("Discovery & Define", "Discovery &amp; Define")
        self.assertIn("Discovery &amp; Define", entity)
        self.assertEqual(self.rules(self.add(cf.project(51, entity))), [])

    def test_the_request_digest_is_the_same_for_both_forms(self):
        written = "## Pedido\n\nO **time** de cobrança quer o arquivo faturas_do_mes.csv.\n\n"
        self.assertEqual(self.cc.digest(written), self.cc.digest(self.read_back(written)))
        self.assertNotEqual(self.cc.digest(written), self.cc.digest(written.replace("cobrança", "vendas")))
        for empty in EMPTY_PARAGRAPHS:
            self.assertEqual(self.cc.digest(written), self.cc.digest(written.replace("\n\nO ", "\n" + empty + "\nO ")))
        self.assertEqual(self.cc.digest("Contas a pagar & receber."), self.cc.digest("Contas a pagar &amp; receber."))
        page = self.add(cf.task(1, written + entrega()))
        self.assertClean(page)
        self.set_body(page, self.read_back(written + entrega()))
        self.assertClean(page)
        self.set_body(page, self.read_back(written + "<empty-block/>\n" + entrega()))
        self.assertClean(page)


if __name__ == "__main__":
    unittest.main()
