---
name: cdv-interactive-qa
description: >
  Interactive step-by-step manual QA of a branch against the local QA
  environment — one test per AskUserQuestion turn, real-data fixtures prepared
  by the skill, side effects self-verified, failures triaged in-loop. Works on
  any implemented branch. Triggers on "QA this branch with me", "roda o QA
  interativo", "como eu faço QA disso?", "me guia no QA", or the finalize
  wrap-up offer. Do NOT use for pure automated-test runs, production debugging
  (`cdv-debug`), or authoring the QA guide (`cdv-plan-feature` Step 4c).
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Interactive QA

Turns a QA roteiro into a driven session: the skill proposes one test at a time, the user acts in the UI, the skill verifies the observable trail itself, and failures are fixed on the spot — committed and re-tested before moving on. It is adapted to the repository's environment (`profile.qa_env`).

## Step 0 — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-interactive-qa.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

## When to use

- After implementation, on any branch that needs manual validation beyond the automated suite — with or without a pre-existing `QA-<slug>.md`.
- When the user asks how to QA a feature, wants click-by-click guidance, or accepts the offer from `cdv-finalize`.

## Ground rules (non-negotiable)

- **PRODUCTION-AFFECTING steps are user-executed, always.** Classification per `cdv-plan-feature` Step 3.5: anything that writes to one of `profile.production_writing_integrations`, mutates real-people tables via a flow that chains into external writes, or dispatches a job that does — the agent never runs these, even when delegated. `[MUTABLE]` local-DB writes may be delegated ("run yourself") explicitly; `[READ-ONLY]` needs no ceremony.
- **Mask PII in any output** — prefer ids + first names, never paste national-id numbers or full addresses into the chat or into committed files. **E-mail addresses are the exception**: they are the work identifier and appear in clear in the chat and in reports.
- **Self-verify the trail.** When a step has an observable trail (log line, DB row, queue count, audit record), the skill checks it directly — never asks the user to confirm something a read-only query can prove.
- **One question at a time** via AskUserQuestion; every question carries ✅ Passou / ❌ Falhou options.
- **Test runner:** `profile.cmd_test_backend` (with `profile.cmd_test_backend_filter` for a subset), run where `profile.commands_run_on` says — it is the repo's single runner and what CI executes; do not fall back to another runner. REPL probes always go through `profile.cmd_tinker` as a single-line `--execute` (a heredoc breaks on copy-paste).

## Phase 0 — Environment safety audit

Before any state-mutating step, establish where external writes would land. Check `.env` **key presence only** (never print values) for the tokens of each of `profile.production_writing_integrations`, and read the relevant `ApiClient`/adapter code for environment guards. Present a verdict table (service → guarded/unguarded → decision). Steps that would reach an unguarded external service are `[PRODUCTION-AFFECTING]` and blocked from agent execution — the user runs them or skips. Record the decision once; don't re-ask per step.

## Phase 1 — Setup checklist

1. Branch checked out where the app runs (`profile.main_checkout`). When the branch lives in a worktree or the main checkout is on something else, bring it with `profile.bring_branch_script` — never with a bare `git checkout`: first check that no other agent session is working in this checkout (one that is busy there means stop and ask), then run the script with `--check <branch>` and show its verdict; only on a passing check, run it again without `--check`. The script's own output says what to do next. When `profile.bring_branch_script` is `none`, check `git status` for someone else's uncommitted work and ask before switching; never stash. Containers up per `profile.qa_env` (`docker compose ps`; the extension lists the services to expect).
2. Migrations: run the pending ones only (`profile.cmd_migrate_status` lists them; surface anything unexpected).
3. **When `profile.cmd_build_frontend` is `none`, the dev server owns the bundle and is the user's to run.** NEVER run a frontend build then — a stale bundle silently overrides the dev server. The rest of this item applies only in that case (the backend reads the dev-server hot file, `<profile.app_dir>/public/hot`).
   **Never start a second dev-server instance.** `public/hot` is a single shared file: two instances race to write it, and the Laravel Vite plugin **deletes it on shutdown of either one**, so the user's still-running server gets "Vite manifest not found" the moment the agent's copy exits. Check first — `pgrep -af` for the repository's `node_modules/.bin/vite` — and if none is running, **ask the user to start it** instead of starting a competing one (they keep it in a real terminal; an agent-owned background process dies with the task and takes `public/hot` with it). If `public/hot` is missing while their server is up, restore it without restarting anything: `printf 'http://127.0.0.1:<their port>' > <profile.app_dir>/public/hot` (port from `ss -ltnp`).
4. **Restart the queue workers after any branch switch or backend commit** with `profile.cmd_queue_restart`. Workers are long-lived processes holding old code; stale workers throw "undefined method" on new paths. The scheduler is safe (spawns fresh processes).

## Phase 2 — Derive the test script

1. **Source of the roteiro**, in precedence order: `QA-<slug>.md` at the repo root (ephemeral, authored by `cdv-plan-feature` Step 4c) → the `## 🧪 Como testar` of `<slug>-pr.md` → derive from `git diff origin/<profile.default_branch>..HEAD` (every user-facing surface, every business-rule branch including boundaries, every side effect).
2. Order: cheap/read-only first → local-mutating → externally-visible last.
3. **Real fixtures, prepared by the skill — named the way the surface names them.** Every step names a real fixture pre-queried from the local DB — never "pick one of your clients". Carry the **display label** (name) whenever the tester has to find the entity through a search box, dropdown or autocomplete, and the **id** where it is actually consumed (URL, query param, REPL, expected values). Write both — `user 15 (Jane Doe)` — since an id cannot be typed into a name search and a bare id sends the tester back to the DB to run their own QA. Derive the fixture from the feature's ACTUAL scope source (read the guard/controller and call that same method in a read-only REPL probe), and reproduce the guard end-to-end so the URL yields 200 before it is baked in. The extension lists the access-scope traps that shipped 404s before.
4. **UI labels are literal.** Every element named in a step is the exact label grepped from the component source. A label not found in the source means the step cannot be written yet.
5. **Data for QA** (when the QA database lacks the states to exercise):
   - Prefer an idempotent, local-only seeder following `profile.qa_fixture_pattern`, covering one record per flow state: docblock stating it is local-only, what it sets up, that re-running wipes only its own rows — **and which UI actions will NOT work on the fixtures and why** (e.g. reprocessing a fixture calls the real external system). App code is never edited to fabricate state. The extension names the precedent seeder.
   - For volume-dependent features, a real fill with an explicit `--limit` justified by the scenario. **Never a full-population fill on the first run** — a full run (hours, thousands of rows) needs the user's explicit approval after a limited run passed.
6. Long-running preparation (syncs, backfills, queue drains) follows [references/long-running-jobs.md](references/long-running-jobs.md) — background with progress + DONE marker, re-armed monitoring, summary delivered without the user having to nudge.
7. Time-dependent rules are tested by advancing the scheduled rows and running the due-command manually (user-executed when it writes externally) — never by changing the application clock.

## Phase 3 — Interactive loop

For each step:

1. Embed the full checklist INSIDE the AskUserQuestion `question` string (numbered click-by-click actions on literal labels + `*Esperado*` lines with real-data-derived values + the closing question). The question box is the only surface guaranteed visible at answer time.
   **URLs go bare, never inside markdown emphasis.** The question box renders as plain text, so `**http://localhost:<port>/x**` (the app's address is `profile.qa_url`) is copied *with* the asterisks and 404s in the browser. Put each URL alone on its own line, unwrapped — no bold, no backticks, no trailing punctuation touching it.
2. Options: ✅ Passou / ❌ Falhou (descreva) / a step-specific third option when useful.
3. On ✅ with an observable trail: verify the trail anyway (grep `storage/logs/laravel.log`, read the rows, check the queue) before marking passed.
4. On ❌: diagnose immediately — browser console + `laravel.log` first, then code. Distinguish **feature bug** (fix + commit on this branch, `profile.cmd_format_backend` + targeted tests, restart queue workers if queued code changed, re-run the step) from **pre-existing bug** (report it in the `Achados fora de escopo` list with evidence — fix only on explicit approval) from **environment issue** (dev server needs restart, stale queue worker, missed migration — apply the fix from the symptom table and re-run).
5. Keep a running status table.

## Phase 4 — Closure

1. Summary table: test → status → fixes produced (commit hashes).
2. Residual-risk list: what remains covered only by automated tests, what nobody covered, plus the `Achados fora de escopo` list.
3. **Test-data cleanup list — explicit and mandatory:** every row mutated and every demo fixture created (seeder wipe command included). Cleanup of `[MUTABLE]` rows can be delegated; anything touching external systems is user-executed.
4. If QA produced fix commits, offer `cdv-finalize` (the commit tree and the PR description changed).

## Composition

- `cdv-plan-feature` — authors `QA-<slug>.md` at planning time (Step 4c); this skill consumes and executes it interactively.
- `cdv-finalize` — offers this skill at wrap-up; QA fix commits loop back into a new finalize pass.
- `cdv-debug` — production incidents and stack traces belong there, not here.

## Bundled references

- [references/long-running-jobs.md](references/long-running-jobs.md) — contract for background syncs/backfills/queue drains during QA. Load only when a long-running command enters the script.
