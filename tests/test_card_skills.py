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

    def test_the_reference_says_which_hidden_writes_the_hook_does_not_see(self):
        self.assertSentence(read(CONTRACT), r"output is hidden", r"any other shape", r"not seen", r"bash -c", r"redirection",
                            r"substitution", r"interpreter", *(rf"`{name}`" for name in (
                                "env", "timeout", "nice", "nohup", "time", "exec", "command", "sudo", "if", "for", "while",
                                "until")))

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

    def test_ticket_status_keys_leave_the_schema_and_the_core(self):
        keys = ["ticket_status_" + suffix for suffix in ("pr_open", "merged", "deployed")]
        schema = read(REPO_ROOT / "profile.schema.yaml")
        for key in keys:
            self.assertNotRegex(schema, rf"^\s+{key}:", key)
        for name, text in core_text_files():
            for key in keys:
                self.assertFalse(key in text, f"{name} still cites {key}")

    def test_cdv_notion_keeps_workspace_ids_out_and_points_to_the_contract(self):
        text = skill("cdv-notion")
        self.assertSentence(text, r"ids and keys of a real workspace", r"never in this core",
                            r"card-contract\.md", where="cdv-notion/SKILL.md")
        self.assertNoSentence(text, r"property names of a real workspace", where="cdv-notion/SKILL.md")


def core_text_files():
    """Every tracked text file of the core but the changelog and the tests."""
    names = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.split()
    for name in names:
        path = REPO_ROOT / name
        if name == "CHANGELOG.md" or name.startswith("tests/") or not path.is_file() or path.suffix in (".png", ".jpg", ".pyc"):
            continue
        try:
            yield name, path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


class TicketSkillTest(SentenceCase):
    def setUp(self):
        self.text = skill("cdv-notion-ticket")

    def sentence(self, *patterns):
        return self.assertSentence(self.text, *patterns, where="cdv-notion-ticket/SKILL.md")

    def test_ticket_skill_states_the_five_moments_and_points_to_the_contract(self):
        self.assertIn("[references/card-contract.md](references/card-contract.md)", self.text)
        self.sentence(r"names of the workspace", r"names map", r"card-contract\.json")
        moments = re.findall(r"^### (\d)\. (.+) - (.+)$", self.text, re.M)
        self.assertEqual([(n, role) for n, _, role in moments], [
            ("1", "not started"), ("2", "in progress"), ("3", "pull request open"),
            ("4", "merged or deployed"), ("5", "done")])
        self.assertEqual([title for _, title, _ in moments], [
            "Request arrives", "Plan approved, or work starts on a track with no plan", "Pull request open",
            "Merged or deployed", "Validated by who asked"])

    def test_ticket_skill_drops_the_recent_cards_layout_and_the_delivery_note(self):
        for pattern in (r"recent cards?", r"callout", r"\bAntes\b", r"Como usar", r"pr[óo]ximos passos",
                        r"next[- ]steps", r"tag line", r"linha de tags", r"delivery note"):
            self.assertNotRegex(self.text, re.compile(pattern, re.I))
        self.assertFalse((SKILLS / "cdv-notion-ticket" / "references" / "ticket-format.md").exists())
        for name, text in core_text_files():
            self.assertFalse("ticket-format.md" in text, f"{name} still names ticket-format.md")

    def test_ticket_skill_keeps_someone_elses_text_under_pedido(self):
        self.sentence(r"body someone else wrote", r"`## Pedido`", r"without changing a word",
                      r"only under `## Entrega` and `## Fechamento`")

    def test_plan_approved_writes_entrega_and_the_plan_page(self):
        self.sentence(r"plan is approved", r"write `## Entrega` from the plan", r"objective", r"1 to 5 criteria",
                      r"stays out", r"repositories", r"plan page", r"`\*\*Plano:\*\*`|\*\*Plano:\*\*|Plano:",
                      r"in progress status", r"assignee", r"type", r"current sprint")
        self.sentence(r"`notion create --parent <card key> --set 'title=Plano técnico: <card title>'",
                      r"criteria as bullets whose number is bold", r"every `\$` outside code escaped")
        self.sentence(r"track with no plan", r"no child page", r"no `\*\*Plano:\*\*` line|no `Plano:` line")

    def test_a_changed_plan_rewrites_the_plan_page_and_entrega_as_current_state(self):
        self.sentence(r"plan changes during the build", r"rewrite the plan page and `## Entrega`",
                      r"current state", r"no history", r"`cdv-notion-project`", r"belongs to a project")

    def test_pr_open_adds_the_prs_line_property_summary_and_status(self):
        self.sentence(r"pull request is opened", r"`\*\*PRs:\*\*`|PRs:", r"`<repository> #<n>`",
                      r"fill the pull request property when it is empty",
                      r"first sentence of the pull request's TL;DR", r"summary property unchanged",
                      r"pull request open status")

    def test_the_status_waits_for_a_pr_of_another_repository(self):
        self.sentence(r"pull request of another repository", r"not reached the same event",
                      r"leave the status as it is", r"say which pull request it waits for")

    def test_merged_or_deployed_writes_fechamento_and_sets_the_status(self):
        self.sentence(r"merged or deployed", r"write `## Fechamento` with 1 to 3 items", r"`Fora do código:`",
                      r"status of that event")

    def test_an_existing_fechamento_is_filled_and_one_is_appended_only_when_there_is_none(self):
        self.sentence(r"already holds `## Fechamento`", r"skeleton's, with its placeholders", r"that zone filled",
                      r"appended only when the card has none")
        self.sentence(r"`--append-file <file\.md>`", r"`## Fechamento` to a card that has none")
        limits = section(read(CONTRACT), "Limits")
        self.assertSentence(limits, r"placeholder of a skeleton", r"is not an item", where="card-contract.md")
        self.assertSentence(limits, r"one `## Fechamento`", r"second", r"finding", where="card-contract.md")

    def test_done_only_when_the_developer_says_who_asked_validated(self):
        self.sentence(r"done status only when the developer says who asked validated")

    def test_a_production_step_is_one_comment_not_a_body_line(self):
        self.sentence(r"manual production step", r"one comment on the card", r"what ran, when, by whom, the result",
                      r"`notion comments add", r"never as a change to the body")

    def test_merged_requests_keep_the_lowest_key_and_archive_the_others(self):
        self.sentence(r"several request cards are served by one delivery", r"lowest key",
                      r"propose a title that names the delivery", r"under `## Pedido` headed by its key",
                      r"requester property", r"archived status", r"`Pedido atendido em <key of the kept card>\.`",
                      r"trash none", r"`scripts/card_contract\.py accept-request <kept card>`")

    def test_requester_is_who_asked_and_the_tag_only_for_others_or_bugs(self):
        self.sentence(r"creates a card", r"requester is who asked",
                      r"developer only when the work started with them",
                      r"request tag is set only when someone else asked or the type is the bug type")

    def test_closing_offers_a_draft_to_who_asked_never_sent(self):
        self.sentence(r"request came from someone else is closed", r"draft of a message", r"summary sentence",
                      r"card's link", r"never send it", r"Slack draft", r"connector", r"otherwise the text in the chat")

    def test_without_a_profile_the_skill_works_from_the_contract(self):
        self.sentence(r"no harness profile", r"user-level install", r"still writes and checks a card",
                      r"contract and the names map", r"skips only the steps that read a profile key")
        self.assertNoSentence(self.text, r"profile\.yaml` is missing", r"stop", where="cdv-notion-ticket/SKILL.md")


class HelpdeskTest(SentenceCase):
    def setUp(self):
        self.text = skill("cdv-notion-ticket")

    def test_picking_up_a_form_ticket_changes_properties_only(self):
        self.assertSentence(self.text, r"form ticket is picked up", r"change only properties",
                            r"type, requester, assignee, sprint", r"fixed process title",
                            r"duplicate in a comment on both cards", r"never touch the body")

    def test_closing_a_form_ticket_with_a_pr(self):
        self.assertSentence(self.text, r"form ticket is closed with a pull request", r"fill the summary property",
                            r"`skeleton form-closing`", r"1 to 3 items", r"`PR: #<n>` linked to the pull request",
                            r"fill the pull request property")

    def test_closing_a_form_ticket_without_code(self):
        self.assertSentence(self.text, r"form ticket is closed with no code change", r"fill the summary property",
                            r"no `## Fechamento` is owed")

    def test_debug_writes_no_analysis_block_and_hands_the_card_to_ticket(self):
        debug = skill("cdv-debug")
        self.assertFalse((SKILLS / "cdv-debug" / "references" / "notion-ticket-template.md").exists())
        for pattern in (r"Análise técnica", r"notion-ticket-template", r"`notion update", r"--append-file",
                        r"Render the .* block for the ticket"):
            self.assertNotRegex(debug, re.compile(pattern, re.I))
        steps = re.findall(r"^### Step (\d+) — (.+)$", debug, re.M)
        self.assertEqual(steps[-1][0], "8")
        self.assertIn("Two lanes when fix intent appears", steps[-1][1])
        self.assertSentence(debug, r"report stays in the chat", r"nothing of it is written on the card", where="cdv-debug")
        self.assertSentence(debug, r"fix intent", r"card or a form ticket", r"triage and its closing",
                            r"`cdv-notion-ticket`", where="cdv-debug")
        for name, text in core_text_files():
            self.assertFalse("notion-ticket-template" in text, f"{name} still names notion-ticket-template.md")


class OtherSkillsTest(SentenceCase):
    def test_kickoff_reads_the_card_with_its_comments_through_the_client(self):
        self.assertSentence(skill("cdv-kickoff"), r"run starts from a card", r"open comments", r"`cdv-notion` client",
                            r"`notion fetch <card> --discussions`", r"request from `## Pedido`",
                            r"criteria from `## Entrega`", where="cdv-kickoff")

    def test_kickoff_runs_the_plan_approved_moment_at_plan_approval(self):
        self.assertSentence(skill("cdv-kickoff"), r"stop `plan-approval` is answered", r"every track that has a plan",
                            r"before the build starts", r"plan approved moment of `cdv-notion-ticket`",
                            r"no card exists", r"ask once whether to create it", where="cdv-kickoff")

    def test_the_plan_approved_moment_runs_in_every_mode_and_on_a_track_with_no_plan(self):
        kickoff = skill("cdv-kickoff")
        self.assertSentence(kickoff, r"mode that has no such stop", r"`autonomous`", r"`step-by-step`",
                            r"plan is approved when the `plan` stage ends", r"same moment runs then", where="cdv-kickoff")
        self.assertSentence(kickoff, r"track with no plan", r"run that started from a card", r"that moment",
                            r"when the `build` stage starts", r"`## Entrega` with no `Plano:` line",
                            where="cdv-kickoff")
        self.assertSentence(kickoff, r"track with no plan and no card", r"nothing is asked and nothing is written",
                            where="cdv-kickoff")
        self.assertSentence(skill("cdv-notion-ticket"), r"`cdv-kickoff`", r"plan approved moment", r"plan is approved",
                            r"track with no plan", r"`build` stage starts", where="cdv-notion-ticket")

    def test_kickoff_flags_a_plan_too_big_for_one_card(self):
        self.assertSentence(skill("cdv-kickoff"), r"more than one delivery that could ship alone",
                            r"more than about a week and a half of work", r"say so at the plan stop",
                            r"leave the split to the developer", where="cdv-kickoff")

    def test_ticket_stage_ends_with_a_clean_check_or_its_findings_reported(self):
        self.assertSentence(skill("cdv-kickoff"), r"`ticket` stage ends", r"`card_contract\.py check <card>`",
                            r"exited `0`", r"findings are in the run's final report", where="cdv-kickoff")

    def test_open_pr_finds_by_key_first_and_calls_the_pr_open_moment(self):
        text = skill("cdv-open-pr")
        step = section(text, "Step 3 — The ticket")
        items = re.findall(r"^(\d)\. (.+)$", step, re.M)
        self.assertRegex(items[0][1], r"key in the conversation.*branch name.*before any search by theme")
        self.assertRegex(items[1][1], r"`notion search <feature theme>")
        self.assertSentence(step, r"create the card only in the task skeleton", r"request arrives moment",
                            r"`cdv-notion-ticket`", where="cdv-open-pr Step 3")
        self.assertSentence(step, r"requester is who asked", r"request tag is set only when someone else asked or the "
                            r"type is the bug type", where="cdv-open-pr Step 3")
        self.assertSentence(text, r"pull request open moment of `cdv-notion-ticket`", where="cdv-open-pr")
        for gone in (r"leave its Status alone", r"assignee and requester are the user", r"você como assignee"):
            self.assertNotRegex(text, re.compile(gone, re.I))

    def test_finalize_defines_the_first_sentence_for_who_asked(self):
        self.assertSentence(skill("cdv-finalize"), r"first sentence of the TL;DR", r"what changed for who asked",
                            r"at most 200 characters", where="cdv-finalize")
        guidelines = read(SKILLS / "cdv-finalize" / "references" / "PR_GUIDELINES.md")
        self.assertSentence(guidelines, r"primeira frase do TL;DR", r"o que mudou para quem pediu",
                            r"até 200 caracteres", r"resumo do card", where="PR_GUIDELINES.md")
        example = re.search(r"^> (.+)$", guidelines, re.M).group(1)
        first = re.match(r".+?[.!?](?=\s|$)", example).group(0)
        self.assertLessEqual(len(first), 200)

    def test_prod_records_a_write_as_a_card_comment(self):
        text = skill("cdv-prod")
        self.assertSentence(text, r"Record the write as one comment on the card", r"`cdv-notion-ticket`",
                            r"never as a line in its body", where="cdv-prod")
        self.assertNotRegex(text, r"Write one line on the card")


class ProjectSkillTest(SentenceCase):
    def setUp(self):
        self.text = skill("cdv-notion-project")

    def sentence(self, *patterns):
        return self.assertSentence(self.text, *patterns, where="cdv-notion-project/SKILL.md")

    def test_project_skill_is_listed_and_says_when_it_runs(self):
        lint = subprocess.run([str(REPO_ROOT / "bin" / "harness"), "lint"], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)
        self.assertIn("`cdv-notion-project`", read(REPO_ROOT / "CATALOG.md"))
        registry = json.loads(read(REPO_ROOT / "registry.json"))
        self.assertIn("cdv-notion-project", [entry["name"] for entry in registry["skills"]])
        description = re.search(r"^description: >\n((?:  .*\n)+)", self.text, re.M).group(1)
        description = " ".join(description.split())
        for when in (r"briefing to refine", r"project to cut into tasks", r"scope change to log", r"Do NOT use"):
            self.assertRegex(description, when)

    def test_refining_a_project_writes_the_current_toggle_only(self):
        self.sentence(r"refines a project", r"writes nothing inside the request toggle",
                      r"current toggle with the sub-headings of the contract in their order",
                      r"effort score in the checklist toggle and in the score property")
        headings = ["`### 🎯 Objetivo`", "`### ✅ O que será feito`", "`### 🚫 O que NÃO será feito`",
                    "`### 🔗 Dependências`", "`### 🔎 Decisões`", "`### 🧾 Mudanças de escopo`"]
        step = section(self.text, "Step 2 - Refine the briefing")
        positions = [step.index(h) for h in headings]
        self.assertEqual(positions, sorted(positions))

    def test_tasks_are_one_plan_each_and_shown_before_any_card(self):
        self.sentence(r"proposes the tasks of a project", r"each task is one plan",
                      r"about a week and a half of work for a person", r"shown to the developer before any card exists",
                      r"creates only the cards the developer approves", r"task skeleton",
                      r"`## Pedido` quoting the part of the briefing it serves")

    def test_an_approved_plan_updates_the_project_in_one_pass(self):
        self.sentence(r"plan of the project is approved", r"in one pass", r"executors", r"status",
                      r"effort score", r"list of tasks", r"current toggle")

    def test_scope_changes_are_logged_after_the_first_plan_not_fixes(self):
        self.sentence(r"enters or leaves `O que será feito` or `O que NÃO será feito`", r"task is added",
                      r"score changes", r"after the first approved plan", r"one line under `### 🧾 Mudanças de escopo`",
                      r"contract's shape")
        step = section(self.text, "Step 5 - Log a scope change")
        self.assertIn("`- **<dd/mm>** · Entrou: <...>. Saiu: <...>. <who decided, or where it came from>. "
                      "CES de <x> para <y>.`", step)
        self.sentence(r"fix made after the merge", r"log nothing")


class HouseAndDocsTest(unittest.TestCase):
    def test_house_block_states_the_card_rule_in_one_paragraph(self):
        house = read(REPO_ROOT / "instructions" / "house.md")
        paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", house)]
        rules = (r"every plan is a task card", r"card follows the card contract",
                 r"request zone .{0,120}never rewritten", r"write to a card.{0,80}checked by the `card-check` hook")
        found = [p for p in paragraphs if all(re.search(rule, p, re.I) for rule in rules)]
        self.assertEqual(len(found), 1, "one paragraph of the house block holds the four card rules")

    def test_changelog_and_readme_describe_the_change(self):
        changelog = read(REPO_ROOT / "CHANGELOG.md")
        unreleased = changelog.split("## Unreleased", 1)[1].split("\n## v", 1)[0]
        bullets = [" ".join(b.split()) for b in re.split(r"\n(?=- )", unreleased) if b.strip().startswith("- ")]

        def bullet(*patterns):
            found = [b for b in bullets if all(re.search(p, b) for p in patterns)]
            self.assertTrue(found, f"no bullet of ## Unreleased holds all of {patterns}")
            return found[0]

        bullet(r"New skill `cdv-notion-project`")
        bullet(r"`card-check`", r"`PostToolUse`", r"`PostToolUseFailure`", r"A consumer")
        bullet(r"`sync --user", r"`<config dir>/harness/hooks/`", r"settings\.json", r"runs it once per config dir")
        bullet(r"ticket-format\.md", r"notion-ticket-template\.md", r"A consumer drops")
        bullet(r"Removed profile keys", r"`ticket_status_pr_open`", r"`ticket_status_merged`",
               r"`ticket_status_deployed`", r"A consumer deletes")
        readme = " ".join(read(REPO_ROOT / "README.md").split())
        for needle in ("PostToolUse", "PostToolUseFailure", "card-check", "<config dir>/harness/hooks/",
                       "<config dir>/settings.json", "--config-dir", "$CLAUDE_CONFIG_DIR", "cdv-notion-project"):
            self.assertIn(needle, readme)
        self.assertNotIn("PreToolUse hook scripts (require-model, prod-ssh, suite-lock)", readme)


if __name__ == "__main__":
    unittest.main()
