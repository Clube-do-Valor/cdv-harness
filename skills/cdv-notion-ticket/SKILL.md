---
name: cdv-notion-ticket
description: >
  Write the business-facing delivery note on a feature's Notion card — short pt-BR delivery-note layout (TL;DR callout, Antes/Agora table, como usar, próximos passos with the PR link) grounded in the branch's real diff, written into the card with the cdv-notion client after the user confirms the draft (inside a cdv-kickoff run, without the question); once the PR exists the card follows the layout of the project's three most recent cards, links the PR both ways and moves to the PR-open status. Sits beside cdv-finalize — that one produces the technical PR description; this one produces the business delivery description (Notion). Triggers on "gera o ticket da entrega", "descrição pra o card do Notion", "nota de entrega", "delivery note", "o que escrevo no ticket dessa feature". Do NOT use for the PR description (cdv-finalize), bug-analysis Notion blocks (cdv-debug Step 8 owns the Análise técnica template), or planning artifacts.
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Notion Delivery Ticket

Writes the delivery note on the Notion card, for managers and the requesting area. Different document, different audience from the PR: the PR tells the reviewer *how to judge the diff*; this tells the business *what it can now do*. The PR links the card in its `🏷️ Ticket` section; this note links the PR back.

## Step 0 — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-notion-ticket.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

This skill writes to a Notion card: when `profile.ticket_system` is `none` there is no card, so skip it; when it is another system than `notion`, say so and stop.

Every Notion step below runs through the `cdv-notion` client (`.claude/skills/cdv-notion/scripts/notion`, written `notion` below; its skill has the commands and the markdown). When `notion auth status` exits `3` there is no token on this machine: write nothing to Notion, leave the note in the chat as text to paste, and say the developer runs `notion auth login` in a terminal.

## Operating principles

- **Grounded in the real diff.** Start from `git log --oneline origin/<profile.default_branch>..HEAD` + `git diff --stat/--name-status origin/<profile.default_branch>..HEAD` and read the key files enough to describe what changed for the user/business — not to review code. **What is not in the diff does not go in.**
- **Short, in the project's layout.** The three most recent cards of the same project set the layout (properties, sections, their order); the delivery-note layout in [references/ticket-format.md](references/ticket-format.md) fills what they leave open: TL;DR callout, Antes/Agora table, como usar, próximos passos. There is no long format (pilares, Termos, Validação).
- **Reads as a feature spec, never as a chronology.** No "executado durante o rollout", "agora corrigido", "anteriormente fazia X".
- **No status in the body.** The card's Status property conveys it.
- **Written by the client, after a yes - or, in a run, without one.** Outside a `cdv-kickoff` run the draft is shown in the chat first and the card changes only after the user confirms. Inside a run the card is part of what the run does unattended: write it and put the draft in the final report.
- **Status by event only.** The card's Status moves when the pull request opens (`profile.ticket_status_pr_open`, Step 4), and on merge and deploy through `cdv-rollout`; a key set to `none` skips that move. Never any other status change (the extension says why).

## Workflow

### Step 1 — Ground in the diff and find the card

Run the git commands above and read the central files of the delivery. The card is the one the PR's `🏷️ Ticket` section links (`<profile.pr_cli> pr view <N>` from `cdv-open-pr`), the one named in the conversation or `STATE-<slug>.md`, or — when none — `notion search <theme> --in <profile.ticket_database>`. With no card at all, create it in Step 4 (or let `cdv-open-pr` Step 3 create the ticket and come back here afterwards).

Then list the three most recent cards of the same project as this one (`notion query <profile.ticket_database> --where '<project property> has <project url>' --order 'created desc' --limit 3`) and `notion fetch` each: their properties, sections and order are the layout of this card.

### Step 2 — Draft

Per the format file. `notion fetch <card>` first: an existing note is rewritten as if it had always said the final thing. A request written by someone else (the sections the extension names) stays below the note; a request the session itself wrote that the delivery outgrew is replaced by the note. When the delivery is broader than the card's title, propose the new title in the same confirmation.

### Step 3 — Show and confirm

Inside a `cdv-kickoff` run, skip the question: write the note as below and put the draft in the final report. Otherwise print the draft in the chat and ask once: *"Escrevo essa nota no card <KEY>?"*. On a yes, write it with the client: `notion update <card> --replace-file <note.md>` for a card whose body is all being replaced, `--edit '<old text>' '<new text>'` for an existing note, `--prepend-file <note.md>` otherwise; set the icon the extension names with `--icon`, and report the card link. An `--edit` that did not match (exit `4`) is re-read and retried once, never forced with a rewrite. On a no, the draft stays in the chat for the user to adjust.

### Step 4 — After the pull request exists

Where `profile.ticket_system` is not `none`, once the pull request exists, create or update the card in the layout of the three most recent cards of the same project, link the pull request both ways and set the card's status to `profile.ticket_status_pr_open`.

- With the client: create with `notion create --parent <profile.ticket_database> --set '…' --body-file <note.md>`, link and move with `notion update <card> --set '<pull-request property>=<pr url>' --set 'Status=<profile.ticket_status_pr_open>'`.
- The card links the pull request where the recent cards keep it (a property, or the próximos passos of the note); the pull request links the card in its `🏷️ Ticket` section, which `cdv-open-pr` writes - when it is missing, update the description through `profile.pr_cli`.
- When `profile.ticket_status_pr_open` is `none`, the status stays as it is.
- The merged and deployed statuses are `cdv-rollout`'s, on the developer's word.

## Composition

- `cdv-finalize` → `cdv-open-pr` → this skill: run it once the PR exists, so the note can link it. In a `cdv-kickoff` run this is the `ticket` stage.
- `cdv-rollout` — moves the card on merge and deploy.
- `cdv-debug` — owns the *bug analysis* Notion block (Análise técnica template), a different artifact.
