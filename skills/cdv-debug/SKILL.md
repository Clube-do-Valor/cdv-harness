---
name: cdv-debug
description: >
  Read-only root-cause investigation for backend bugs (integrations and sync
  jobs especially), from a Laravel log, a Sentry issue, or a human report,
  ending in an evidence-backed report. Triggers on "investigue esse erro",
  "olha esse log", "esse cliente reportou", "esse 404 da integração", "esse erro
  do workflow", or a pasted stack trace. When the user signals fix intent ("vamos
  consertar", "plano de fix"), sizes the fix and asks: a small fix (≤ ~3 files,
  no migration, no new screen) can be done here as "fix direto" (fix + test +
  express finalize); anything larger hands off to `cdv-plan-feature`. Never
  produces a multi-phase plan. Do NOT use for feature implementation,
  refactors, frontend-only bugs, or generic Laravel questions.
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Debug

Read-only bug investigation lane for the backend of the repository (`profile.repo_name`). Drives a fixed sequential path from a trigger (log, Sentry, or human report) to a root-cause report with verified evidence — and optionally renders the paste-ready Análise técnica block for the ticket.

## Step 0 — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-debug.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

## Operating principles

- **Read-only by default.** Never edit DB rows, never commit, never close a ticket. The investigation's only outputs are the report and, on request, the paste-ready Análise técnica block (Step 8).
- **PII discipline (hard rule).** PII columns (national-id numbers, phone, address, birth dates; the extension lists the column names and any other sensitive fields of this repository) are off-limits in queries unless the symptom is specifically about them. When a PII value must appear in the report or the chat, mask it, keeping at most the last digits (`<masked>`, `***-1234`; the extension gives the masks of this repository's formats). **E-mail is NOT in this list**: it is a work identifier (house rule) — query it and show it in clear. Minimum-column SELECTs are already the rule; this extends it — prefer ids + first names + e-mail, never dump full rows of the people tables into the transcript.
- **Evidence over hypothesis.** Every claim in the final report must be backed by a file read, a REPL query, an external API call, or a git log entry. Zero invention.
- **Ground in the area card.** The area card (`profile.area_cards_glob`) loads with the area's files; it carries the external contracts and invariants (each with its test) the code should keep. A doc is intent, not fact: when card and code diverge, the code wins, and the divergence itself becomes evidence in the report — plus a card-fix candidate.
- **Competing hypotheses, held open.** Before the first SELECT (Step 3), write 2–4 candidate causes, each with the query or code path that would confirm or discard it. Update the block after each evidence step: strike the discarded, refine the survivors, add new ones. Do not collapse to a single hypothesis until the data forces it — the final report marks each as confirmada / descartada / inconclusiva, with the evidence.
- **Two lanes when fix intent appears.** This skill stops at the root-cause report. The moment the user signals intent to fix (see Step 9 triggers), size the fix: a **pequeno** fix (≤ ~3 files, no migration, no new screen) is offered as *fix direto* here — fix + regression test + `cdv-finalize` in modo expresso; anything larger, or the user's choice, **invokes `cdv-plan-feature`** with the report as Shared Understanding context. Never produce a multi-phase fix plan here; producing one is a hard error.
- **No frontend authoring or review here.** This skill investigates backend bugs; frontend-only bugs are explicitly out of scope. Frontend conventions are owned by `cdv-frontend` — a UI fix is routed through `cdv-plan-feature` (which loads it). Do not restate UI rules in this skill.

## Workflow

### Step 1 — Identify the trigger and gather context

Detect which entry point the user provided:

- **Laravel log file** (`<profile.app_dir>/storage/logs/laravel-YYYY-MM-DD.log` or pasted excerpt): proceed to Step 2.
- **Sentry URL**: ask the user to paste the stack trace and the top-level exception message if the Sentry MCP is not connected. If connected, fetch via MCP.
- **Human bug report** (someone reported error Y for entity Z): collect at minimum: the reporter's e-mail, the affected entity's identifier (e-mail/name/id), the symptom, the approximate timestamp. If date is missing, default to today.
- **Integration trigger** (a workflow-automation execution link, or a "the bot didn't send it" report): the extension may list integration playbooks (`<profile.extension_dir>/cdv-debug/`); load the one that matches — it holds the workflow map, the execution URL format, the batching/abort mechanics and the read-only MCP recipe. When the automation platform's MCP is connected, search and read executions yourself before asking the user for anything.

If essential context is missing (no stack trace, no entity to query), ask exactly one clarifying question before proceeding. Do not guess.

### Step 2 — Read the throw site and caller chain

From the stack trace, pick the throw site and the upstream callers worth reading.

Use `Read` in parallel for those files at the cited offsets. Confirm the shape of the data flow before forming a hypothesis. Cite each file as `path:line` in the eventual report.

### Step 3 — Query the local database via the REPL

**Hypotheses first.** Before the first SELECT, render the competing-hypotheses block (2–4 candidate causes, each with the query/code path that confirms or discards it — per the operating principle) and keep it updated through Steps 3–6.

Read-only one-line REPL queries are allowed for facts, never writes; a probe longer than one line is asked for first. Prefer the wrapper [scripts/tinker.sh](scripts/tinker.sh), which runs `profile.cmd_tinker`, drops the lines matching `profile.cmd_noise_filter` when it is set, and accepts the snippet via `-e`, `-f`, or stdin:

```
./.claude/skills/cdv-debug/scripts/tinker.sh -e 'echo App\Models\User::count();'
```

Direct invocation is also fine when scripting is not available — in that case run `profile.cmd_tinker` with the snippet (`<profile.cmd_tinker>="..." 2>&1`, filtered through `profile.cmd_noise_filter` when it is set) and remember to escape `$` as `\$` inside the snippet.

In either case, use `echo json_encode([...]).PHP_EOL;` to keep output parseable.

**Read the live DDL before the first query against any new table.** Column names drift; never trust the schema you remember. Use [scripts/ddl.sh](scripts/ddl.sh):

```
./.claude/skills/cdv-debug/scripts/ddl.sh orders        # full DDL with FKs + indexes
./.claude/skills/cdv-debug/scripts/ddl.sh -d orders     # concise column list
./.claude/skills/cdv-debug/scripts/ddl.sh                   # list every table
```

Do this lazily: each time a new table enters scope, dump its DDL, then build the targeted query. Never `SELECT *`.

Common starting queries live in the integration playbook the extension lists for the area, when there is one.

Capture the relevant fields (ids, status, timestamps, external ids, source, trigger, created_at, updated_at — the extension names the ones that matter in this repository) and keep them for the report.

### Step 4 — Verify external state

When the bug involves an integration, prove the external side via the project's own API client inside the REPL — never invent an HTTP call.

Locate the right client in the application's API-client layer and call its public read methods in a one-line probe; the extension may carry the exact probe for each integration. A method that returns `null` (e.g. `$response->json()` on a 404) is the proof that the external object does not exist.

Never call PATCH/POST (write) methods from the debugger.

### Step 5 — Cross-reference git history

Hunt for prior fixes or PRs that explain the bug or stand to fix it:

```
git log --all --oneline --since=YYYY-MM-DD --grep="keyword"
git log --oneline <profile.default_branch> --since=YYYY-MM-DD --until=YYYY-MM-DD -- path/to/file.php
git show <commit> --format="%ai %s" --no-patch
```

Anchor by date (the bug-triggering record's `created_at`) to find which fix landed before vs. after.

The extension may list PRs and tickets worth checking against for this area, and a known-patterns catalog.

### Step 6 — Broaden the audit if a pattern is detected

If the proven hypothesis matches a known pattern, run a same-shape query for analogous records (other entities, broader date range). Use the repository's read-only audit command if it exists for the domain (the extension names them), otherwise build the REPL query directly.

Cap the broadening at one extra round per pattern — the goal is to flag scope, not to enumerate every record.

### Step 7 — Compose the report

Follow [references/report-template.md](references/report-template.md). The report opens with a block for the person who opened the ticket, then the technical sections.

0. **Resumo para quem abriu o chamado** — ten lines at most, written for the reporter and for the user to relay to a manager or a daily, per [explain-findings.md](../cdv-code-review/references/explain-findings.md): **O problema** (what the screen does wrong, in product words), **Como ver na tela** (which screen, which element, compared with what — or "não tem sintoma visível" and when it would appear), **Desde quando** (regression with the commit date, or "desde que existe"), **O que fazer agora** (the immediate mitigation the reporter can act on, one line), **Correção recomendada** (one sentence). No `path:line`, no column or method names, no metaphor. This block is the document a manager can be given.
1. **Causa raiz** — 1-2 sentences pinning the failure mechanism.
2. **Hipóteses consideradas** — each candidate cause from the Step 3 block, marked confirmada / descartada / inconclusiva with the evidence that decided it.
3. **Evidência** — bullets or a small table with the verified facts (DB rows, external-system state, log lines). PII masked per the operating principle.
4. **`path:line` refs** — every code citation linked in markdown.
5. **PRs/commits relacionados** — git hashes and PR numbers, with the merge date when relevant. When the bug is a regression, name the commit/PR that introduced it (`git log -S`/blame) and since when.
6. **Quem é afetado** — roles/permissions/users atingidos e a tradução da causa técnica para o sintoma visível na tela.
7. **Próximos passos** — split into "mitigação imediata" (action for the reporter) and "follow-ups técnicos" (optional code hardening, audit commands to run).

Keep tables tight.

### Step 8 — (Optional) Render the Análise técnica block for the ticket

Only triggered when `profile.ticket_system` is `notion` and the user wants the analysis on a ticket card. Otherwise stop after Step 7.

Follow [references/notion-ticket-template.md](references/notion-ticket-template.md) for the exact "Análise técnica" structure and render the block as paste-ready text in the chat (or as ephemeral `analise-<slug>.md` at the repo root when the user prefers a file). When the Notion MCP is connected and the user confirms the draft, the block is appended below the card's original description through the MCP; otherwise the user pastes it into the card. Do not restate the card's title, status or properties in the block.

### Step 9 — Two lanes when fix intent appears: fix direto or `cdv-plan-feature`

This skill is **debug-only**. The moment the user signals they want to move from "understand the bug" to "plan/implement the fix", stop investigating and pick the lane — with one question, never by assumption.

**Size the fix first**, from the evidence you already have (same criterion as `cdv-plan-feature` Step 0): **pequeno** = up to ~3 files, no migration, no new screen; **grande** = anything else.

- **Pequeno → offer the direct lane.** One `AskUserQuestion`: *"O fix cabe em ~N arquivos, sem migration e sem tela nova. Corrijo aqui direto (fix + teste + finalize expresso) ou monto o plano?"* — recommended: direto. On "direto": ensure a feature branch on the main checkout (`.claude/skills/cdv-finalize/scripts/branch-from-master.sh fix/<slug>` from `profile.default_branch`; from another feature branch, ask), apply the minimal fix with its regression test in the same change, run the targeted suite (`profile.cmd_test_backend` with `profile.cmd_test_backend_filter`) + `profile.cmd_format_backend`, then invoke `cdv-finalize` and tell it **modo expresso**. No phases, no `STATE-*.md`, no QA artifacts — the PR's `## 🧪 Como testar` is the QA record. The verifier of plan-feature does not run in this lane; the regression test is the proof. If the fix grows past the criterion while you write it, stop and route to `cdv-plan-feature` with what you learned.
- **Grande, or the user chose "plano" →** **invoke the `cdv-plan-feature` skill via the `Skill` tool**, passing the root-cause report + suggested next steps as the Shared Understanding block.


**Trigger phrases (non-exhaustive)** — treat any of these as a mandatory handoff signal:

- "vamos consertar", "vamos implementar", "vamos corrigir", "go fix", "go implement"
- "prossiga implementando", "prossiga para o plano", "go to plan", "plan it"
- "option B", "opção b" (or any "go with option X" referring to an implementation path you offered)
- "abra um plano", "monta o plano", "preciso de um plano de fix"
- "open a PR for this", "let's PR this", "create the branch"

**What to pass to `cdv-plan-feature`:**

```
SHARED UNDERSTANDING (from cdv-debug)

## Bug
{1-2 sentence causa raiz from Step 7}

## Evidence
{the evidence table / bullets from Step 7}

## Code refs
{path:line list from Step 7}

## Related PRs
{PR/commit table from Step 7}

## Suggested fix direction
{the "follow-ups técnicos" bullets from Step 7, framed as the plan's goals}

## Out of scope for this fix
{whatever the user explicitly excluded during debug}
```

## Troubleshooting

### The REPL command fails to start
Cause: running outside the project root, or the runtime the command targets is not up.
Solution: `cd` to the checkout that holds the repository's runtime configuration and check that the runtime is up. If it is not, ask the user before starting it — do not auto-start services.

### Tinker returns "Call to a member function X on null"
Cause: the method returns null/array directly instead of a Response object (e.g., a client method that returns `$response->json()`, which is `null` on 404).
Solution: check the return type in the client method before chaining; treat `null` as the proof of 404.

### The command prints noise around the result
Cause: the REPL command emits warnings on every call.
Solution: set `cmd_noise_filter` in the profile (an extended regular expression of lines to drop); `scripts/tinker.sh` applies it.

### Stack trace points to a vendor file
Cause: the real bug is in our code one or two frames above. Vendor frames are middleware noise.
Solution: walk up until you hit a frame under the application's own code (`app/` inside the container, `<profile.app_dir>/app/` on host), then read that file.

### User asks to also delete the orphan records
Cause: scope creep beyond read-only.
Solution: surface the recommendation in the report but require explicit confirmation before any DB write. If approved, use the repository's dedicated audit command (the extension names it) plus a deliberate `DELETE` via the REPL — never a bulk operation without per-row evidence.

### User pivots from "understand the bug" to "implement the fix"
Cause: debug session concluded; user wants to plan/build the correction.
Solution: **invoke `cdv-plan-feature` via the `Skill` tool** with the Shared Understanding block from Step 9. Do not draft phases, file lists, or branch names from this skill. If you already started drafting a plan in chat, acknowledge the slip and hand off formally — the plan must live in `cdv-plan-feature`, not here.

## Tools assumed available

`Read`, `Bash` (REPL + git), `Grep`/`Glob`. Sentry MCP is optional — fall back to pasted stack traces when not connected. The Notion MCP is optional too: without it the Análise técnica block leaves as paste-ready text (Step 8).

## Bundled scripts

- [scripts/tinker.sh](scripts/tinker.sh) — wrapper around `profile.cmd_tinker` (for instance `docker compose exec ... php artisan tinker --execute`) that drops the lines matching `profile.cmd_noise_filter` (when set) and accepts the snippet via `-e`, `-f`, or stdin. Use this in Step 3 unless you have a reason not to.
- [scripts/ddl.sh](scripts/ddl.sh) — print the live DDL of a table (`SHOW CREATE TABLE` by default, `DESCRIBE` with `-d`) or list every table when called without an argument. Delegates to `tinker.sh`, sanitizes the table name to `[A-Za-z0-9_]+`. Use this before the first SELECT against any new table in Step 3.

## When to load each reference file

- Integration playbooks — `<profile.extension_dir>/cdv-debug/*.md`, listed by the extension. Load the one that matches when the trigger smells like that integration (a sync with a 404 on the external side, a webhook, duplicates, an automation that "didn't fire"). Each holds the known patterns with proof snippets and the read-only access recipe.
- [references/report-template.md](references/report-template.md) — load before Step 7. Contains the exact section shape and a realistic example.
- [references/notion-ticket-template.md](references/notion-ticket-template.md) — load only when a Notion ticket URL is in scope (Step 8).

Do not load all of them upfront — each one only when its phase begins.
