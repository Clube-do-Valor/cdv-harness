---
name: cdv-finalize
description: >
  Finalize a feature branch — ephemeral `<slug>-pr.md` at repo root (lean PR format, never committed), atomic conventional commits with inferred scope, branch guard, state report, then the push and the pull request opened (or updated) through `cdv-open-pr` at wrap-up (never merges). Triggers on "finaliza essa feature", "wrap up this branch", "gera o PR description e os commits", "comita isso e prepara o PR". Do NOT use for planning unimplemented work (cdv-plan-feature), PRD/PROGRESS artifacts, or merging.
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Finalize

Wraps up a feature once the implementation is in place: generates an ephemeral PR description at the repo root, plans atomic conventional commits with scope, ensures the work is on a proper feature branch, executes the commits locally, then pushes and opens the PR at wrap-up.

## Step 0 — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-finalize.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

## Operating principles

- **Push and PR are the wrap-up, not a question.** Commits happen locally after the plan is confirmed; Step 9 pushes the feature branch (never `--force`, never `profile.default_branch` or another protected branch, only branches whose prefix is in `profile.branch_prefixes`) and hands it to `cdv-open-pr`, which opens the PR through `profile.pr_cli` — or offers to update the description of the one already open. Never through Claude in Chrome (the token fallback owned by `cdv-open-pr` is the only exception), never a merge.
- **PR_GUIDELINES.md and defining-commit-plan.md are the source of truth.** Read them from `references/` every run; do not rely on memory.
- **The PR description is for the reviewer, not an archive.** The diff shows *what* changed file by file; the description says *why*, *what requires human judgment* and *how to prove it works*. Target 40-80 lines, hard ceiling 100.
- **The PR file is ephemeral.** `<slug>-pr.md` lives at the repo root, is never committed, and is deleted once the PR carries it (`<profile.pr_cli> pr view <N>` reads it back).
- **Ground everything in the actual diff.** The PR description and the commit plan must reflect what `git diff origin/<profile.default_branch>..HEAD` actually shows, not what the conversation assumed earlier.
- **Confirm before committing.** Present the full commit plan (messages + file lists) and wait for explicit "segue"/"ok" before running any `git commit`.
- **Out of scope by design:** PRD.md, PROGRESS.md, plan-chat.md, general-plans audit, merge. This skill does PR description + commits + branch guard + push, and delegates the PR itself to `cdv-open-pr`.
- **Modo expresso exists for small fixes and hotfixes.** Triggered by "um commit só", "merge rápido", "não organiza commits", "hotfix", "expresso", or by the `cdv-debug` direct lane: ONE conventional commit with everything, the PR description **optional** (recommended, asked once, skippable for a hotfix), straight to the wrap-up (push + PR; a skipped description opens the PR with the title and the Ticket section only). Steps 2 (inspection + guards), 7 (branch guard), 8 (re-inspect before writing) and 9 (state report) still run — expresso removes ceremony, not safety.

## Workflow

### Step 1 — Gather conventions

Run in parallel:

- `Read` [PR_GUIDELINES.md](references/PR_GUIDELINES.md) — canonical PR format, section order and length contract.
- `Read` [pr-example-template.md](references/pr-example-template.md) — the structural template for the PR file.
- `Read` [defining-commit-plan.md](references/defining-commit-plan.md) — atomic commit grouping rules.
- `git log --oneline -20` — sniff the current scope style of conventional commits in this repo.
- `<profile.pr_cli> auth status` — whether Step 9 can open the PR through the host's API. On a non-zero exit, say it once now, in one line, so it is not a surprise at the end: *"Sem credencial válida para abrir o PR: no fim eu pergunto como seguir (`cdv-open-pr`, Step 0)."* It never blocks the run.
- **Finalize seed (optional):** derive the slug from the current branch name (strip the prefix listed in `profile.branch_prefixes`), then check if `STATE-<slug>.md` exists at repo root (`Bash: ls STATE-<slug>.md 2>/dev/null`). If it exists, `Read` its `## Finalize seed` section — External Links and PR seeds feed Step 4; the Draft Commit Plan seeds Step 5 — and note whether a `## Verificação` section exists (Step 2, item 3). Transitional fallback: an older branch may carry the seed in a separate `FINALIZE-<slug>.md`; read that when no STATE exists.

Do not load anything else until these are in hand.

### Step 2 — Inspect branch state

Inspect in parallel: `git status -s`, the current branch, the `origin/<profile.default_branch>..HEAD` commit list and diffs (stat + name-status), untracked files, and how far behind the default branch the branch is (`git rev-list --count HEAD..origin/<profile.default_branch>`).

Everything from here on must be grounded in this output. If `origin/<profile.default_branch>` is stale, run `git fetch origin <profile.default_branch>` once before the diff commands.

Then apply two guards on that output, **before** any plan is drafted:

1. **Behind-default-branch guard.** If the `HEAD..origin/<profile.default_branch>` count > 0, surface it and propose the rebase (or merge, per user preference) *before* building the commit plan — resolving drift after commits is more expensive. Predictable conflict hotspot: area cards (`profile.area_cards_glob`, when it is not `none`) edited by parallel branches; resolve those by uniting sections, never by picking a side wholesale.
2. **Stale-ephemerals sweep.** List ephemeral artifacts at the repo root that do not belong to the current slug (`profile.ephemeral_patterns`, e.g. `*-pr.md`, `QA-*.md`, `STATE-*.md`, `HANDOFF-*.md`, `handoff-*.md`, `decisions-*.md`, `delivery-*.md`, the review directories under `profile.pr_review_dir_prefix`, plus retired `FINALIZE-*.md` leftovers). Offer their cleanup in the Step 9 wrap-up — they are leftovers from finished branches and make "is everything committed?" ambiguous.
3. **Verifier gate (plan-feature branches).** When `STATE-<slug>.md` exists and has no `## Verificação` section with the AC table, the branch was executed by `cdv-plan-feature` and never verified: dispatch the verifier now, per `cdv-plan-feature/references/verifier.md` (`model="opus"`, announced in one line), and only continue to Step 3 on a clean verdict. Never build commits for an unverified plan-feature branch. Branches with no STATE (debug direct fix, modo expresso, work planned elsewhere) are not gated here.

**This step is re-runnable and MUST be re-run immediately before any `git commit`** (see Step 8) — a resumed session, a compacted conversation, or user edits between plan and execution all invalidate the original snapshot.

### Step 3 — Determine `<slug>` and target branch name

The `<slug>` is the kebab-case theme of the feature, derived from the conversation and validated against the diff (e.g. `invoice-sync-deletion-skip`, `export-date-filter`). Keep it short, technical, and singular.

The target branch follows the repo convention, with a prefix from `profile.branch_prefixes`: `feat/<slug>` for features, `fix/<slug>` for bug fixes, `chore/<slug>` for infra/config, `refac/<slug>` for refactors. Pick by looking at what the diff actually does, not what the user called it conversationally.

### Step 4 — Generate `<slug>-pr.md` at the repo root

The file lives at the **repo root** as `<slug>-pr.md`. It is **ephemeral**: never committed, never listed in any commit plan, deleted in Step 9 once the PR carries it. It stays untracked at the root precisely so it never lands in a commit.

This generation is **unconditional** in the normal mode: every run produces the file — Step 9 sends it as the PR description through `cdv-open-pr`. In **modo expresso** ask once, before drafting: *"Gero a descrição do PR? (recomendado; um hotfix pode pular)"* — on "pula", skip this step and Step 8.5, and the Step 9 report says `sem <slug>-pr.md por escolha`.

Mandatory section order from [PR_GUIDELINES.md](references/PR_GUIDELINES.md):

1. `## ⚡ TL;DR` — **mandatory, the very first section.** 3-4 short sentences for managers/stakeholders, ≤80 words, plain PT-BR, no technical jargon (no column/method/hook names, file paths, workflow-tool nodes, pipeline jargon, or ticket links). See "Regra do TL;DR" in PR_GUIDELINES.md.
2. `## 🔍 O que muda e por quê` — ONE short paragraph (the request/problem, prior state, closed scope) + 3-6 bullets of BEHAVIORAL changes. Never per-file — the diff shows the files.
3. `## 🎯 Decisões para o reviewer validar` — 2-4 bullets of judgment calls the diff does not explain by itself: accepted trade-offs, non-obvious business rules, deliberate side effects, assumed debt. **Highest-signal section — write it first.**
4. `## 🧪 Como testar` — exact copy-paste test commands + `**N passed (M assertions)**`, then a QA roteiro of ≤5 numbered `Passo` steps with measurable `*Esperado*` lines. Steps that write to an integration in `profile.production_writing_integrations` (or dispatch jobs that write) are tagged `[PRODUCTION-AFFECTING]` and run manually by the reviewer only.
5. `## ⚠️ Riscos e impactos` — real risks only (migrations with rollback note, external contract changes, retroactive data effects, deploy window). When none: `Nenhum risco identificado além do escopo descrito.` in one line. Sibling-ticket cross-refs live here, never above.
6. `## 🚀 Pós-deploy` — ONLY when the diff touches migrations, config, console commands, schedules or queues: the exact commands to run in production after deploy, in order, with **real parameters already filled in** (never `<opções>` placeholders) — migrations, `config:clear`/queue-worker restart when applicable, and any backfill command with its flags. Omit the section entirely when nothing manual is needed after deploy.
7. `## 🛠️ Extras (out-of-band)` — ONLY when the branch carries out-of-band maintenance/infra/skill commits (see "Extras rules" below). Omit the section entirely when absent.
8. `## 🏷️ Ticket` — only when `profile.ticket_system` is not `none`: the ticket hyperlinked as `[<KEY> — <Task name>](<ticket url>)` (`<KEY>` matches `profile.ticket_key_pattern`), always last. Write it when the ticket is known now; otherwise `cdv-open-pr` finds or creates it in Step 9 and appends the section.

Rules:
- PT-BR content with accents; English code names.
- No emojis in body content (only in the section headers, which come from the template).
- **No file inventory.** No architecture tree, no per-file bullets, no "Sem dependências novas"/"Nenhuma" filler sections. A new env var or dependency appears in "Como testar" (setup) or "Riscos e impactos" (operation) — where it has consequence.
- Commands in "Como testar" must be runnable from `{app_dir}` (or wherever the actual command lives) — no placeholders.
- **At least one external link is mandatory in the body** — inline in "O que muda e por quê" or "Riscos e impactos", never in the TL;DR. Mine the current conversation for public URLs that anchor the problem to its evidence: error-monitor issues, CRM records, workflow-tool executions, tickets, PRs and commits (the extension may list the hosts this repository uses). If the user shared screenshots, harvest the URL bar from those images. When the relevant public link is mentioned only in text, link it instead of citing the bare id ("[<KEY>](ticket-url)" not "<KEY>").
- **Do not link to private/internal team workspaces.** The evidence cited in the PR description must come from a public source the reviewer can open. When a piece of context exists only in an internal thread with no public counterpart, paraphrase it inline without a link.
- When no public external link is available at all, at minimum link the originating ticket if one exists. If even that is missing, surface the gap explicitly in the plan preview (Step 6) so the user can supply one before commit.

**Scope discipline (hard rule).** `## 🔍 O que muda e por quê` covers EXCLUSIVELY what THIS PR's diff changes. Parent tickets, sibling tickets, and related-but-separate concerns NEVER live there — they belong to `## ⚠️ Riscos e impactos` (when consumers are affected, with a relationship label like `ticket pai`, `entrega que criou o gap`, `PR anterior`) or they don't enter at all.

Before drafting "O que muda e por quê", run this self-check:

1. *Does the diff of this branch actually implement what I am describing?* If the description cites a root cause that the diff does not address, you are mixing scopes — rewrite.
2. *Would this referenced ticket explain why this PR exists without needing the current diff?* If yes, the ticket is *adjacent context*, not this PR's scope. Demote it to "Riscos e impactos" with a relationship label.
3. *Is there any sentence that, if read alone, describes a different problem than the diff fixes?* If yes, delete or move it.

**Anti-bloat gate (run after writing the draft):** execute [scripts/lint-pr-description.sh](scripts/lint-pr-description.sh) `<slug>-pr.md` — **exit 0 required** before presenting the file. It mechanically enforces: TL;DR first and ≤80 words, 40-100 lines, Decisões present with 2-4 bullets, ≤5 Passos, Riscos present, ≥1 external link, no file-inventory filler, Pós-deploy without placeholders. Two checks remain YOUR judgment (the script cannot decide them):

1. TL;DR carries no forbidden terms (column/method names, file paths, pipeline jargon — see "Regra do TL;DR").
2. "Decisões" bullets are *substantive and specific to this diff*, `## 🚀 Pós-deploy` appears **iff** the diff touches migrations/config/commands/queues, and `## 🛠️ Extras` only with real out-of-band commits.

### Extras rules (out-of-band piggyback commits)

When the branch carries small commits that are NOT part of the main feature scope but landed on this branch to avoid spawning a separate maintenance branch (skill updates, infra tweaks, template fixes, doc cleanup), list them in `## 🛠️ Extras (out-of-band)` — **one bullet per commit**: exact commit message in backticks + half a line of piggyback justification.

**When to use Extras (positive signals):**
- Skill SKILL.md / template / reference edits inside `.claude/skills/**`.
- Infra tweaks in `docker-compose*.yml`, the CI configuration (`profile.ci_config`), the environment templates (`profile.env_templates`), `composer.json`/`package.json` patch upgrades.
- Repo-level template / convention markdown updates.
- Each extra commit can be reviewed and reverted in isolation without touching the feature commits.

**When NOT to use Extras (must be a separate PR):**
- Behavior change in `{app_dir}/app/**` or `{app_dir}/resources/**` unrelated to the feature → open a separate branch.
- Schema changes (migrations) unrelated to the feature → separate branch.
- Anything that affects production code paths outside the feature's diff blast radius.
- "Just one small fix while I'm here" that introduces risk or merge surface area beyond the feature.

**Self-check before adding Extras:**
1. *Could a reviewer who only cares about the main feature skip this section and still understand the PR?* If no, the Extras content is actually scope-bleed — move into the main sections or open a separate PR.
2. *Could each Extras commit be cherry-picked onto the default branch independently of the feature commits?* If no, it is not really out-of-band — it is dependency, not extra.
3. *Would the merge of just the feature commits, without the Extras commits, still pass tests and ship value?* If no, Extras is not optional — it is a dependency and must be re-framed as part of the main scope.

**When a Finalize seed was loaded in Step 1:**
- Use its External Links to satisfy the "at least one external link" requirement — but only when they explain why THIS diff exists (not because the seed listed them).
- Map its seed sections onto the current format: Descricao + Contexto (old seeds) or "O que muda e por quê" (new seeds) → base draft for `## 🔍 O que muda e por quê`; Impactos / Breaking Changes → base draft for `## ⚠️ Riscos e impactos`; "Decisões para o reviewer validar" (when the seed has it) → base draft for that section, re-validated against the diff.
- **Strip parent-ticket framing.** When the seed inherits context from `cdv-debug` that documented a *parent ticket* (different root cause, same symptom), the seed will likely include that parent ticket's causa raiz as if it were this PR's context. The seed is a planning-time intent snapshot, not final truth — re-read every seed sentence and delete anything that describes a root cause the diff does not address.
- Do NOT copy file references blindly — every claim must still be validated against the actual diff output from Step 2.

### Step 4.5 — Area card check (before the commit plan)

Skip this part when `profile.area_cards_glob` is `none`. When the diff touches an area card (`profile.area_cards_glob`) or deletes or renames a file under `{app_dir}`, run the repository's area-card check (the extension names the command): it fails a card that is over its size limit, a `paths:` that matches no tracked file, or a path, class or method the card cites that no longer resolves. A red result is fixed in the card before the commit plan.

**The criterion is semantic, not line count.** A card line is edited only when the diff makes a fact it states false — an external contract, an agreement, an invariant, a trap. No PR is required to touch a card; a diff that changes no stated fact leaves the cards as they are. When answering "isso precisa de doc?", answer from this criterion, never from the diff size.

**How card edits are written (when they happen):** rewrite only the line that is factually wrong *now*, keep its source citation, and keep established-state voice — NEVER rollout phrasing ("após esta mudança", "agora faz X", "anteriormente"). When the diff makes a stated fact false and leaves the card untouched, ask: *"O diff muda `<fato>`, que o cartão `<card>` afirma. Corrijo a linha antes do commit plan? (default: sim)"*

**User guide (same gate).** Skip when `profile.user_guides_rule` is `none`. When the diff touches a screen page (the extension names the page glob) and none of the files that carry the user guides (the extension names them), ask the same way: *"O diff mexe em `<Page>` e nenhum guia de usuário mudou. O guia da tela (`profile.user_guides_rule`) precisa de atualização?"* On "não", the commit that carries the screen change gets a `profile.docs_skip_trailer` line (`<trailer> <motivo>`) — the pipeline's docs gate (`profile.docs_gate`) fails the PR without it, and the reason is what the reviewer reads.

On `sim` to either question, halt the commit plan until the diff includes the edit; a `não` is recorded in the wrap-up (Step 9).

When `cdv-plan-feature` produced the Finalize seed with a "Documentation skipped — rationale" block, this gate must still re-prompt — the planning-time skip might no longer apply after the actual implementation landed.

### Step 5 — Build the atomic commit plan

**Modo expresso:** the plan is one commit — `<type>(<scope>): <what the fix does>` over every changed file (ephemeral denylist still applies; `Fora do tema:` line still rendered). Present it and go to Step 6. Everything below is the normal mode.

This skill does not author frontend code; it only groups already-changed files for commits and PR text. Frontend conventions are owned by `cdv-frontend` — no UI rules are defined here.

Per [defining-commit-plan.md](references/defining-commit-plan.md), group by concern in dependency order. Typical layers:

1. **DB layer** — `{app_dir}/database/migrations/`, `{app_dir}/app/Models/`, `{app_dir}/database/factories/`.
2. **Backend layer** — `{app_dir}/app/Services/`, `{app_dir}/app/Http/Controllers/`, `{app_dir}/app/Http/Requests/`, `{app_dir}/app/Jobs/`, `{app_dir}/app/Enums/`, `{app_dir}/routes/`.
3. **Backend tests** — `{app_dir}/tests/Feature/`, `{app_dir}/tests/Unit/` (when separable from backend behavior).
4. **Frontend layer** — `profile.frontend_root` and the rest of `{app_dir}/resources/js/` (components, composables, pages, routes, translations).
5. **Frontend tests** — `*.spec.ts` alongside the source files (when present).
6. **Docs** — any `profile.docs_dirs` updates. The `<slug>-pr.md`, `QA-<slug>.md` and `STATE-<slug>.md` files are NEVER part of any commit — QA artifacts are ephemeral root-level files (the durable QA record is the PR's `## 🧪 Como testar`; the proof of execution is the interactive QA's closure table).
7. **Chore** — `composer.json`, `package.json`, the CI configuration (`profile.ci_config`), the environment templates (`profile.env_templates`), infra (only if applicable; these surface in `## 🛠️ Extras`).

Conventional commit format **with scope**:

```
<type>(<scope>): <imperative, lowercase, ≤72 chars>
```

- `<type>` ∈ `feat | fix | refac | test | docs | chore`.
- `<scope>` is inferred from the path most touched by that commit; the extension may carry the repository's scope map. Generic areas:
  - the CI configuration (`profile.ci_config`), infra → `ci`
  - `.claude/skills/**` (SKILL.md, references, scripts) → `skills`, always with type `chore` — keep the spelling the history already uses (`chore(skills): ...`)
  - `docs/**` → `docs`
- If a commit truly spans multiple areas with no dominant one (>60% of files), use no scope (`feat:`, `fix:`).
- Sniff the recent log from Step 1 for any scope spelling already in use and prefer it over a new variant.

**When a Finalize seed was loaded in Step 1:**
Use its Draft Commit Plan as the starting grouping — reconcile against `git diff --name-status origin/<profile.default_branch>..HEAD` and `git ls-files --others --exclude-standard`. Reorder, split, or merge groups as the actual diff requires. The seed is a planning-time intent snapshot, not final truth.

Rules:
- One concern per commit. Splitting is preferred over mixing.
- No `Co-Authored-By` trailer. No `🤖 Generated with Claude Code` footer.
- Render the plan inline as a numbered list with each commit's message on top and a bullet list of files under it, using `path` (no markdown link) so paste-into-terminal is clean.
- **Ephemeral denylist (hard rule).** Root-level files matching `profile.ephemeral_patterns` (e.g. `*-pr.md`, `QA-*.md`, `STATE-*.md`, `HANDOFF-*.md`, `handoff-*.md`, `decisions-*.md`, `delivery-*.md`), the review directories under `profile.pr_review_dir_prefix` (and retired `FINALIZE-*.md`) NEVER appear in any commit. These patterns live in the repo `.gitignore`; if one is missing there, add it as part of the chore commit instead of committing the artifact.
- **Off-theme files line (mandatory in the plan).** After the numbered commits, render `Fora do tema:` listing every changed/untracked file the slug does not cover, each with the proposed handling — `chore:` isolado, excluir do PR, or pertence à branch-par. When empty, render `Fora do tema: nenhum.` The user approves this line together with the plan.

### Step 6 — Confirm the plan

Present:

1. The target branch (current vs. new).
2. The commit plan from Step 5 in order.
3. A 1-line dry-run estimate (e.g. "8 commits, 31 files").
4. One line saying what follows the commits: push of `<branch>` and the PR opened (or updated) through `cdv-open-pr`, with the ticket it will link when already known.

Then ask the user explicitly: *"Pode seguir?"* / *"Confirma para executar os commits?"*. Wait for an affirmative reply ("segue", "ok", "vai", "pode") before any `git` write operation. If the user asks for changes, revise and re-confirm.

### Step 7 — Ensure feature branch

Before the first commit, run `git branch --show-current`:

- If the result starts with one of the prefixes in `profile.branch_prefixes` (`feat/`, `fix/`, `chore/`, `refac/`) → use it as-is.
- Otherwise (current is `profile.default_branch`, `develop`, or any protected/default branch) → run `scripts/branch-from-master.sh <type>/<slug>` first (it branches from `origin/<profile.default_branch>`).

This step is unconditional regardless of whether the user asked for a new branch. Feature work in this repo always lives on a feature branch.

**Stacked branches — verify what actually landed.** When the new branch stacks on a parent feature branch instead of `origin/<profile.default_branch>`, `git fetch origin` first, then check the parent both ways before branching:

- `git merge-base --is-ancestor <parent> origin/<profile.default_branch>` false while `origin/<profile.default_branch>` contains a merge of the parent's name → the parent was merged at an **earlier** commit than the local tip. `git log --oneline origin/<profile.default_branch>..<parent>` lists exactly what was left behind.
- Never read a stale `origin/<profile.default_branch>` as evidence: a "not merged" answer before a fetch says nothing.

Commits the parent left behind are not a detail to route around — they are unshipped work, and stacking on top buries them. Surface the list and let the user choose the base (ship them first as their own PR, fold them in, or drop them) before the first commit of the new branch.

### Step 8 — Execute commits

**Re-inspect before writing (hard rule).** Immediately before the first `git commit`, re-run the Step 2 commands and compare with the snapshot the plan was built on:

- Working tree or HEAD changed since the plan was confirmed → discard the plan, rebuild from Step 5, re-confirm.
- `git status -s` empty AND commits already ahead of `origin/<profile.default_branch>` → the commits were already made (earlier run, other session); do NOT commit again — announce it and skip to Step 8.5.

Execute one commit at a time, in the order from the confirmed plan, using HEREDOC to preserve newlines and avoid shell interpretation:

```
git add <files>
git commit -m "$(cat <<'EOF'
<type>(<scope>): <message>
EOF
)"
```

After each commit, verify with `git log --oneline -1 --stat`. If anything looks off (wrong files, wrong scope, typo), stop and ask before continuing.

No `git push` during this step — the push lives in Step 9. Never `git tag`. Never open the host's web UI.

### Step 8.5 — Refresh `<slug>-pr.md` against the final tree (mandatory)

After the last commit, regenerate the `<slug>-pr.md` body against `git log --oneline origin/<profile.default_branch>..HEAD` and `git diff --stat origin/<profile.default_branch>..HEAD` so the description always reflects the **final** commit tree — "is it up-to-date?" must never be a possible question. Re-run the anti-bloat self-check on the refreshed draft. Record (for the Step 9 report, not inside the file) the SHA of the last commit the description was generated against.

### Step 9 — Wrap-up

**Push, then the PR — no question.** Confirming the commit plan in Step 6 is the authorization for both.

1. `git push -u origin <branch>` — feature branches only (a prefix from `profile.branch_prefixes`); on `profile.default_branch`/protected, refuse and point to Step 7. A rejected push (remote has commits the local branch lacks) stops here with the `⚠` bullet below; never `--force`.
2. Invoke `cdv-open-pr` with `<slug>-pr.md` (it opens the PR through `profile.pr_cli`). With no open PR for the branch it creates one (ticket, title, reviewers) and deletes the file; with an open PR it offers to update the description only when this run added commits — a re-run after QA fixes lands there.

Then print the **final state report**: ONE status line with fixed clauses in fixed order, then one `⚠` bullet per pending action or anomaly. Every clause is still a mandatory check — a clause may only be written after its command ran; any check that is not "ok" leaves the status line and becomes an expanded `⚠` bullet. Never omit a clause silently.

Status line (fixed clause order): **Estado final** — `<N>` commits nesta rodada; árvore limpa; `origin/<branch>` em dia; **PR** `#<N>` aberto / atualizado / já em dia, with its link; **Pós-deploy:** `nenhum comando` or the ordered production commands copied verbatim from the PR's `## 🚀 Pós-deploy` section (migrations, `config:clear`, worker restart, backfill with its real flags). The clause is mandatory in both states.

The remote clause comes from `git rev-list --count origin/<branch>..HEAD` after the push — never report "em dia" without having run it.

`⚠` bullets (only when applicable, with the concrete follow-up inline):
- Residual `git status -s` entries beyond the slug's known ephemerals — name each file (unfinished business).
- Guide or card skip recorded in Step 4.5.
- Stale ephemerals found in Step 2, with the cleanup offer.
- Push rejected or `origin/<branch>` still behind the local branch — name the count and the consequence: an open PR shows the **old** tree, so approving it merges the pre-commit code and orphans the local commits.
- Front-end change without a visual QA yet (reported by `cdv-open-pr`).
- PR opened through the token fallback of `cdv-open-pr` (Claude in Chrome, Bitbucket only) because there was no credential — with the one-line recommendation to run `<profile.pr_cli> auth login` before the next PR.

**Interactive-QA offer + handoff block.** When the branch has a QA roteiro (`QA-<slug>.md` at the repo root or the `## 🧪 Como testar` section) and the user has not QA'd yet, offer once: *"Quer rodar o QA interativo agora, aqui ou numa sessão nova?"*. QA in a **fresh session** is the norm when this session grew large (the fix found in QA comes out better with less context) — so print the handoff block right there, in the chat, per `cdv-handoff` (its template lives in that skill): what the branch does in three lines, where the code is (worktree or main checkout) with the exact `git rev-list --count origin/<branch>..HEAD` result, the environment trap when it is a worktree (`profile.worktree_runner`, when it is not `none`), the roteiro path, the named real fixtures, the `[PRODUCTION-AFFECTING]` steps, the "não faça" lines (no branch switch over another session's WIP, no `git stash`), and the test baseline. No file: the block points at the ephemerals that already exist. In modo expresso the block is three lines (branch, what changed, how to see it). QA fix commits loop back into a new finalize pass, which updates the open PR.

When the QA already ran, ask (AskUserQuestion): *"QA feito — posso apagar o `QA-<slug>.md` e o `STATE-<slug>.md`?"* with options **apagar** / **manter por enquanto**. On "manter", remind that they must never be committed.

Beyond the push, the PR through `cdv-open-pr` and the optional `rm`, no further git writes; never merge.

## Examples

### Example 1 — Standard wrap-up after implementation

User says: *"finaliza essa feature, branch atual é `fix/invoice-orphan-cleanup`, já implementei tudo."*

Actions:
1. Read conventions + template + recent log (Step 1).
2. Inspect diff (Step 2).
3. Slug = `invoice-orphan-cleanup`, branch already `fix/...` so no rename needed.
4. Generate `invoice-orphan-cleanup-pr.md` at repo root (lean format, anti-bloat check passed).
5. Plan: e.g. (1) `feat(invoices): add InvoiceNotFound enum case`, (2) `fix(invoices): silently skip the lookup when no invoice matches`, (3) `test(invoices): cover skip path`.
6. Show plan, ask QA-directory choice, then "Pode seguir?".
7. Branch already feature → skip rename.
8. Execute commits (re-inspection passed — tree unchanged since the plan).
9. Refresh the PR file (Step 8.5), push, open the PR through `cdv-open-pr` (ticket found, `invoice-orphan-cleanup-pr.md` deleted once the PR carries it), then the final state report with the PR link.

### Example 2 — Wrap-up but user is on the default branch

User says: *"gera o PR e os commits dessa feature de export-retry"*. `git branch --show-current` returns the default branch.

Actions:
1-5 as above.
6. Plan presented. User confirms.
7. Step 7 triggers `scripts/branch-from-master.sh feat/export-retry-after-timeout` (slug from diff theme).
8. Execute commits on the new branch.
9. Push + PR + final state report.

### Example 3 — Mid-flight correction

User says "finaliza" and confirms the plan. After commit 2 of 5, you notice commit 3 should have been split into two. Stop. Ask: *"Encontrei uma mistura no commit 3 (mexe em backend service e em uma migration). Divido em 3a (migration) + 3b (service) e sigo?"* Wait for confirmation before continuing. Never silently rewrite the plan mid-flight.

## Troubleshooting

### `origin/<profile.default_branch>` shows as ahead but `git log origin/<profile.default_branch>..HEAD` is empty
Cause: stale local ref.
Solution: `git fetch origin <profile.default_branch>` then retry the diff commands.

### Branch name conflicts (already exists locally)
Cause: previous `branch-from-master.sh` run with the same slug, or the user already created it manually.
Solution: stop and ask the user whether to switch to the existing branch, append a suffix (`-v2`), or rename the slug.

### Diff includes files outside the feature scope (e.g. accidentally staged `vendor/`, `node_modules/`, `.env`)
Cause: stray `git add -A`.
Solution: stop before generating the commit plan. Surface the suspicious files, ask the user to confirm exclusion, and unstage them via `git restore --staged <file>` (read-only here means the user runs the unstage, not the skill).

### User asks to push or to open the PR before the wrap-up
Both are Step 9. Run them on the feature branch (`git push -u origin <branch>`, then `cdv-open-pr`); refuse only if the current branch is `profile.default_branch`/protected. Never through Claude in Chrome.

### `<profile.pr_cli> auth status` says there is no valid credential
Not a blocker: the push happens, and `cdv-open-pr` Step 0 asks whether to log in now (`<profile.pr_cli> auth login`, about 2 minutes) or, on Bitbucket, to open this PR through Claude in Chrome.

### "O que muda e por quê" is describing the parent ticket's root cause instead of this PR's diff
Cause: the Finalize seed (from `cdv-plan-feature` upstream) inherited context from `cdv-debug`, which documented a *parent ticket* with a different root cause but a shared symptom. The seed pulled the parent's causa raiz forward.
Solution: refocus on what THIS branch's diff actually changes. Move the parent ticket to "Riscos e impactos" with an explicit relationship label (e.g., `ticket pai — causa raiz distinta, mesmo sintoma`). Delete every sentence that describes the parent's root cause; keep only sentences that describe the edge case this diff resolves. Re-run the 3-question scope-discipline self-check from Step 4 before re-submitting.

### The draft PR description exceeds 100 lines
Cause: file-inventory content, per-file bullets, or filler sections leaked in from the old format.
Solution: cut — there is no annex to move detail to. The diff shows the files; keep only what requires judgment. Re-run the anti-bloat self-check from Step 4.

### Recent commits in `git log` use a scope variant you weren't sure about
Cause: scope drift between contributors.
Solution: prefer the spelling that appears most recently in `profile.default_branch`. If ambiguous, surface the two variants in the plan and ask the user to pick before committing.

## Tools assumed available

`Read`, `Bash` (git + the bundled script), `Glob`, `AskUserQuestion`. No MCP requirement.

## Bundled scripts

- [scripts/branch-from-master.sh](scripts/branch-from-master.sh) — fetch `origin/<profile.default_branch>` and check out a new branch from it. Aborts if the branch already exists. Used in Step 7 when the current branch is not a feature branch.
- [scripts/lint-pr-description.sh](scripts/lint-pr-description.sh) — mechanical anti-bloat gate for `<slug>-pr.md`. Exit 0 required before presenting (Step 4) and after the Step 8.5 refresh.
