---
name: cdv-plan-feature
description: >
  Plan a feature (Laravel + Inertia + Vue) as a multi-phase plan grounded in the repo docs, then execute the approved phases with an independent verifier at the end. Sizes the work in two tiers first — pequeno (≤ ~3 files, no migration, no new screen) runs inline on the main checkout; grande runs in a worktree with parallel executors only on disjoint code. Triggers on "planeja essa feature", "preciso de um plano pra X", "implementa essa feature", a `decisions.md` ledger from `cdv-grilling`, or a settled spec/definition doc ("spec is settled, execute" — resolved-spec mode skips the Q&A). Do NOT use for one-off bug fixes (`cdv-debug`), single-file refactors, wrap-up of implemented work (`cdv-finalize`), or pure infra/CI tasks.
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Plan Feature

Codifies the recurring planning workflow: read repo conventions and the area cards, dispatch Explore for codebase facts, ask scoped questions with UI-first ordering, produce a multi-phase plan, and execute the approved phases (Step 6). Composes upstream with `cdv-grilling` (decisions-ledger input) and downstream with `cdv-finalize` (wrap-up).

## Operating principles

- **No long-lived orchestration state.** The plan is rendered inline in the chat. No plan.md, no plan-chat.md, no PRD.md, no PROGRESS.md. This skill writes exactly **two** ephemeral root files, both gitignored, never committed, deleted at the finalize wrap-up: `QA-<slug>.md` (Step 4c — the roteiro `cdv-interactive-qa` executes) and `STATE-<slug>.md` (Step 6 — the approved plan verbatim, the phase status, and the `## Finalize seed` that `cdv-finalize` reads). There is no dry-run script and no separate FINALIZE seed file.
- **Read conventions every run.** Never plan from memory. `profile.instructions_file` is already in context; read the path rules in `.claude/rules/` that cover the areas the plan touches — a rule loads on its own only when a matching file is read, and a plan names files before reading them. Area cards (`profile.area_cards_glob`) are rules too.
- **Ground in real diff state.** Phases must reflect the actual codebase layout discovered by Explore, not generic Laravel/Vue scaffolding.
- **UI/visual placement first.** Whenever the feature touches a visible UI element, the placement question is asked in Round 2 (immediately after bundling/scope), never after the plan is drafted.
- **Backend questions stay architectural.** Async vs sync, job vs command, where to persist (DB / cache / config), which system owns the data. Do NOT ask which method maps to which service call — that is an executor-level decision.
- **One question per turn.** No batches. Build on the previous answer.
- **Stop when scope is unambiguous.** Leaves like operator order, exact label text, debounce ms are decided autonomously during planning. **Anything the end user perceives is trunk, not leaf**: TTL/refresh frequency, throttle values, page sizes, limits, and visible defaults are user decisions — never fixed autonomously.
- **Read-only until approval (hard rule).** Zero writes — code, migrations, seeders, docs, **and probe files anywhere, including the container's `/tmp`** — before the user explicitly approves the plan. Investigation (Steps 1–5) uses file reads, grep and single-line read-only REPL queries (`profile.cmd_tinker`); a probe that needs more than one line is asked for first ("preciso escrever um probe descartável em /tmp do container, ok?"). A probe written during planning looks like implementation to the user — the rule covers what looks like code, not only what ships. If anything was touched before approval, list it and offer `git restore`.
- **A question is a request for analysis, not action.** "Quais/por quê/deveria/é possível/what would be needed" → deliver the assessment and stop. Requests to change local state (grant a permission, create a test user, toggle a flag) resolve via a read-only-safe REPL query (`profile.cmd_tinker`) or a demo seeder — never by editing application code.
- **Evidence-or-hypothesis.** Every claim about current behavior, every number and every "X calls Y" carries its evidence inline (`path:line`, a read-only REPL command, a table/column read) or is explicitly marked as hypothesis. Exhaust local reads before proposing "validar em staging" or "confirmar com <dev>" — if genuinely blocked, name the concrete blocker (data only exists in prod, API doesn't expose the field), not the uncertainty.

## When to use

- The user pastes a feature description with multiple steps spanning DB/backend/frontend/tests.
- The user says "planeja essa feature", "preciso de um plano pra X", "plano multi-fase para Y", "implementa <feature>".
- A `decisions.md` ledger written by `cdv-grilling` (or an equivalent settled doc) arrives as the entry context — use it verbatim, do not re-interview.
- A general module change touches multiple `<profile.frontend_root>/<Module>/*` directories at once.

## When NOT to use

- One-off bug fixes → use `cdv-debug` or just edit.
- Single-file refactors with no behavior change → just edit.
- Wrap-up of an already-implemented feature with docs + commits → use `cdv-finalize`.
- Pure infra/CI tasks (no app code) → just edit.
- Work in a repository without a cdv-harness profile (the profile step below stops).
- The brief is so vague that interaction model and scope are still open → run `cdv-grilling` first.

## Workflow

### Before anything — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-plan-feature.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

### Step 0 — Size the work, then place it (always)

**Complexity tier (provisional from the brief, confirmed in Step 4).** Two tiers decide where the work runs and how much machinery it gets. The tier is stated in the plan's Resumo and never changes silently after approval.

| | **PEQUENO** | **GRANDE** |
|---|---|---|
| Criterion | up to ~3 files, no migration, no new screen (a new field on an existing screen still counts as pequeno) | anything else |
| Investigation (Step 3) | inline: reads, grep, single-line read-only REPL queries | Explore subagent(s) when the survey spans many files or areas |
| Execution (Step 6) | inline, no executor subagents | parallel executors only for phases touching disjoint code |
| Where it runs | the **main checkout**, after `profile.bring_branch_script --check <branch>` confirmed no other session's WIP sits there (no script: `git status --porcelain` is the guard) | an isolated **worktree** (`EnterWorktree` or `git worktree add`), gates through `profile.worktree_runner` (`none`: the worktree runs its own gates) per [references/worktree-safe-commands.md](references/worktree-safe-commands.md) |
| Verifier (Step 6.5) | fresh-context subagent, `model="opus"`, announced, dispatched in the turn the last phase closes; `verificador: light` by default | same, plus `verificador: standard` (fault injection) when the plan says so |
| QA interativo | optional (offered, not assumed) | offered at the finalize wrap-up |

Why two tiers: subagents earn their cost on large decomposable work and cost turns on small work. Worktree isolation is session-level and pays for itself only when another session may touch the same checkout for long; a three-file fix on the main checkout with the WIP guard is safer than a worktree that cannot run its own gates.

**Model rule (every subagent, both tiers).** Every `Agent`/`Task` call names `model` explicitly — inheritance silently runs subagents on the wrong model. The table: `Explore`, executors and any mining/analysis agent → `sonnet`; the verifier → `opus`; Fable never in a subagent. A call without `model=` is a defect in the brief, not a default.

**Branch.** Confirm the current branch is a feature branch (a prefix from `profile.branch_prefixes`) created from a fresh `origin/<profile.default_branch>`. Run `git branch --show-current`:

- If on `profile.default_branch` or any protected branch: slugify the feature title and run `.claude/skills/cdv-finalize/scripts/branch-from-master.sh feat/<slug>` before the first plan output.
- If on an existing matching feature branch: continue.
- If on an existing feature branch whose name does NOT match the new feature: ask whether to switch.
- **Pequeno** on the main checkout: if `git status --porcelain` shows tracked modifications you did not make, stop and ask — they are another session's work. Never `git stash` (shared stack).

The branch guard delegates to the script bundled with `cdv-finalize`. Do not reimplement git logic here.

### Step 1 — Load base context (always)

Read in parallel:

- The path rules in `.claude/rules/` that cover the areas the feature touches (see **Read conventions every run** above; `profile.instructions_file` is already loaded).
- [references/naming-language.md](references/naming-language.md) — the one-language naming rule (`profile.language_code`) and the four cases where `profile.language_ui` is allowed. Every file, symbol, column and route named in the plan is bound by it.
- `ls <profile.adr_dir>` — scan the ADR titles (skip when `none`) and read every ADR whose title touches the feature area. **Conform-or-supersede rule:** the plan either conforms to each active relevant ADR, or explicitly proposes superseding it (a new ADR, marking the old one superseded). Silently contradicting an active ADR is not an option — the reviewer (`cdv-pr-review`) checks against them downstream.

These are mandatory. Never plan a feature without them in context.

**ADR gate (hard rule):** when the feature changes the source of truth of a dataset, a contract with an external system, or the schema semantics of an existing table, the plan's Phase 0 is writing the ADR into `profile.adr_dir` — never a doc under `profile.research_dir` for a decision already taken. Cite the ADR's absolute path in the plan (when `profile.adr_dir` lives outside `profile.app_dir`, name it explicitly — it is invisible in editor workspaces opened on the app directory).

**Module gate:** when the repository has a module convention (the extension names it) and the feature is greenfield with its own ubiquitous language and a small, nameable integration surface, surface the opt-in question — does it get born as a backend module? — BEFORE drafting the plan (the answer changes every path in it). Criteria: [references/module-opt-in.md](references/module-opt-in.md); layout and port/event wiring: the module rule the extension names; `profile.module_design_skill` feeds the judgment when the call is not obvious. Existing code is never retrofitted into a module as a side effect of a feature.

### Step 2 — Area cards

An area card (`profile.area_cards_glob`; skip this step when `none`) is a path rule: it states what the code cannot — external contracts, agreements with other teams, invariants with the test that proves each, traps already paid for — and loads by itself when a file of its area is read. A plan names files before reading them, so read, as in Step 1, the cards whose `paths:` cover the areas the plan names (list the glob). The code stays the source of truth. The plan edits a card only when it changes a fact the card states.

### Step 3 — Gather codebase facts (inline in the small tier; Explore in the large one)

Before asking the user about anything that can be looked up, look it up. **Pequeno tier:** read the files, grep, run single-line read-only REPL queries — no subagent; the survey is a handful of files and a subagent costs more turns than it saves. **Grande tier**, or whenever the survey spans many files or several areas: spawn an isolated subagent, on the cheap model — exploration is bounded, read-only work:

```
Task(
  subagent_type="Explore",
  model="sonnet",
  description="Survey codebase for <area>",
  prompt="Map the <feature area> in <repository root>:
    (1) main page/component files under <profile.app_dir>/<profile.frontend_root> (paths + 1-line purpose);
    (2) backend controller(s)/service(s)/model(s)/enum(s) under <profile.app_dir>/app/;
    (3) DB schema for tables the feature mentions (column list with types);
    (4) existing test files under <profile.app_dir>/tests/ that touch this area;
    (5) any sibling feature with similar UX or domain to reference;
    (6) any external integration touched and its client file path.
    Return a concise file map (paths + 1-line purpose). Skip irrelevant scaffolding."
)
```

If the feature touches multiple distinct areas, dispatch multiple Explore agents in parallel. Use the returned map for INFORMED planning. Never ask the user "where is X implemented?" — Explore first.

### Step 3.5 — Production-impact analysis (MANDATORY before drafting the plan)

Load [references/production-safety.md](references/production-safety.md) — the full rules for Steps 3.5, 3.6 and 3.7. Non-negotiable summary:

- **3.5**: classify every touched code path as **PRODUCTION-AFFECTING** (writes/mutates/triggers side-effects on systems or tables shared with prod, directly or transitively) or **DEV-SAFE** (reading is always safe — the boundary is state modification). The classification table goes into the plan output, right before the QA Plan phase. PRODUCTION-AFFECTING paths are tested ONLY via Pest with fakes.
- **3.6 (HARD STOP)**: never run a command mapping to a PRODUCTION-AFFECTING path during implementation — main session, every executor subagent, every verification pass. The forbidden/allowed Bash pattern lists live in the reference. "Just to confirm it's wired" → write the `Http::fake()` test instead.
- **3.7**: real execution of PRODUCTION-AFFECTING paths happens only in the user-executed QA manual, never by the agent, with the manual-only header note.

### Steps 3.6 / 3.7 — see [references/production-safety.md](references/production-safety.md)

### Step 4 — Draft the multi-phase plan inline

Render the plan inline using [references/plan-skeleton.md](references/plan-skeleton.md) as the structure. Phases reflect the repository's layering:

1. **Migrations + Models + Factories** — additive by default (no `dropColumn`, `dropForeign`, or `change` on existing tables unless the user explicitly approves). Factories for any new model under test.
2. **Services + Enums + Jobs** — business logic. Services are stateless; jobs delegate to services. New enums under `<profile.app_dir>/app/Enums/<Module>/`.
3. **Controllers + Requests + Routes** — thin controllers, FormRequest for validation, Inertia response shaping. Routes reach the frontend as `profile.frontend_routes` says — never invent a route-generation step that the profile does not name.
4. **Frontend** — new pages, components, forms, and charts. Executed like any other phase (Step 6); the one asymmetry is which skill is in scope. **In the grande tier, load `cdv-frontend`** — the single source of truth for every frontend convention (file placement, component library, charts, template permissions, script style, product text; the repository's own are in `profile.frontend_rules` and the extension); it also chains `profile.design_skill`. Do NOT restate its rules here. **In the pequeno tier, do not load it**: follow the neighbouring file as the pattern, which is where consistency actually comes from for a twin component, a prop added to an existing surface, or a copy change — reading the whole chain costs more than the diff. Reflect only the feature-specific decisions (which pages/components, which module) in the plan.
5. **Tests** — `profile.backend_test_framework` (Feature + Unit) for backend, `profile.cmd_test_frontend` for frontend (skip when none). Happy path + 2-3 sad paths. **If the feature touches a flow already in production, include explicit regression tests per the repository's tests rule (the extension names it)** (contract change, guard semantics, ordering invariant, schema affecting existing rows, enum mapping, job dispatch behavior).

   **Mock fidelity (mandatory).** When a mocked method's return shape originates from a macro/external service, the mock MUST return that **exact** shape — call the real `->toArray()` or mirror its keys, including any keys the code under test must strip (so the strip is actually exercised). A mock that returns the wrong *type* passes green while production 500s; tests + static analysis + review will not catch it because the code is internally self-consistent. Cross-check the real shape once with a read-only keys-only REPL dump (`profile.cmd_tinker`, `array_keys($svc->method()->first())`).

   > ❌ **BAD** (the mock returns objects where the real method returns arrays): a service method was mocked to return a collection of **objects** — tests passed; the browser 500'd because the real method returns a collection of `toArray()` **arrays**, and the controller used object access (`$c->id`).
   > ✅ **GOOD**: the mock returns the real `toArray()` shape, sensitive keys included, so the whitelist assertion is genuine and array access is exercised.
6. **QA Plan** — deterministic numbered steps with exact commands (prefixed with `profile.cmd_container_exec` when `profile.commands_run_on` is `container`) the user runs manually. Each step carries a mutation label (Step 4c). Every PRODUCTION-AFFECTING path from Step 3.5 maps to exactly one `[PRODUCTION-AFFECTING]` step here, flagged for manual execution only — the agent never runs them itself.

   **Dados para QA (mandatory sub-section of the QA plan).** State how the QA database (`profile.qa_env`) gets the states the roteiro exercises: (a) it already has them (cite the pre-queried fixture ids), (b) an idempotent demo seeder following `profile.qa_fixture_pattern` — docblock declaring local-only scope, self-wiping re-runs, and **which UI actions will NOT work on fixtures and why** (e.g. reprocessing calls the real external system), or (c) a real fill with an explicit `--limit` justified by the scenario — never a full-population fill on the first run. Execution of the roteiro itself can be driven by `cdv-interactive-qa` after implementation.
7. **Area card + user guide** — the plan edits an area card (`profile.area_cards_glob`) only when it changes a fact the card states: the line that became false is rewritten, a new external contract or invariant gets its line with its source. No PR is required to touch a card.

   **User guide (same phase, default-on).** When the plan adds a screen or changes what one shows or does (a page under `profile.frontend_root`), the phase also writes or updates its guide per `profile.user_guides_rule` (skip when `none`): the guide file with the required sections and whatever registers it (the extension lists them). A new screen never lands as `pending`.

   Default: include the guide when a screen changes. Opt-out requires explicit user approval and is logged in the `## Finalize seed` section of `STATE-<slug>.md` under "Documentation skipped — rationale".

Smaller phases can merge; larger phases can split. Don't pad to fit a count.

**Naming gate (hard rule, applies to every phase).** Every file, class, enum case, method, variable, column, index, component, prop, type and route path the plan names must be in `profile.language_code`, per [references/naming-language.md](references/naming-language.md). No mixed-language identifiers, no symbol in the UI language because the business says the word in it. Before rendering the plan, scan the names you just wrote and check each string in the UI language (`profile.language_ui`) against the four allowed cases (user-facing copy, already-published URL path, external contract field inside a string literal, already-persisted data value). If the concept already has an English name in the codebase, reuse that exact name — do not coin a synonym.

**Precedent gate (hard rule, applies to every phase).** Every technical value and pattern the plan fixes cites its in-repo precedent as `path:line`, or is explicitly marked `novo padrão — decisão do usuário` and surfaces as a question before the plan closes. This covers magic numbers (rate limits, TTLs, timeouts, `tries`, chunk sizes, queue names), architectural choices (job vs command — recurring/scheduled work follows the repository's precedent, which the extension may fix; a command for scheduled work must declare the conflict), schema shape (extend the existing table first — a mirror/profile table needs a stated justification like distinct cardinality or lifecycle; the extension may fix the default foreign key of new tables), and column precision for mirror tables (copy the upstream DDL/payload type **verbatim**, citing it; intentional divergence needs a written reason). New columns declare their concrete consumer (screen, endpoint, job) — a column with no consumer does not enter the plan. Migrations created on this same unmerged branch are edited in place or recreated — never altered by a follow-up migration.

#### Step 4c — Emit the QA guide to disk

After rendering the inline plan, write **one** file at the **repo root**: `QA-<slug>.md`. Together with `STATE-<slug>.md` (Step 6) it is the only file this skill writes.

It is **ephemeral** (gitignored: `/QA-*.md`, one of `profile.ephemeral_patterns`): it exists to drive `cdv-interactive-qa`, is never committed, and is deleted at the finalize wrap-up. The durable reviewer-facing record is the PR's `## 🧪 Como testar`; the proof of execution is the interactive QA's closure table. The mechanical gates (pending migrations, backend formatter, static analysis, backend tests — the `profile.cmd_*` commands) are re-run by the verifier (Step 6.5) and by `cdv-finalize`; there is no separate dry-run script.

**QA guide** (`QA-<slug>.md`):
1. Load [references/qa-guide-template.md](references/qa-guide-template.md) as the structural scaffold.
2. Substitute `{{SLUG}}`, `{{FEATURE_TITLE}}`, `{{FEATURE_SUMMARY}}`, `{{FILTER}}` mechanically, and the command tokens from the profile: `{{EXEC}}` = `profile.cmd_container_exec` (empty, with no leftover space, when `profile.commands_run_on` is `host`), `{{TEST}}` = `profile.cmd_test_backend`, `{{TINKER}}` = `profile.cmd_tinker`, `{{FORMAT}}` = `profile.cmd_format_backend`, `{{ANALYSE}}` = `profile.cmd_static_analysis`.
3. Compose the feature-specific sections per [references/qa-authoring.md](references/qa-authoring.md) — **load it now, in full**. Non-negotiable summary of what it enforces: real-data-derived `**Expected:**` values (richest real fixture, pre-queried ids + counts — abstract expectations are unfalsifiable); zero placeholder ids; local host only, never the production domain; owner-scoped/external screens get their fixture derived from the feature's ACTUAL scope source with the guard reproduced end-to-end (the extension lists the repository's scope traps); gitignored scratch oracle for external/PII values; `profile.cmd_test_backend` only; single-line read-only REPL queries only; mutation labels on every heading with the legend in the preamble; PRODUCTION-AFFECTING steps manual-only; Inertia page-availability check (bundle the page when the branch lacks it, and verify it RENDERS).
4. Write to `QA-<slug>.md` at the repo root.
5. **Lint gate (mandatory):** run [scripts/lint-qa-guide.sh](scripts/lint-qa-guide.sh) on the written file — **exit 0 required**. It catches placeholder ids, hosts other than the local one, heredoc tinker, headings without mutation labels, the missing manual-only header, and a test runner other than `profile.cmd_test_backend`. Fix and re-run until clean.

The `<slug>` is the feature branch suffix (e.g. `feat/invoice-export-db` → `invoice-export-db`). The `<FILTER>` is a backend test name filter (`profile.cmd_test_backend_filter`) matching the feature's test classes (e.g. `InvoiceExport`).

If the user requests plan adjustments, regenerate the guide with the updated content.

### Step 5 — Ask scoped questions (one at a time)

**Resolved-spec mode (skip the Q&A entirely).** When the brief points at a settled spec — a definition doc (`<profile.research_dir>/**/definition.md` or equivalent), a `decisions.md` ledger from `cdv-grilling`, or the user states the spec is closed — do NOT re-litigate decisions: read the source of truth first, skip this step, and go straight to Step 4. Any divergence discovered between the spec and the codebase becomes a `Divergência vs <doc>` line in the plan (with the evidence), never a question. Only a divergence that makes a phase impossible warrants interrupting.

Otherwise, load [references/question-rounds.md](references/question-rounds.md) for the full taxonomy. The short version:

- **Codebase fact** (where/how is X done) → resolve via Explore, do NOT ask.
- **UI/visual placement** (where on the page, visual weight, which existing pattern to follow) → ask user **before any backend architecture question** when the feature touches a visible UI element. Failure to ask this early leads to implementing the wrong visual language and having to redesign after the fact.
- **User preference** (a/b option, default behavior) → use `AskUserQuestion` with concrete options + a recommended default.
- **Scope decision** (include feature Y? handle edge case Z?) → ask user.
- **Hidden constraint** (compliance, deadline, downstream consumer) → ask user.

**Question ordering rule** (hard rule): UI/visual placement comes in Round 2, never skipped or deferred. Backend questions stay architectural — async vs sync, job vs command, where to persist, who owns the data. Do NOT ask implementation-level details.

One question per turn. Build on the previous answer. Stop when scope is unambiguous.

### Step 6 — Execute the plan in phases

After the user signals approval on the plan ("ok", "ready", "vamos", "segue"), execute the approved phases in order, in this session.

**Execution checkpoint (`STATE-<slug>.md`, repo root, ephemeral).** On plan approval, before the first phase, write the checkpoint file with: the approved plan **verbatim** (phases, the numbered ACs, the Restrições block), a phase-status list (`pending`), and a `## Finalize seed` section — slug, branch and conventional-commit scope; every public URL mined from the conversation (ticket, record of an external system, workflow execution, error-tracker issue); the PR seeds in PT-BR ("O que muda e por quê", "Decisões para o reviewer validar", "Riscos e impactos", mirroring `cdv-finalize/references/PR_GUIDELINES.md`); and a draft commit plan grouped by concern in dependency order (DB → Backend → Tests → Frontend → Docs → Chore). Write the seed now, before any compaction: `cdv-finalize` reads it in its Step 1 and cannot derive business motivation, judgment calls or external links from the diff. Update the file **only at phase transitions** — a closed phase gets its status, test count and commit hash; the verifier appends its AC table under `## Verificação`; nothing else is ever rewritten (a checkpoint updated at deterministic points cannot drift from the chat). Gitignored (`/STATE-*.md`), never committed, deleted at the finalize wrap-up.

- **Resume rule.** Entering Step 6 with a `STATE-<slug>.md` already present for this branch (resumed session, compacted conversation): resume from the checkpoint — phases marked closed are NOT re-executed; the plan, ACs and Restrições are read from the file, not reconstructed from chat memory.

- **Autonomy between phases is the default.** Move from one phase to the next without asking for approval. Stop only when a decision surfaces that the plan does not cover — ask exactly that question, then continue.
- **Pequeno tier runs inline.** No executor subagents, no Explore: the session that planned implements, phase by phase, on the main checkout. This is the common case for fixes and small features.
- **Grande tier may parallelize via subagents.** When two phases touch disjoint code, dispatch them as parallel executor subagents with `model="sonnet"` (model rule, Step 0) — the orchestrating session keeps decomposition and judgment on the strong model; a well-briefed executor does bounded work. A single phase is never split across agents that would touch the same files — merge conflicts cost more than parallelism saves. Read-only research goes to `Explore`, never to an executor. When the user says "inline" or "sem subagente", that wins over the tier.
- **Frontend is not a dispatch category.** A frontend phase is executed exactly like a backend one — same tier, same parallelization test, same gates. There is no rule that sends UI work to a subagent, and "backend vs frontend" is not an example of disjoint phases. The only thing frontend changes is **which skill is in scope** (Phase 4 below), never who does the work.
- **Delegation is about context, not size.** Before dispatching anything, name the file the executor will follow as its pattern. If that file is already in this session's context, do the work inline — delegating pays twice: once writing a brief that reconstructs what is already known, once for the agent to re-read it.
- **The brief is the contract.** Every executor subagent receives in ONE prompt: (a) its phase of the plan with exact business-rule values and the relevant ACs, (b) the Restrições block, (c) the prohibitions — the PRODUCTION-AFFECTING table from Step 3.5 and the pre-existing-defects rule below — and (d) the expected deliverable: a structured report with files touched, tests written, the exact test command, and an honest pass/fail count. The report is the interface; the orchestrator must be able to check it without re-reading the whole diff.
- **An agent finishing is a status, not a success signal.** Verify each executor's report against reality — `git diff` for the claimed files, one targeted test run for the claimed green — before counting the phase as closed. When the user changes the spec mid-flight, correct the running executor by message instead of waiting for it to finish wrong.
- **Close every phase with the gates**: the phase's tests written and green (`profile.cmd_test_backend`), `profile.cmd_format_backend`, `profile.cmd_static_analysis` without new errors. A phase without its tests is not done. If queued code changed, restart the queue workers (`profile.cmd_queue_restart`) before any behavior check.
- **Pre-existing defects are reported, never fixed.** A bug discovered mid-execution that predates this branch goes into an `Achados fora de escopo` list in the phase report — with evidence — and is only fixed on explicit approval. When unsure whether something is pre-existing, check `git log`/`profile.default_branch` first and ask before touching it.

Never write code before the plan is approved.

If the user explicitly says "just write the plan, don't execute", stop after Step 5. Acknowledge the override.

### Step 6.5 — Independent verification (always-on, both tiers)

**When the last phase closes, in that same turn:** announce it in one line and dispatch ONE fresh read-only verifier subagent (`model="opus"` — never fable, never sonnet) per [references/verifier.md](references/verifier.md). Do not ask. Do not wait for the user to request it. Never let an executor dispatch it — the orchestrating session does, over the whole feature. The author never validates its own work, in the small tier as much as in the large one. When it depends on being remembered, it gets skipped; when it runs, it finds real gaps. `cdv-finalize` refuses to build commits for a plan-feature branch whose `STATE-<slug>.md` lacks the verifier's AC table, so skipping it here only moves the cost.

The verifier receives the approved plan (ACs + Restrições) **read from `STATE-<slug>.md`, never paraphrased from chat memory** — after a compaction, the file is the only faithful copy of what the user approved — plus the diff command and the gate commands, and returns an AC-by-AC verdict (coberto with `path:line` + asserting test, or descoberto), re-run gate results, orphan diff files, and unimplemented phases. Its AC table is appended to `STATE-<slug>.md` under `## Verificação`. Descoberto/red → fix and re-verify (max 2 iterations, then escalate). Only a clean verdict proceeds to `cdv-finalize`, with the AC table attached.

**Profile.** The plan's Resumo states `verificador: light` (default: proofs re-run, one located assertion per AC) or `verificador: standard` (grande tier only, opt-in: adds fault injection — up to 5 mutants in a throwaway worktree, per verifier.md). `standard` is for the feature where "the test exists and passes" is not enough evidence: a branch table, a guard, a boundary that production data will hit. It costs minutes; when the user has stated a deadline, `light` stands.

The full `cdv-pr-review` remains opt-in on top — this step checks the plan was implemented; `cdv-pr-review` checks the code is good.

## Hard rules (from `profile.instructions_file` + .claude/rules/)

**These are standing invariants of the repo — the user never needs to restate them in a brief.** A brief that is silent about tests, lint gates, branch discipline or area cards means they all apply in full; an explicit user override wins only for the named exception. Never treat the absence of "tests ship in the same PR" or "Pint + PHPStan clean" in a prompt as permission to skip them.

Surface these as **defaults** during the Q&A and bake them into the plan output:

- **Testes no mesmo PR, em toda fase.** Todo comportamento/wiring/validação novo entra com seus testes na mesma entrega — nunca como follow-up (`profile.instructions_file`).
- **Branch atual por padrão.** Já numa feature branch → o trabalho fica nela; nunca criar branch nova sem pedido explícito (Step 0 só cria branch quando o HEAD está em `profile.default_branch`/protegida).
- **Cartão de área quando um fato dele muda.** Se a feature muda um fato que um cartão de área (`profile.area_cards_glob`) afirma, a linha é corrigida no mesmo PR (fase 7); sem fato mudado, o cartão fica como está.

- **Aditividade no schema** por padrão. Zero `dropColumn`/`dropForeign`/`change` em tabela existente, exceto quando a feature explicitamente exige (e o usuário aprova).
- **Sem refactor fora do escopo** — manter alterações concentradas no que foi pedido.
- **Eloquent sobre `DB::`** sempre que possível.
- **FormRequests para validação**, nunca inline em controllers (exceto quando todos os siblings fazem inline em um módulo legacy).
- **Rotas conforme `profile.frontend_routes`.** Não inventar passo de geração de rotas que o profile não nomeia.
- **Formatador antes de finalizar** (`profile.cmd_format_backend`, a partir de `profile.app_dir`).
- **Análise estática** sem regressão de erro (`profile.cmd_static_analysis`, a partir de `profile.app_dir`).
- **Testes de regressão para mudanças com efeito sobre fluxo existente.** Quando o plano alterar contrato (response shape, evento, payload), semântica de guard/skip, ordem de execução, mapping de enum, ou comportamento de dispatch de job de um fluxo já em produção, a Fase 5 (Tests) deve incluir um teste explícito que cobre o caller pattern antigo + adaptação dos testes existentes com nota no commit `test:`. Critério detalhado na regra de testes do repositório (a extensão a nomeia).
- **Convenções de frontend: `cdv-frontend` é a fonte da verdade.** Toda regra de UI nova — placement, biblioteca de componentes, estilo de script, charts, permissions no template, texto de produto — vive lá (e em `profile.frontend_rules`). NÃO replicar aqui: carregar a skill ao planejar a fase de frontend **no tier grande** e deferir a ela; no pequeno, o arquivo vizinho é o padrão. Se o usuário pedir algo que conflita com essas regras, surfaçar o conflito.
- **Sem `Co-Authored-By`** em commits.
- **Este skill nunca faz push** — o `cdv-finalize` empurra a branch de feature (sem `--force`) e abre o PR no wrap-up; nada é mergeado.

## Composition with other skills

- `cdv-grilling` — upstream stage. Quando a entrada é o `decisions.md` do `cdv-grilling` (ledger com tags de procedência), pular Step 5 (Q&A) e usar o ledger como input direto do Step 4; só as linhas `[recomendação — pendente]` e as `Open questions` viram pergunta.
- `Explore` — Step 3 codebase mapping (mandatório antes da primeira pergunta nova).
- `cdv-frontend` — **fonte da verdade das convenções de frontend.** Carregar na fase 4 **apenas no tier grande**; no pequeno, o arquivo vizinho é o padrão. Este skill não replica as regras de UI; delega a ela (que por sua vez encadeia `profile.design_skill`).
- `profile.design_skill` — **critérios de qualidade de design** (pule quando `none`). No tier grande, a fase 4 abre com um "Design gate" que lista os critérios 🔴/🟠 específicos daquela tela. Responde "esta tela está boa?", enquanto `cdv-frontend` responde "este código está no padrão?".
- `profile.design_review_skill` — **auditoria de olhos frescos, só sob pedido explícito** (`disable-model-invocation: true`; pule quando `none`). NUNCA disparada por este skill ao fim de uma fase: quem escreveu a tela não encomenda a própria revisão. Existe para tela nova de verdade ou um fluxo que atravessa telas, e é o usuário que a chama.
- `cdv-interactive-qa` — executa o roteiro de QA (`QA-<slug>.md`) de forma dirigida após a implementação: um teste por vez, fixtures reais preparadas pela skill, verificação do trail pelo agente. Este skill AUTORA o roteiro; aquele o executa.
- `cdv-finalize` — invocado APÓS a execução das fases terminar, para gerar o `<slug>-pr.md` efêmero (descrição de PR, nunca commitado) e a árvore de commits atômicos. Consome a seção `## Finalize seed` do `STATE-<slug>.md` (escrita no Step 6, na aprovação) como seed de contexto, e recusa commitar sem a tabela do verificador em `## Verificação`. Owns the `branch-from-master.sh` script reused in Step 0.
- `cdv-debug` — não está nesta pipeline. Se o usuário descreve um bug em vez de feature, redirecionar.

The full pipeline for a vague feature:

```
cdv-grilling  →  cdv-plan-feature  →  execução em fases + verificador  →  cdv-finalize
    ↑                ↑                            ↑                              ↑
brief vago     plano multi-fase            Step 6/6.5 deste skill        lê o Finalize seed
decisions.md   (este skill)                (inline/subagentes)           e a tabela do verificador
               gera QA-<slug>.md           escreve STATE-<slug>.md       no STATE-<slug>.md
```

Each stage assumes the previous one ran. Skip stages only when the user explicitly says so.

## Bundled scripts and references

- `profile.worktree_runner` — the repository's script that runs a gate (a test filter, the formatter check, a read-only REPL query) against a WORKTREE's code. It lives in the repository, not here, because it encodes the repository's container setup; `none` means the worktree runs its own gates. Its literal invocation passes the worktree Bash guard.
- [references/worktree-safe-commands.md](references/worktree-safe-commands.md) — the Bash shapes the worktree guard refuses and the ones that pass. Load in the grande tier, right after entering the worktree.
- [scripts/lint-qa-guide.sh](scripts/lint-qa-guide.sh) — mechanical gate for the composed `QA-<slug>.md` (Step 4c, item 5). Exit 0 required.
- [references/plan-skeleton.md](references/plan-skeleton.md) — structure of the multi-phase plan rendered in Step 4 + a realistic example.
- [references/production-safety.md](references/production-safety.md) — full Steps 3.5/3.6/3.7 rules (classification, forbidden/allowed commands, QA-manual-only execution). Load when Step 3.5 begins.
- [references/qa-authoring.md](references/qa-authoring.md) — full QA-guide authoring doctrine for Step 4c (real fixtures, scope-source derivation, scope traps (the extension lists them), labels, Inertia availability). Load during Step 4c.
- [references/question-rounds.md](references/question-rounds.md) — Q&A taxonomy for Step 5 (classification, UI-first rule, architectural vs implementation level).
- [references/qa-guide-template.md](references/qa-guide-template.md) — template for the QA guide generated in Step 4c. Load only during Step 4c.
- [references/verifier.md](references/verifier.md) — verifier subagent prompt, `light`/`standard` profiles and verdict handling for Step 6.5. Load only when Step 6 finishes.

- The extension (`<profile.extension_dir>/cdv-plan-feature.md`) adds the repository's facts under headings that mirror this file's sections and links its own references (naming examples, QA scope traps, production-safety lists); read the heading that matches each step when it begins.

Load each reference only when its phase begins, not upfront.
