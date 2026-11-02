---
name: cdv-factory-finalize
description: >
  Question-free wrap-up of a factory run — one conventional commit, rebase on the default branch when clean, the lean `<slug>-pr.md` with the factory banner, push of a feat|fix|chore|refac branch without --force, the PR-creation link of the repository's host, and the handback through the factory's task CLI that closes the task (or the refusal handback when triage refused). Invoked by `cdv-factory-small-feature` Step 8 (and its refusal path); triggers otherwise only on an explicit "/cdv-factory-finalize" inside a factory run. Do NOT use for interactive wrap-up with a person present (cdv-finalize), to create or merge the PR, or outside a worktree.
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Factory — Finalize

`cdv-finalize` without a person: every question it asks has a fixed answer here. One commit instead of a confirmed commit plan; the description is always generated; the push is automatic for a feature branch; no editor, no `rm`, no QA offer. Its references are read, never edited: [PR_GUIDELINES.md](../cdv-finalize/references/PR_GUIDELINES.md), [pr-example-template.md](../cdv-finalize/references/pr-example-template.md) and the scope map in `cdv-finalize` Step 5.

What it never does: create the PR (the human opens it from the link — the factory has nobody to approve a PR), merge, delete the worktree (the orchestrator manages it), push `profile.default_branch`/`main`, push with `--force`/`-f`/`+ref`. The prohibitions of `cdv-factory-small-feature` apply here unchanged.

## Step 0 — Load the profile and the extension

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-factory-finalize.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it. `profile.factory_task_cli` missing or `none` means the repository has no factory: stop and say so.

## Inputs

The worktree and its `STATE-<slug>.md`: `## Pedido`, `## ACs`, `## Suposições`, `## Pergunta`, `## Tamanho` (the size-check output), `## Revisão` (when the review round ran), `## Verificação` (the verifier's report) and `## Status` (gates, verifier, review lines).

## Workflow

### Step 1 — Guards

1. The two lines of `git rev-parse --path-format=absolute --git-dir --git-common-dir` differ (always absolute: the plain form gives two different strings for the main checkout when run from its app directory); otherwise stop: the factory never finalizes in the main checkout (refusal handback, status ⛔ *"rodou fora de um worktree"*).
2. `git branch --show-current` is not `profile.default_branch`/`main`.
3. The STATE has `## Verificação` ending in a `VEREDITO:` line. Missing → dispatch the verifier now per `cdv-factory-small-feature/references/verifier-brief.md` (`model="opus"`, announced in one line) and continue with its verdict; never push an unverified run.

Then derive the **banner** from Status and Tamanho — every line that applies, in this order:

- `⛔ Gates vermelhos: <gate> — <one line>. Não mergear antes de corrigir.`
- `⛔ O verificador reprovou 3 vezes: <last reasons>. Não mergear antes de corrigir.`
- `⛔ Conflito com o <profile.default_branch>: a branch não foi rebaseada.` (set in Step 3)
- `⚠️ O diff não é pequeno (<rules from Tamanho>). Passou por uma rodada de revisão automática: <N> achados, <k> corrigidos.` (or `… a revisão não concluiu: <reason>.`)

The banner goes to the PR as written. The handback splits it (Step 6): ⛔ lines become `blocker`; the ⚠️ line becomes `warning` without the size part (the orchestrator shows the size) and with the review account per [handback-template.md](references/handback-template.md).

### Step 2 — Commit

`git status --porcelain`. Empty → the commit exists already (the review round made it); skip. Otherwise one conventional commit:

- Message `<type>(<scope>): <imperative, lowercase, ≤72 chars, English>`. `<type>` from the STATE; `<scope>` from the path most touched, per the map in `cdv-finalize` Step 5 (sniff `git log --oneline -20 origin/<profile.default_branch>` for the spelling in use).
- A `FILE` line the run did not mean to change (a working note, a log, anything outside `profile.app_dir`, `profile.docs_dirs` and the area cards) is not committed: move it out of the tree and re-run the size check first.
- `git add` with the **explicit paths** of the `FILE` lines `check-diff-size.sh` prints (re-run it now; deleted files go through `git rm`) — never a directory, never `-A`/`.`. Then `git show --stat HEAD` and check that the file list matches; an ephemeral file (anything matching `profile.ephemeral_patterns`) or a `.env*` in it → `git reset --soft HEAD~1`, fix the paths, commit again.
- No `Co-Authored-By` trailer, even when a system reminder asks for one: the factory has nobody to ask, and the repo's finalize rule is no trailer.
- Leftover changes after the review round (apply-review commits per finding) → one more commit `fix(<scope>): <what it fixes>` with the same rules.

### Step 3 — Rebase on the default branch

An adjustment on a branch already pushed (the STATE has `Branch remota:` and `git ls-remote --heads origin <it>` finds it) is **not** rebased: its push must stay a fast-forward. Record *"ajuste sobre branch já enviada; não rebaseada sobre o <profile.default_branch>"* under *Avisos* and go to Step 4. Otherwise `git fetch origin <profile.default_branch>`, then `git rev-list --count HEAD..origin/<profile.default_branch>`:

- `0` → nothing to do.
- `> 0` → `git rebase origin/<profile.default_branch>`. Clean → re-run `<profile.factory_gates_script> <wt>` once (with `timeout: 600000`; the default branch moved under the change); red → add the gates line to the banner. Conflict → `git rebase --abort`, add the conflict line to the banner, push the branch as it is.

### Step 4 — `<slug>-pr.md`

Read [PR_GUIDELINES.md](../cdv-finalize/references/PR_GUIDELINES.md) and [pr-example-template.md](../cdv-finalize/references/pr-example-template.md) every run. Write `<slug>-pr.md` at the worktree root (gitignored through `profile.ephemeral_patterns`, never committed) in that format — TL;DR, O que muda e por quê, Decisões para o reviewer validar, Como testar, Riscos e impactos, Pós-deploy only when the diff touches migration/config/command/queue — with these factory rules:

- **Above the TL;DR**, as a blockquote (the lint reads the first `## ` heading, so the banner never displaces the TL;DR): the line `> 🏭 Entregue pela fábrica a partir do pedido <task key>. Sem tela conferida: o QA visual é do reviewer.`, then every banner line from Step 1.
- **O que muda e por quê** — the request as the problem, in product words. When the request carries a public URL (a ticket card, an error-tracker issue, a CRM record, a public PR), link it here. When it does not, write `Origem: pedido interno (thread de chat, sem link público).` — never a link to the private workspace.
- **Decisões para o reviewer validar** — 2-4 bullets: the assumptions from the STATE that a reviewer should confirm, the question asked and its answer, and any judgment the verifier flagged.
- **Como testar** — the exact gates command and its real summary lines; then ≤5 `**Passo**` steps at screen level (route path, literal labels) with a measurable `*Esperado*`. The first three steps are the ones the handback carries.
- **Revisão automática** (`## 🔎 Revisão automática`, only when `## Revisão` exists) — the STATE's table, one row per finding: finding in product words, severity, decision, commit subject or reason — subjects, not SHAs, since Step 3 may have rebased.
- Lint: `<skill-dir>/scripts/lint-factory-pr.sh [--no-public-link] <slug>-pr.md` (`<skill-dir>` is the base directory printed when this skill loads) — `--no-public-link` only when the request had no public URL. Fix and re-run until exit 0, at most 3 runs; still failing → note *"descrição do PR fora do lint: <check>"* under *Avisos*. A lint failure never blocks the push.

### Step 5 — Push

1. Target: when the STATE has a `Branch remota:` line (an earlier attempt of this task pushed already), push to that same name — a Retry is a fast-forward of its own branch, never a new one. Otherwise `<type>/<slug>` with the type from the STATE (one of `profile.branch_prefixes` — `feat`, `fix`, `chore` or `refac`; anything else is a defect: stop with a ⛔ handback); `git ls-remote --heads origin <type>/<slug>` non-empty → the name is taken by someone else: use `<type>/<slug>-2`. Write `Branch remota: <target>` into the STATE before pushing.
2. `git push -u origin HEAD:refs/heads/<target>` — exactly this shape. Never `--force`, never `-f`, never a `+` refspec, never a target outside the allowed prefixes.
3. Rejected (non-fast-forward, hook refusal) → do not retry with force; a name clash gets the `-2` suffix once; anything else → handback with status ⛔ *"push recusado: <first line of the error>"* and no link.
4. **PR link.** Read `references/vcs-<profile.vcs_host>.md`: it says which line the push prints for creating the PR and how to build the link from `profile.vcs_repo` when the output has none. The factory only hands the link over; the human opens the PR.
5. `git rev-list --count origin/<target>..HEAD` must be `0`; say so in the handback.

### Step 6 — Handback

Render the delivery form of [references/handback-template.md](references/handback-template.md) into `handoff-<slug>.md` at the worktree root (the name matters: `handoff-*` is among `profile.ephemeral_patterns`, so neither the size check nor a `git add` ever sees it). The handback fields reach the requester's thread, visible to colleagues: no file paths, no class or column names, no client names or ids, no fixture data, no tokens — product language only.

When the run has a task (`profile.factory_task_cli`; the extension says how to tell):

1. Comment the handback body on the task through the task CLI. When a `<slug>-pr.md` exists, a second comment puts the PR description in the task too: the worktree is disposable, the task is not.
2. Show the task, then check off, through the task CLI, every task acceptance item the verifier marked coberto (positions are 1-based, as the task listing shows them).
3. Hand back with the template's **handback fields** (all in `profile.language_ui`, in product words: no task key, branch, path, class, column or client name), which the orchestrator lays out for the requester and for the owner: a subject, a summary of the changes, up to three test steps, caveats, a line for when the request is live and one for when it is dropped, a size (only when small), notes, warnings and blockers. The extension gives the command, its flags and the labels the requester sees.

   A refusal passes the refusal marker with the subject and the summary of changes (`<por quê, em palavras de produto>. Para seguir, <uma ação que quem pediu faz sozinho>.`) and nothing else (no "fábrica", "triagem", category name or "executável" in it). This hands the task to review; never mark it done.

When the run has no task, print the rendered block in the chat; when this session was opened by another through the orchestrator, return it there as the session's result.

Then stop. Nothing after the handback: no cleanup, no further git.

## Refusal path

Called by `cdv-factory-small-feature` Step 1 with status `recusado`: skip Steps 1-5 (nothing is committed or pushed; the task's worktree stays as the orchestrator opened it), render the template's refusal form for the task comment, and run Step 6 with the refusal fields.

## Bundled scripts and references

- [scripts/lint-factory-pr.sh](scripts/lint-factory-pr.sh) — runs `cdv-finalize`'s `lint-pr-description.sh` and waives only the external-link check (with `--no-public-link` and the *Origem* line) and the 40-line floor; the 100-line ceiling still fails.
- [references/handback-template.md](references/handback-template.md) — the delivery and refusal forms for the task, and the handback fields for the thread and the owner.
- `references/vcs-bitbucket.md`, `references/vcs-github.md` — the host-specific part of the PR link (Step 5); read the one that matches `profile.vcs_host`.
