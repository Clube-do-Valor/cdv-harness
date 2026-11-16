# Production safety

Shared reference, vendored to `.claude/harness/references/`. Load it before a plan is drafted, and give it to every builder, fixer and Verifier child. These rules bind the plan, the build (main session AND every child), every verification pass and the QA. The repository's note for this reference (`<profile.extension_dir>/references/production-safety.md`) names its command families, tables and external clients; read it with this file. Reading production goes through `.claude/harness/bin/prod-read` (skill `cdv-prod`), never a free-form `ssh`.

## 1. Production-impact analysis (before drafting the plan)

For every code path the feature will touch, classify it as **PRODUCTION-AFFECTING** or **DEV-SAFE**. This classification dictates which paths the agent may exercise during the build and the QA, and which MUST be handed to the developer.

The boundary is **modification of state**, not reading. Reading real data (queries, live API reads) is DEV-SAFE. A code path is **PRODUCTION-AFFECTING** only if it can — directly or transitively — *write/mutate/trigger a side-effect* when executed by the agent outside production:

- Write to or mutate an external system: any of `profile.production_writing_integrations`, or any Slack/email/SMS/push reaching a real person
- Persist to or mutate tables holding real-people data (the repository's note lists them)
- Dispatch a queued job whose `handle()` chains into any of the above
- Call an external API that **writes**, using a token that reaches a real system (`profile.production_writing_integrations`) (the write methods of an API client, calendar adapters, workflow triggers)

Concretely, **Bash commands that are production-affecting by default**:
- the console command families the repository's note lists (syncs, ingests, writes to an external system, links)
- any `*:notify-*`, `*:remind-*`, `*:send-*`, `*:dispatch-*` / scheduled-task triggers (the repository's note lists its own)
- the REPL (`profile.cmd_tinker`) **when used to write/mutate rows or dispatch a job** (read-only inspection is DEV-SAFE)
- any one-off PHP script that writes via `Http::*->post/put/patch/delete(...)`, a writing API-client method, or a service that ultimately writes to the network

(All of these run with the `profile.cmd_container_exec` prefix when `profile.commands_run_on` is `container`.)

Write the classification table into the plan:

```
## Production-impact analysis

| Code path                                     | Classification        | Validation strategy                                       |
|-----------------------------------------------|-----------------------|-----------------------------------------------------------|
| ReportBuilder::deriveType                     | DEV-SAFE (read-only)  | Feature tests with RefreshDatabase                        |
| IngestRecordsCommand::handle                  | PRODUCTION-AFFECTING  | Feature tests with Http::fake() — the developer runs it live |
| SyncPropertiesJob::handle                     | PRODUCTION-AFFECTING  | Feature tests with Queue::fake()/Http::fake() — never live |
```

The plan and the build must respect this table: PRODUCTION-AFFECTING paths are tested ONLY via the backend test framework with appropriate fakes (`Http::fake()`, `Queue::fake()`, `Bus::fake()`, `Notification::fake()`, `Mail::fake()`). They are NEVER smoke-tested by running the real console command or hitting the live API, even "to confirm it's wired up". Wiring confirmation comes from tests passing + reading the code, not from execution.

## 2. Forbidden smoke tests (HARD STOP)

During the build, NEVER run any command that maps to a PRODUCTION-AFFECTING path of the analysis. This applies to the main session, every child, every verification pass and the QA.

These families may also be blocked at the harness level through the repository's versioned `.claude/settings.json` deny rules (the repository's note lists which) — but this rule enforces them up-front so the agent doesn't even attempt. Read-only REPL use is deliberately NOT denied at the harness (fixture derivation and debug depend on it); the write-vs-read REPL boundary remains this rule's responsibility.

Forbidden Bash patterns during implementation (they write/mutate/trigger side-effects):
- `php artisan` console commands of the families the repository's note lists
- `php artisan *:notify-*` / `*:remind-*` / `*:send-*` / `*:dispatch-*`
- the REPL (`profile.cmd_tinker`) **that writes/mutates rows or dispatches a job** (read-only inspection is allowed)
- `php -r` / `php -f` one-shot scripts that write via models or `Http::*->post/put/patch/delete`

Allowed during implementation (DEV-SAFE):
- `profile.cmd_test_backend` / `profile.cmd_test_backend_filter` (tests with fakes — NOTE: it is the repository's single runner; do not use another)
- `php artisan migrate --path=...` (only the new migration)
- `php artisan route:list`, `schedule:list`, `list`, `make:*`
- read-only inspection: REPL queries that only read, and live API reads that don't write (reading is allowed — only state modification is forbidden)
- `profile.cmd_format_backend`, `profile.cmd_static_analysis`, type checks, and `profile.cmd_build_frontend` when it is set (`none` means the build must never be run: the dev server owns the bundle)
- `git` / `gh` operations

Any "I just want to confirm the command is wired correctly" instinct → STOP. Write a test that asserts the wiring (job dispatched, API called with the expected payload via `Http::fake()`). That is the wiring confirmation — not running the real write command.

## 3. Real execution belongs to the developer

Every PRODUCTION-AFFECTING path of the analysis gets a step labeled `[PRODUCTION-AFFECTING]` in the QA steps of the run, handed to the developer (`cdv-qa`). The agent never runs these steps itself, even after the implementation is "done", and they never enter any automated script. A QA step that changes an external record first names the automations that change triggers, and stops to ask when one reaches a person or a live automation.
