"""The card contract checker (skills/cdv-notion-ticket/scripts/card_contract.py) against synthetic cards.

The checker and the cdv-notion client are loaded as modules; the client's transport is a fake Notion
(card_fixtures.CardNotion) and HOME is a temporary directory, so nothing reaches Notion."""

import hashlib
import json
import os
import re
import shutil
import tempfile
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
