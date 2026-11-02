# QA — {{FEATURE_TITLE}}

> {{FEATURE_SUMMARY}}
> Run these steps in order. Commands carry the `{{EXEC}}` prefix: the container when the repository runs its commands there, nothing when it runs them on the host.
>
> **important:** do not run the `[PRODUCTION-AFFECTING]` steps yourself — those are for me to execute manually. Smoke tests must never touch production behavior.
>
> **Label legend:** `[READ-ONLY]` — reads only (no DB writes, no external side-effects). `[MUTABLE: <what it writes>]` — creates, updates, or deletes rows in the local app DB, or triggers a service that does so, with NO external/production side-effect. `[PRODUCTION-AFFECTING: <what it touches>]` — writes to or mutates an external system shared with prod (the ones in `profile.production_writing_integrations`) or triggers a job/side-effect that does so; **manual execution only**, never automated. Reading real data is NOT production-affecting — only state modification is.

---

## Prerequisites

<!-- List env vars, config keys, or seed data required before running. Example:
1. `.env` has `SOME_SERVICE_TOKEN` populated.
2. Add to `.env`:
   ```
   SOME_CONFIG_KEY=value
   ```
3. Clear config cache:
   ```bash
   {{EXEC}} php artisan config:clear
   ```
-->

---

## 1. Verify config is wired `[READ-ONLY]`

<!-- Tinker command to confirm config is readable. Use --execute form:
```bash
{{TINKER}}="echo config('services.some.key');"
```

**Expected:** prints the expected value.
-->

---

## 2. Run the automated test suite `[READ-ONLY: runs in isolated test DB — no writes to the app database]`

```bash
{{EXEC}} {{TEST}} --filter={{FILTER}}
```

**Expected:** all tests green.

> `exit 127` / "runner not found" means the runner is missing where the command ran: run the tests
> where `profile.commands_run_on` says.

---

<!-- Add feature-specific steps below. Each step must:
  - Start with a heading: `## N. Step title [READ-ONLY]`, `## N. Step title [MUTABLE: <what it writes>]`, or `## N. Step title [PRODUCTION-AFFECTING: <what it touches>]`
  - CITE THE AC IT VALIDATES: append the plan's acceptance-criteria id(s) to the heading — `## 3. Summary table renders real values [AC2] [READ-ONLY]`. Every ACn from the plan must appear in at least one step; a step validating nothing from the plan is either setup (label it) or scope creep.
  - PRODUCTION-AFFECTING steps are manual-only: never auto-run by the agent.
  - Use the `{{EXEC}}` prefix for ALL commands.
  - Use the single-line REPL `--execute="..."` form (`{{TINKER}}`) — NEVER heredoc.
  - Include an `**Expected:**` block.
  - REAL-DATA-DERIVED EXPECTED VALUES: reading the QA database (`profile.qa_env`) is DEV-SAFE. Before writing each `**Expected:**`, query the DB to pick the richest real fixture and compute concrete numbers; bake real ids + counts in (e.g. "owner 7 → 42 records, 17 with field A"). Abstract expectations ("expect the records to show") are unfalsifiable — they pass on all-stub/empty/wrong-scope renders. Keep PII out of this committed file: opaque ids + counts only.
  - NO PLACEHOLDER ENTITY IDS: every browser/staging/REPL step names a REAL id pre-queried from the DB — never `{your-client-id}`, `<id>`, `SOME_ID`, or "pick one of your clients". The only literal braces allowed are framework route patterns echoed by `route:list` (e.g. `items/{item}`). A placeholder id is as unfalsifiable as an abstract Expected — the step "passes" by being un-runnable.
  - LOCAL URLS ONLY: QA runs locally against `profile.qa_env`. Browser steps use `profile.qa_url` (the local dev host), NEVER the production domain. A prod URL risks mutating real data and makes `[PRODUCTION-AFFECTING]` steps hit prod for real.
  - EXTERNAL / OWNER-SCOPED SCREENS still get a real fixture, never a placeholder. If the rendered values come from an external system or the screen is owner-scoped: (a) derive a real entity id + owner scope from the QA database, through the feature's actual scope source (see qa-authoring.md), (b) bake local-derivable counts/sparsity into Expected, (c) dump the external/PII expected values to a gitignored `storage/app/qa-scratch/<slug>-<id>.json` via a tinker that echoes only the path, and tell the tester which fields are external-only (cross-check the source UI).
  - Escaping inside --execute="...": variables → `\$var`; strings → single quotes; backslash namespaces need no escaping.

Examples:

## 3. Smoke: verify service returns expected output `[READ-ONLY]`

```bash
{{TINKER}}="use App\Services\SomeService; \$result = app(SomeService::class)->run(); echo json_encode(\$result, JSON_PRETTY_PRINT);"
```

**Expected:** ...

## 4. Full run `[MUTABLE: writes to some_table — inserts and updates rows]`

```bash
{{TINKER}}="use App\Services\SomeService; \$result = app(SomeService::class)->run(); echo json_encode(\$result, JSON_PRETTY_PRINT);"
```

**Expected (first run):** ...

**Expected (re-run immediately after):** ...

## 5. Live ingestion against the external CRM `[PRODUCTION-AFFECTING: writes to the CRM + local_records]`

> Manual only — do NOT run this autonomously. Reaches a real external system (`profile.production_writing_integrations`) with a real token.

```bash
{{EXEC}} php artisan app:ingest-records --since=2026-05-01
```

**Expected:** ...
-->

---

## N. Formatter + static analysis `[READ-ONLY: static analysis only — no DB writes, no API calls]`

```bash
{{EXEC}} {{FORMAT}}
{{EXEC}} {{ANALYSE}}
```

**Expected:**
- Formatter: no output (no style violations).
- Static analysis: 0 new errors.

---

## Known limitations

<!-- Deferred behaviors not covered by this slice. Delete if none. -->
