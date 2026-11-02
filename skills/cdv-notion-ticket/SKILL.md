---
name: cdv-notion-ticket
description: >
  Write the business-facing delivery note on a feature's Notion card — short pt-BR delivery-note layout (TL;DR callout, Antes/Agora table, como usar, próximos passos with the PR link) grounded in the branch's real diff, written into the card through the Notion MCP after the user confirms the draft. Sits beside cdv-finalize — that one produces the technical PR description; this one produces the business delivery description (Notion). Triggers on "gera o ticket da entrega", "descrição pra o card do Notion", "nota de entrega", "delivery note", "o que escrevo no ticket dessa feature". Do NOT use for the PR description (cdv-finalize), bug-analysis Notion blocks (cdv-debug Step 8 owns the Análise técnica template), or planning artifacts.
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

This skill writes to a Notion card: when `profile.ticket_system` is not `notion`, say so and stop.

## Operating principles

- **Grounded in the real diff.** Start from `git log --oneline origin/<profile.default_branch>..HEAD` + `git diff --stat/--name-status origin/<profile.default_branch>..HEAD` and read the key files enough to describe what changed for the user/business — not to review code. **What is not in the diff does not go in.**
- **Short.** The delivery-note layout in [references/ticket-format.md](references/ticket-format.md): TL;DR callout, Antes/Agora table, como usar, próximos passos. There is no long format (pilares, Termos, Validação).
- **Reads as a feature spec, never as a chronology.** No "executado durante o rollout", "agora corrigido", "anteriormente fazia X".
- **No status in the body.** The card's Status property conveys it.
- **Written by the MCP, after a yes.** The draft is shown in the chat first; the card changes only after the user confirms. Never change the card's Status (the extension says why).

## Workflow

### Step 1 — Ground in the diff and find the card

Run the git commands above and read the central files of the delivery. The card is the one the PR's `🏷️ Ticket` section links (`<profile.pr_cli> pr view <N>` from `cdv-open-pr`), the one named in the conversation or `STATE-<slug>.md`, or — when none — a `notion-search` in the ticket database (`profile.ticket_database`). With no card at all, `cdv-open-pr` Step 3 creates the ticket; come back here afterwards.

### Step 2 — Draft

Per the format file. `notion-fetch` the card first: an existing note is rewritten as if it had always said the final thing. A request written by someone else (the sections the extension names) stays below the note; a request the session itself wrote that the delivery outgrew is replaced by the note. When the delivery is broader than the card's title, propose the new title in the same confirmation.

### Step 3 — Show and confirm

Print the draft in the chat and ask once: *"Escrevo essa nota no card <KEY>?"*. On a yes, write it with `notion-update-page` (`replace_content` for a card whose body is all being replaced, `update_content` for an existing note, `insert_content` at the start otherwise), set the icon the extension names, and report the card link. On a no, the draft stays in the chat for the user to adjust.

## Composition

- `cdv-finalize` → `cdv-open-pr` → this skill: run it once the PR exists, so the note can link it.
- `cdv-debug` — owns the *bug analysis* Notion block (Análise técnica template), a different artifact.
