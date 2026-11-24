---
name: cdv-notion-ticket
description: >
  Own a Notion task card and a helpdesk form ticket from the request to the closing, in the card contract (references/card-contract.md): write the card at each moment of its event - request arrives, plan approved (the delivery zone and the plan as a child page), pull request open (the PRs line, the pull request property, the one-sentence summary), merged or deployed (the closing), validated by who asked - set the status of that moment, triage and close a form ticket, merge request cards that one delivery serves, and hold every write to card_contract.py check. Works through the cdv-notion client, in a repository or at user level. Called by cdv-kickoff, cdv-open-pr, cdv-debug, cdv-rollout and cdv-prod at their events; triggers on "atualiza o card", "fecha o chamado", "escreve o card dessa entrega", "o que escrevo no ticket", "junta esses cards". Do NOT use for the pull request description (cdv-finalize), a project page (cdv-notion-project), or the investigation report of a bug (cdv-debug keeps it in the chat).
metadata:
  version: 0.2.0
  owner: augusto-henriques
---

# Notion card

Writes the card a delivery lives on, for whoever asked and for the business. The card holds three things with an owner each: the request, in the words of who asked; the delivery, the unit the developer builds, with its plan one click away; and a short closing that says what changed for who asked. The contract in [references/card-contract.md](references/card-contract.md) is the only layout: its zones, labels, limits and skeletons (`scripts/card_contract.py skeleton <kind>`). The names of the workspace (data sources, properties, statuses) are the names map of `scripts/card-contract.json`, called here by role: the summary property, the pull request property, the in progress status.

## Step 0 - Load the profile and the extension

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). Where the folder has no harness profile (the user-level install, outside any repository), the skill still writes and checks a card from the contract and the names map alone, and skips only the steps that read a profile key.
2. Read `<profile.extension_dir>/cdv-notion-ticket.md` when it exists. The extension only adds or restricts what this repository's cards carry (the system and area a new card takes, the icon, the url shapes); it never replaces the contract.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

With a profile, `profile.ticket_system` decides: `none` means there is no card, so skip this skill; another system than `notion` means say so and stop.

Every Notion step below runs through the `cdv-notion` client (`.claude/skills/cdv-notion/scripts/notion` in a repository, `<config dir>/skills/cdv-notion/scripts/notion` at user level, written `notion` below; its skill has the commands and the markdown). When `notion auth status` exits `3` there is no token on this machine: write nothing to Notion, leave the text in the chat to paste, and say the developer runs `notion auth login` in a terminal.

## Operating principles

- **The request is never rewritten.** When the skill takes over a card whose body someone else wrote, it puts that text under `## Pedido` without changing a word of it, and writes its own text only under `## Entrega` and `## Fechamento`.
- **The delivery reads as the current state.** `## Entrega` and the plan page say what is true now, never a history of how it got there.
- **No status in the body.** The status property conveys it.
- **Status by event only.** Each moment below sets the status of its role, on the event that starts it; the done status needs the developer's word that who asked validated the delivery. Nothing else moves a status.
- **Checked after every write.** Run `scripts/card_contract.py check <card>` after a write and correct what it reports; the `card-check` hook runs the same check after every card write and puts its findings beside the tool result. A finding about another person's card or an older card is never forced: the developer decides.
- **Written by the client, after a yes - or, in a run, without one.** Outside a `cdv-kickoff` run the text of a body write is shown in the chat first and the card changes only after the developer confirms. Inside a run the card is part of what the run does unattended: write it and put the text in the final report.

## The five moments of a task card

The contract's table of moments is the reference; each moment below names its write.

### 1. Request arrives - not started

When the skill creates a card, the requester is who asked (the developer only when the work started with them), and the request tag is set only when someone else asked or the type is the bug type. The card is created with `notion create --parent <tasks data source> --set '<title property>=<title>' --set '<requester property>=<who asked>' --set '<type property>=<type>' --body-file <request.md>`, where the body holds `## Pedido` with the request as it arrived; properties only otherwise, and the not started status.

### 2. Plan approved, or work starts on a track with no plan - in progress

When a plan is approved, write `## Entrega` from the plan (the objective in one sentence, 1 to 5 criteria someone can observe, what stays out of this delivery, the repositories), create the plan page as a child of the card, mention it on the `**Plano:**` line, and set the in progress status, the assignee, the type and the current sprint.

- The plan page: `notion create --parent <card key> --set 'title=Plano técnico: <card title>' --body-file <plan.md>`, from the approved plan converted to the client's markdown, with the criteria as bullets whose number is bold (`- **12.** ...`) and every `$` outside code escaped as `\$`. It never goes into a commit.
- The `**Plano:**` line mentions the page it printed: `<mention url="<page url>">Plano técnico: <card title></mention>`.
- On a track with no plan there is no child page and no `**Plano:**` line: `## Entrega` takes the objective and the criteria from the request (`skeleton task-small`).
- The current sprint is the row of the sprints source whose sprint status is the current one: `notion query <sprints data source> --where '<sprint status property> = <current>'`.

When the plan changes during the build, rewrite the plan page and `## Entrega` as the current state, with no history in them, and hand the change to `cdv-notion-project` when the card belongs to a project.

### 3. Pull request open - pull request open

When a pull request is opened for the card, add it to the `**PRs:**` line as `<repository> #<n>`, fill the pull request property when it is empty, copy the first sentence of the pull request's TL;DR into the summary property unchanged, and set the pull request open status.

- Read the TL;DR from the pull request (`<profile.pr_cli> pr view <N>`) or from `<slug>-pr.md` before `cdv-open-pr` deletes it. Its first sentence is at most 200 characters and says what changed for who asked (`cdv-finalize` writes it that way).
- The property holds one url: the first pull request. Every pull request is on the `**PRs:**` line.
- While the card lists a pull request of another repository that has not reached the same event, leave the status as it is and say which pull request it waits for.

### 4. Merged or deployed - merged or deployed

When the developer says the pull request merged or deployed, write `## Fechamento` with 1 to 3 items (what changed for who asked; `Fora do código:` for what depends on someone outside the code) and set the status of that event.

- A manual production step is recorded as one comment on the card (what ran, when, by whom, the result) with `notion comments add <card> --body '<text>'`, and never as a change to the body. The comment stays open: the API cannot read a resolved one.

### 5. Validated by who asked - done

Set the done status only when the developer says who asked validated the delivery.

When a card whose request came from someone else is closed, offer the developer a draft of a message to that person carrying the summary sentence and the card's link, and never send it: a Slack draft through the connector when one is available (the kickoff's recipe, `cdv-kickoff/references/optional/slack-draft.md`), otherwise the text in the chat.

## Writing the body

`notion fetch <card>` first, always. Then the smallest edit: `notion update <card> --edit '<old text>' '<new text>'` for a line or a zone, `--append-file <file.md>` to add `## Fechamento`, `--replace-file <file.md>` only for a body that is being replaced on purpose (the check then judges the whole card, whoever it belongs to). When no `--edit` matched, the client exits `1` and nothing is changed; when some `--edit` matched and some did not, it exits `4` naming the ones that did not. Either way the card is re-read and the missed edits retried once, never forced with a rewrite. Properties go with `--set`, in the names of the names map.

## A helpdesk form ticket

A form ticket is a card whose form e-mail property is filled and whose body has no `## Pedido`: the form's sections are the request.

- When a form ticket is picked up, change only properties (type, requester, assignee, sprint), replace a fixed process title by one that describes the request, name a duplicate in a comment on both cards, and never touch the body.
- When a form ticket is closed with a pull request, fill the summary property, append the closing skeleton (`skeleton form-closing`) with 1 to 3 items and the line `PR: #<n>` linked to the pull request, and fill the pull request property.
- When a form ticket is closed with no code change, fill the summary property: no `## Fechamento` is owed.

## Several requests, one delivery

When several request cards are served by one delivery, keep the card with the lowest key, propose a title that names the delivery, copy each other request under `## Pedido` headed by its key, add its requester to the requester property, set each other card to the archived status with `Pedido atendido em <key of the kept card>.` as the first line of its body, trash none, and run `scripts/card_contract.py accept-request <kept card>` so the merged request becomes the pinned one.

## Composition

- `cdv-kickoff` - runs the plan approved moment when the plan is approved or, on a track with no plan that started from a card, when the `build` stage starts, and this skill as the `ticket` stage of a run.
- `cdv-open-pr` - finds or creates the card and calls the pull request open moment.
- `cdv-rollout` and `cdv-prod` - call the merged or deployed moment and the production-step comment.
- `cdv-debug` - hands a form ticket's triage and closing here when it fixes a bug.
- `cdv-notion-project` - owns the project page; a plan change of a card that belongs to a project goes there too.
- `cdv-notion` - the client every step runs through.
