---
name: cdv-notion-project
description: >
  Own a Notion project page in the card contract: keep the briefing as it arrived in the request toggle, write the project as it stands in the current toggle (objective, what will and will not be done, dependencies, decisions, the dated scope log), score its effort, cut it into tasks the size of one plan each and create only the cards the developer approves, and log every scope change after the first approved plan. Runs when there is a briefing to refine, a project to cut into tasks, a plan of the project approved, or a scope change to log; triggers on "refina esse projeto", "quebra o projeto em tasks", "registra a mudança de escopo", "atualiza a página do projeto". Works through the cdv-notion client, in a repository or at user level. Do NOT use for a task card or a helpdesk ticket (cdv-notion-ticket), for the plan of one task (tlc-spec-lean, started by cdv-kickoff), or to rewrite the request toggle, which no skill writes.
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Notion project page

A project page holds a briefing that arrives once and a project that changes as it is built. The page keeps both apart: the request toggle holds the briefing as it arrived, and the current toggle holds the project as it stands, with a dated log of what changed. The layout is the project page of the card contract, [cdv-notion-ticket/references/card-contract.md](../cdv-notion-ticket/references/card-contract.md); `card_contract.py skeleton project` (in `cdv-notion-ticket/scripts/`) prints what goes inside the current toggle. The names of the workspace (the projects source, its three toggles, the executors and score properties) are the names map of `cdv-notion-ticket/scripts/card-contract.json`, called here by role.

## Step 0 - Load the profile and the extension

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). Where the folder has no harness profile (the user-level install), the skill works from the contract and the names map alone, and skips only the steps that read a profile key.
2. Read `<profile.extension_dir>/cdv-notion-project.md` when it exists. The extension only adds or restricts.

Every Notion step runs through the `cdv-notion` client (`notion` below; its skill has the commands and the markdown). When `notion auth status` exits `3` there is no token on this machine: write nothing to Notion, leave the text in the chat to paste, and say the developer runs `notion auth login` in a terminal.

## Operating principles

- **The request toggle is never written.** The briefing stays as it arrived; a change of what is asked is a scope line, not an edit of the briefing.
- **The current toggle is the project as it stands.** Rewrite it as the current state, never as a history; the history is the scope log.
- **The developer approves before anything is created.** A task list is a proposal until the developer says which cards to create.
- **Checked after every write.** Run `card_contract.py check <project>` after a write and correct what it reports; the `card-check` hook runs the same check after every page write.
- **Written by the client, after a yes - or, in a run, without one**, as `cdv-notion-ticket` does.

## Step 1 - Read the page

`notion fetch <project> --discussions` reads the page, its properties and its open comments. Find the three toggles of the names map: the request toggle, the current toggle and the checklist toggle. A page without them is reported to the developer, never rebuilt by this skill.

## Step 2 - Refine the briefing

When the skill refines a project, it writes nothing inside the request toggle, writes the current toggle with the sub-headings of the contract in their order (`### 🎯 Objetivo`, `### ✅ O que será feito`, `### 🚫 O que NÃO será feito`, `### 🔗 Dependências`, `### 🔎 Decisões`, `### 🧾 Mudanças de escopo`), and writes the effort score in the checklist toggle and in the score property.

- Write the current toggle with `notion update <project> --edit '<the current toggle as it stands>' '<the toggle with its new content>'`, the old text copied from the fetch.
- `### 🎯 Objetivo` is one paragraph in the present tense; `### 🔎 Decisões` points to where the decisions live and, per part, to the task that holds its plan.
- The score is the effort table of the checklist toggle; its total goes to the score property with `notion update <project> --set '<score property>=<total>'`.

## Step 3 - Cut the project into tasks

When the skill proposes the tasks of a project, each task is one plan (at most about a week and a half of work for a person), the list is shown to the developer before any card exists, and the skill creates only the cards the developer approves, each in the task skeleton with `## Pedido` quoting the part of the briefing it serves.

- Each proposed task names what it delivers and the part of the briefing it serves; a part that cannot ship alone joins the task it depends on.
- Create each approved card with `notion create --parent <tasks data source> --set '<title property>=<title>' --set '<project property>=<project url>' --body-file <card.md>`, the body from `card_contract.py skeleton task` with `## Pedido` filled and the rest left for the plan approved moment of `cdv-notion-ticket`.

## Step 4 - A plan of the project is approved

When a plan of the project is approved, update in one pass the executors, the status, the effort score, the list of tasks and the current toggle: one `notion update <project>` with every `--set` and the `--edit` of the current toggle, so the page never shows half a change.

## Step 5 - Log a scope change

When something enters or leaves `O que será feito` or `O que NÃO será feito`, a task is added to the project, or the score changes, after the first approved plan, append one line under `### 🧾 Mudanças de escopo` in the contract's shape: `- **<dd/mm>** · Entrou: <...>. Saiu: <...>. <who decided, or where it came from>. CES de <x> para <y>.`

- A line with no change of score ends `CES sem mudança.`; `Entrou:` or `Saiu:` is left out when nothing entered or left.
- If the change is a fix made after the merge, log nothing: a fix is not a change of scope.
- Before the first approved plan the current toggle is still being written, and nothing is logged.

## Composition

- `cdv-notion-ticket` - owns each task card; a plan change of a card that belongs to a project comes here as well.
- `cdv-kickoff` - starts the run of each task; its plan approved moment updates this page (Step 4).
- `cdv-notion` - the client every step runs through.
