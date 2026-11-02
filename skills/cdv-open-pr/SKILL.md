---
name: cdv-open-pr
description: >
  Open or update the pull request of a branch through the host's API (`profile.pr_cli`, the bundled `bb` client for Bitbucket or `gh` for GitHub) — conventional title, the finalize description plus the `🏷️ Ticket` section with the ticket hyperlinked, the default reviewers, close-source-branch. Called by `cdv-finalize` Step 9 right after the push; triggers on its own on "abre o PR", "open the PR", "abre os PRs dos workers", "atualiza a descrição do PR", "comenta no PR". Claude in Chrome only as the fallback when the developer has no token and does not want to create one now; do NOT use to merge, approve or decline.
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Open PR

Opens the PR with one API call instead of a browser session; it stands on its own and finalize calls it.

## Before anything — load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-open-pr.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
3. Read `references/vcs-<profile.vcs_host>.md`: it holds everything that depends on the host — the commands, the one-time credential setup, the fallback when there is no credential. The steps below say *what* to do; that file says *how*.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

## Operating principles

- **API first.** `profile.pr_cli` (relative to this skill's base directory when it is the bundled `bb`) creates, edits, reads and comments. Claude in Chrome opens a PR only as the fallback for a developer without a credential who does not want to create one now (Step 0, when the VCS reference defines it); otherwise Chrome is for the visual QA of front-end changes.
- **The PR is authored by the person.** The client authenticates with the developer's own credential, so the PR, its notifications and the "author cannot approve" rule stay with whoever wrote the code. A bot or repository credential authors the PR as a bot — not for interactive sessions.
- **The description lives in the PR.** Once the PR carries it, the local `<slug>-pr.md` is deleted; `<profile.pr_cli> pr view <N>` reads it back. Never paste a token, never print a credentials file.
- **A missing credential never blocks.** The push happens anyway, and the PR still gets opened — through the credential created on the spot or through the fallback.
- **Never merge, approve or decline.** Those stay with the reviewers.

## Setup (once per developer)

The credential, its scopes and the login command depend on the host: see `references/vcs-<profile.vcs_host>.md`. The check is always `<profile.pr_cli> auth status`, which must print your own name; run the login in a terminal, never through the chat (the prompt needs a real TTY), and never paste a token in the chat.

## Workflow

### Step 0 — Credential available?

`<profile.pr_cli> auth status`. Exit 0 → go to Step 1. Otherwise (no credential, or one the host rejects) ask once — *"Não achei uma credencial válida para o host do PR. Quer criar agora (uns 2 minutos: o link e os escopos estão no Setup, e você roda o login num terminal) ou abro este PR pelo fallback?"*:

- **Criar agora** → show the Setup steps of the VCS reference, wait for "pronto", re-run `auth status`, continue with Step 1.
- **Fallback** (only when the VCS reference defines one) → run Steps 2–4 the same way, then open the PR the way that reference describes instead of Step 5's `pr create`, read back the PR `id` and URL, and end the report with one line recommending the credential for the next PR. An update (Step 6) through the fallback is the same call with the update verb.

### Step 1 — The branch is on the remote

`git rev-list --count origin/<branch>..HEAD` must be 0 (finalize pushed it). If the branch was never pushed or is ahead, push it first (`git push -u origin <branch>`, feature branches only — a prefix from `profile.branch_prefixes`, never `--force`).

### Step 2 — Open PR already?

Look up the open PR of the branch (`for-branch` on Bitbucket, `gh pr list --head <branch>` on GitHub). When it finds one, this run is an **update**: go to Step 6. None → create.

### Step 3 — The ticket

Skip this step when `profile.ticket_system` is `none`. The PR links its ticket in a `## 🏷️ Ticket` section — the host template's placeholder may be left unfilled. Find it in this order:

1. The conversation or `STATE-<slug>.md` (a ticket URL or a key matching `profile.ticket_key_pattern`).
2. The ticket database (`profile.ticket_database`): with Notion, `notion-search` with the feature's theme; read the hit's key and name. With another ticket system, search it with its own tool.
3. Nothing found → ask once: *"Não achei ticket para essa entrega. Crio um ticket (TL;DR + o que foi feito, você como assignee) ou abro o PR sem ticket?"* On "cria", create it in that database (the extension lists the properties a new ticket takes; assignee and requester are the user) with the body in the `cdv-notion-ticket` layout, then continue.

The section, appended at the end of the description:

```markdown
## 🏷️ Ticket

[<KEY> — <Task name>](<ticket url>)
```

### Step 4 — Front-end changed, visually checked?

When `git diff --name-only origin/<profile.default_branch>...HEAD` has `{app_dir}/resources/js/**/*.vue` or `*.ts` outside tests and this session ran no visual check (`cdv-interactive-qa` or Chrome on the local app), ask once: *"O PR mexe em tela; o QA visual já rodou (aqui ou em outra sessão)?"*. The answer does not block — QA usually runs in a fresh session — but a "não" goes into the report as a pending item.

### Step 5 — Create

- **Title:** Conventional Commits, English, the intent of the whole branch (usually the main commit's subject), with ` (<KEY>)` at the end when there is a ticket — `fix(auth): reject expired invitation tokens (<KEY>)`.
- **Body:** `<slug>-pr.md` from finalize (lint already passed) with the Ticket section appended. Mentions go in the host's markup (`bb mention <name>` on Bitbucket), only when the user asked for them.
- Create the PR with the title and the body file against `profile.default_branch`, not draft, with the repository's default reviewers minus the author where the host has them and `close_source_branch` (the commands are in the VCS reference). The Claude Code footer goes in once.
- When the ticket's pull-request link property is empty, set it to the PR URL (`notion-update-page`, `update_properties` with Notion); leave its Status alone (the extension says why).
- `rm <slug>-pr.md` and report one line: `PR #<N> aberto: <url> · ticket <KEY> · revisores <names>`.

### Step 6 — Update

An open PR is updated only when it no longer matches the branch: new commits since the description was written (finalize Step 8.5 regenerated `<slug>-pr.md`), or the user asked. Ask once — *"O PR #<N> tem commits novos desde a descrição. Atualizo a descrição?"* — then edit the PR description from `<slug>-pr.md` (the Ticket section stays; the command is in the VCS reference) and `rm` the file. Nothing changed → say the PR is current and do nothing.

## Other commands

Read a PR back, list PRs, comment on a PR (only when the user asks to post), CI status of a branch, mention a person: see the VCS reference.

## Composition

- `cdv-finalize` — Step 9 pushes and calls this skill; a re-run after QA fixes lands in Step 6 here.
- `cdv-notion-ticket` — the ticket's body (TL;DR + o que foi feito), written after the PR exists so it can link it.
- `cdv-factory-finalize` — still does not open PRs: the factory pushes and hands back the link.
