---
name: cdv-notion
description: >
  Read, query, create, edit and comment on Notion pages and data sources through the public REST API with the bundled `notion` client (one API token on the machine, no Notion MCP needed) — fetch a card by url, id or ticket key with its properties and body, query a data source with a readable condition and counts, search, change properties in the short format, edit the body in Notion-flavored Markdown, comment, upload and download files, find people. Triggers on any Notion request: "lê o card", "busca no Notion", "atualiza o status do card", "move o card", "escreve no corpo do card", "comenta no card", "quantos cards", "lista as tasks do projeto", "fetch this Notion page", a pasted notion.so or app.notion.com link, or a ticket key. The core skills that touch the card run their Notion steps through this client. Do NOT use to decide what a delivery note or a bug analysis says (cdv-notion-ticket and cdv-debug own the content), or for another ticket system.
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Notion through the API

One client, `scripts/notion` in this skill, does every Notion read and write. It is installed at `.claude/skills/cdv-notion/scripts/notion` in a repository that vendors the harness and at `~/.claude/skills/cdv-notion/scripts/notion` at user level; below, `notion` means that path (call it by the path, it is not on `PATH`). Python standard library only, nothing to install.

Everything is written as the integration that owns the token: Notion shows the integration as the author of every page and edit. Comments carry the name of the person in `me` (see Rules).

## Step 0 — The token

Run `notion auth status`. Exit `0` names the integration and where the token came from. Exit `3` means there is no usable token: tell the user to run `notion auth login` **in their own terminal** (it reads the token at a hidden prompt and stores it in the keyring), and never ask for the token in the chat, never print a credentials file, never put a token in a repository or an `.env`. [references/setup.md](references/setup.md) says where the token comes from, the capabilities it needs and the settings file. A missing token never blocks the rest of the work: say which Notion step was skipped.

`notion doctor` checks the token, the capabilities and the connected data sources in one go; run it when a command answers `1` and the reason is unclear.

## What to run for each need

`<ref>` is any of: a Notion url (`app.notion.com/p/<id>`, `www.notion.so/<slug>-<id>?source=copy_link`, …), a 32-hex id, a hyphenated id, `collection://<uuid>` for a data source, a ticket key `<PREFIX>-<n>` (resolved through the data source whose unique id carries that prefix), or the title of a connected data source.

| Need | Command |
|---|---|
| Read a card (properties, body, url, parent) | `notion fetch <ref>`; add `--discussions` for the open comments, `--props-only` to skip the body, `--json` for the raw objects |
| Find a card by key | `notion fetch <PREFIX>-<n>`, or `notion search <PREFIX>-<n>` to list it first among other hits |
| See a data source's properties and options | `notion fetch collection://<uuid>` (or its title): the short schema, every name, type and option |
| List a project's tasks | `notion query <tasks data source> --where 'Project has <project url>' --select 'Status,Assignee'` |
| Count or group cards | `notion query <data source> --where '<condition>' --count`, or `--group-by Status` |
| Search by words | `notion search <words>` (titles everywhere, plus title and text properties of each connected data source); `--in <data source>` to stay in one |
| Move status | `notion update <ref> --set 'Status=<option>'` (only when the user or the calling skill says so) |
| Set other properties | `notion update <ref> --set 'Prop=value' --set 'date:Due:start=2026-11-22' --set 'Assignee=me'` |
| Write the body: a small change | `notion update <ref> --edit '<exact current text>' '<new text>'` (repeat `--edit` for more) |
| Write the body: add a section | `notion update <ref> --append-file <file.md>` or `--prepend-file <file.md>` |
| Write the body: rewrite it all | `notion update <ref> --replace-file <file.md>` (after reading it; see Rules) |
| Create a card | `notion create --parent <data source> --set 'Task name=…' --set 'Status=…' --body-file <file.md>`; several at once with `--pages-file pages.json` |
| Create a child page | `notion create --parent <page> --set 'title=…' --body-file <file.md>` |
| Comment | `notion comments add <ref> --body '…'`; answer a thread with `notion comments reply <discussion> --body '…'`; read them with `notion comments list <ref>` |
| Attach an image or a file | `notion upload <file>` prints the markdown line; put it in the body with `--append-file` or `--edit`, within the hour |
| Download an attachment | `notion download <file block or signed url> -o <dir>` |
| Find a person | `notion users find <name or e-mail>` → `user://<uuid>`; `notion whoami` for the person this machine acts for |
| Trash a page | `notion trash <ref> --confirm` (only on an explicit request) |
| Anything else (views, move, templates) | `notion api <METHOD> /v1/<path> [--data '<json>'] [--paginate]` |

Write a multi-line `OLD` or `NEW` from a file: `--edit "$(cat old.md)" "$(cat new.md)"`. A body file is Notion-flavored Markdown: [references/notion-markdown.md](references/notion-markdown.md). The property format and the `--where` language: [references/properties-and-filters.md](references/properties-and-filters.md). What the API cannot do and what to do instead: [references/api-limits.md](references/api-limits.md).

## Rules

- **Fetch before you change.** Read the page (and the data source schema, `notion fetch collection://<uuid>`, before the first write to a data source) and write property and option names exactly as the schema has them. Never guess a column name; an unknown name or option exits `2` with the nearest names, and nothing is sent.
- **The smallest edit.** Prefer `--edit OLD NEW` with `OLD` copied from the current body; it must match exactly one place. When no `--edit` matched, the client exits `1` and nothing is changed; when some `--edit` matched and some did not, it exits `4` naming the ones that did not. `--replace-file` rewrites the whole body and loses what the markdown does not carry; use it for a body that is being replaced on purpose (a card created by this session, a seed), never to change a sentence.
- **Child pages and databases live in the body.** Keep their `<page url="…">` and `<database url="…">` tags when rewriting; the client refuses a rewrite that drops one. Never pass `--allow-deleting-content` without the user confirming the list it printed.
- **A list replaces, it does not add.** `--set 'Tags=A,B'` makes the tags exactly A and B, the same for people, relations and files: read the current value and include what stays.
- **Status moves by event only.** Change a status when the user asks or a skill step says so; a status change can fire the data source's automations (dates stamped, notifications). Never trash, never resolve, never delete without an explicit request.
- **People by id.** In a property write `user://<uuid>`, a unique name, an e-mail or `me`; in a body or comment use `<mention url="user://<uuid>">Name</mention>`, never a bare `@Name`. `me` is the person whose e-mail is `me` in `~/.config/cdv-notion/config.json` (else `git config user.email`).
- **Comments are signed.** With a workspace integration token the comment shows the name of `me`; with a personal token it shows its owner. Only the comments this token wrote can be edited.
- **Report what the client reports.** Exit `4` (done in part: some `--edit` did not match, or a later write was refused, never sent or ended in doubt after an earlier one landed) and every `warning` line go to the user as they are; re-fetch and retry only what was not written or not sent. A write that fails is one of three cases, and every verb says which: **refused** (a 4xx, or a 429 after its retries: "Notion refused it and nothing changed"), **not sent** (the connection could not be made: "the request never left this machine, so nothing changed"), or **in doubt** (any 5xx, a timeout, or a connection lost after the request left: "may have been applied"). Only the first two are safe to run again as they are; fetch the page and check a write in doubt before running it again. Nothing is sent until every property, option, file and page of a `--pages-file` checks out, so an exit `2` means nothing changed.
- **Results are sized for the model.** `query` prints 50 rows unless `--limit` says otherwise and stops paging at 2,000 rows (`--max-rows` raises it); prefer `--count`, `--group-by` and `--select` to dumping rows.
- **No workspace id goes into a repository.** Ids and keys of a real workspace stay in the consumer's profile and extension files, never in this core; the names the card pattern uses (data sources, properties, statuses, toggles) are the names map of the card contract, [cdv-notion-ticket/references/card-contract.md](../cdv-notion-ticket/references/card-contract.md).

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| `0` | done | — |
| `1` | Notion refused or could not be reached, or the first write is in doubt (the message says which); on 403/404 the message names the page to connect; no `--edit` matched (nothing changed) | connect the integration to the page (menu → Connections) or report it; for edits, re-fetch and copy `OLD` as the body has it now; for a write in doubt, fetch and check before running it again |
| `2` | the command is wrong: unknown property or option (nearest names listed), a condition that does not compile, a refused path | fix the command; nothing was sent |
| `3` | no usable token (missing, revoked, mistyped) | the user runs `notion auth login` in a terminal |
| `4` | done in part: some `--edit` did not match, or a later write was refused (`Not written`, `Not created`), never sent (`Not sent`) or ended in doubt (`In doubt`) after an earlier one landed (the properties set, the pages created, by url) | report what was written, what was not and what is in doubt; re-fetch and rerun only what was not written or not sent, never the whole command; check a step in doubt in Notion before running it again |

A rate limit (429) is waited out inside the client (`Retry-After`, at most 5 times). A create in doubt (any 5xx, a timeout, a connection lost after the request left) is never sent twice: the client looks for the page first. When it finds none, or cannot look (the search fails, times out or keeps answering 429), the create stays `In doubt`: look for a page with that title in that parent before creating it again. Notion stores `created_time` to the minute, so the page found is one with that title made by this integration since the minute the command started, and a page with the same title made earlier in that minute (another run, a teammate on the same token) cannot be told apart: read the page found (`notion fetch <url>`) before treating it as the new one.

## Composition

- `cdv-notion-ticket` — the task card and the form ticket at each moment, in the card contract: it decides the content, this client writes it.
- `cdv-open-pr` — finds or creates the ticket and links the pull request with these commands.
- `cdv-debug` — reads the card a bug report came with; it writes nothing on it.
- `cdv-rollout`, `cdv-prod`, `cdv-kickoff` — status moves, one-line notes and plan pages on the card, through the same commands.
