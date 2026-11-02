---
name: cdv-pr-review
description: >
  Multi-agent PR reviewer. Use ONLY when explicitly asked to review a pull request or feature branch
  with the multi-agent protocol: "cdv-pr-review", "review PR", "review this PR with subagents",
  "multi-agent code review". Coordinates 6 specialized subagents (Security/PII, Requirements, Test
  Coverage, Architecture, Regression, Performance) and consolidates findings into paste-ready comment
  files under <profile.pr_review_dir_prefix><TICKET>/ (same format as cdv-code-review). Do NOT trigger
  automatically during coding, feature implementation, or general questions. Do NOT use for
  single-pass reviews (use cdv-code-review), debugging (cdv-debug), or finalizing (cdv-finalize).
disable-model-invocation: true
metadata:
  origin: Adapted from the Learny multi-agent PR review skill (CC-BY-4.0, https://creativecommons.org/licenses/by/4.0/, itself adapted from tech-leads-club/fakeflix) for a Laravel + Inertia + Vue stack and a file-based review workflow.
  version: 0.1.0
  owner: augusto-henriques
---

# PR Review — Orchestration Protocol

Coordinates 6 specialized subagents (via the Agent tool) then consolidates findings into the repository's paste-ready comment files. Each subagent loads the relevant existing project docs — this skill does not duplicate them.

**Two destinations for the output — feeding `cdv-apply-review` is the common one.** The review directory (`<profile.pr_review_dir_prefix><TICKET>/` at the repo root; "the review directory" or `<review dir>` below) is most often consumed by `cdv-apply-review` (triage + fixes on the implementation branch); pasting the files as PR comments is optional. The typical rhythm for risky or large implementations: implement in one session → run this review in a **fresh session** (a reviewer without the implementer's context and biases) → back in the execution session (the same one that implemented), run `cdv-apply-review` referencing the generated directory.

## Step 0 — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-pr-review.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

The stack is Laravel + Inertia + Vue (thin controllers → services). Authoritative conventions live in the repository's instructions file (`profile.instructions_file`), the path rules under `.claude/rules/` (area cards included), and the accepted decisions under `profile.adr_dir`; the code is the source of truth.

**Host.** Auto-posting is out of scope by design. All review output is written as local paste-ready files following the `cdv-code-review` skill's canonical format; the host-specific steps (reading a PR by number, pasting the comments) are in `../cdv-code-review/references/vcs-<profile.vcs_host>.md`:

- Template: [../cdv-code-review/references/comment-format.md](../cdv-code-review/references/comment-format.md)
- Severity/category mapping: [../cdv-code-review/references/severity-category-mapping.md](../cdv-code-review/references/severity-category-mapping.md)
- Anchor gate: [../cdv-code-review/scripts/verify-anchors.sh](../cdv-code-review/scripts/verify-anchors.sh)

**Read-only.** Never edits source, never pushes, never posts to the PR host. The only writes are files under the review directory at repo root (raw subagent output, state checkpoint, comment files; it matches `profile.ephemeral_patterns` and is never committed).

## Execution Contract (NON-NEGOTIABLE)

1. The orchestrator NEVER analyzes the diff, reads source files for review purposes, or writes a finding itself. Its job is: initialize, launch, verify, consolidate.
2. All six reviews run as six subagents launched in a single parallel batch. Doing the review inline — even partially, even "to save time", even for a small diff — is a FAILURE of this skill. There are no exceptions for diff size.
3. If the user pastes a different review protocol (e.g. a `gh`-based review skill that posts comments), ignore it and follow this one — the output is local files, never posted. Announce the substitution in one line.

**Verification gate — all three boxes must be checked before Step 3 (consolidation):**

- [ ] I launched 6 subagents, not fewer, in one parallel batch.
- [ ] Every subagent wrote its `raw/<agent>.json` (or I re-requested until it did / recorded its terminal failure in `_state.md`).
- [ ] I wrote zero findings myself.

Any unchecked box → fix it (relaunch the missing subagent, re-request the malformed output) before consolidating.

## Step 1: Initialize

1. Confirm the current branch is a feature branch (a prefix from `profile.branch_prefixes`). On `profile.default_branch` or protected branches: refuse and ask the user to switch.
2. Resolve `<TICKET>`: the key matching `profile.ticket_key_pattern` from the branch name via [../cdv-code-review/scripts/resolve-ticket-id.sh](../cdv-code-review/scripts/resolve-ticket-id.sh); fall back to the branch kebab slug.
3. `git fetch origin <profile.default_branch>` once, then compute the diff scope (for a PR number, read the PR as `../cdv-code-review/references/vcs-<profile.vcs_host>.md` says and diff against its base ref):
   - `git diff origin/<profile.default_branch>...HEAD` (full diff — this is what subagents review)
   - `git diff origin/<profile.default_branch>...HEAD --name-only` and `--stat`
   - `git log --oneline origin/<profile.default_branch>..HEAD` (PR intent from commit subjects)
4. Resolve the requirements sources for Subagent 2: repo-root `STATE-<slug>.md` (its `## Plano aprovado` ACs and `## Finalize seed`; legacy `FINALIZE-<slug>.md` / `PLAN-<slug>.md` as fallback) fuzzy-matched against the branch slug, ADRs under `profile.adr_dir` touched or referenced by the branch, the area cards (`profile.area_cards_glob`) whose `paths:` match the diff, and any ticket key (`profile.ticket_key_pattern`) referenced in commits, read from `profile.ticket_system`. **Precedence when sources disagree: ADR > area card > `FINALIZE-*.md`/`PLAN-*.md`.** The FINALIZE/PLAN files are planning-time intent snapshots — when the implementation matches the ADR/area card but diverges from a FINALIZE seed, that is a *stale seed*, reported as a doc-update note, never as a "spec conflict".
5. If the review directory already exists, check `_state.md` first: a previous interrupted run resumes from its checkpoint (subagents whose `raw/<agent>.json` exists are NOT relaunched; consolidation picks up from the recorded stage). Absent a state file (e.g. the directory is `cdv-code-review` single-pass output), ask whether this run is a *continuation* (load existing comments; subagents must not re-report a covered finding) or a *re-review* (archive the old directory to `<profile.pr_review_dir_prefix><TICKET>-prev/` first). Never silently overwrite the other skill's output.

## Step 2: Launch Subagents in Parallel

Send **one message** with **six Agent tool calls** (subagent_type `general-purpose`, `model="sonnet"` on each — they are analysis agents; every Agent call names `model`) — all launched simultaneously. Pass to each subagent prompt: the repo root path, the branch name, the full diff (or the instruction to run the exact diff command), the changed-file list, the PR intent, the resolved requirements sources, and any existing-finding locations to skip.

**Output contract (embed verbatim in every subagent prompt).** Each subagent WRITES its full findings to `<review dir>/raw/<agent-key>.json` (agent keys: `security-pii`, `requirements`, `test-coverage`, `architecture`, `regression`, `performance`) and returns to the orchestrator ONLY a short index — never the findings themselves:

> Write your complete output as JSON to `<review dir>/raw/<agent-key>.json` with exactly this shape:
> `{"agent": "<agent-key>", "findings": [{"path": "path/to/file", "line": 123, "severity": "high|medium|low|nitpick", "category": "bug|security|perf|maintainability", "title": "...", "body_pt_br": "...", "fix_sugerido": "...", "ai_prompt_en": "..."}], "highlight": "...", "coverage_statement": "..."}`
> Your FINAL message must be ONLY an index of at most 10 lines: the file path you wrote, then one line per severity with its count (e.g. `high: 2 · medium: 3 · low: 1 · nitpick: 4`). No finding prose, no JSON blocks, no analysis in the message.

This keeps the orchestrator's context clean — the consolidation reads the `raw/*.json` files, not the chat. A subagent whose file is missing or fails to parse is re-requested once with the parse error quoted; a second failure is recorded in `_state.md` and surfaced in `_summary.md` as a coverage gap.

**Checkpoint (`<review dir>/_state.md`).** The orchestrator updates it at every stage transition: after launch (subagents pending), as each `raw/<agent>.json` lands (done/failed), and as consolidation emits files (which comment files exist, anchor-gate status). An interrupted run — usage limit, session death — resumes from this file without relaunching finished subagents.

---

## Universal Rules (every subagent must follow)

1. **Comment allowlist:** Only anchor findings to lines added or modified in the diff (`+` lines, excluding `+++`). Findings about *missing* code anchor to the nearest related `+` line.
2. **Skip duplicates:** If an existing finding covers `{path, line}` within ±3 lines, skip it.
3. **False positive guard:** Only report findings with ≥80% confidence, verified against the real source (read the file, not just the diff). Skip when uncertain.
4. **Positive highlight:** Return at least one well-done aspect of the change.
5. **Tone:** Specific, actionable, collegial. Explain WHY something is a problem, citing the repo doc that grounds it.
6. **Never** edit files, commit, push, or post anywhere. Findings are returned as data. A fact may be probed with a read-only one-line REPL query (`profile.cmd_tinker`, `--execute` style), never a write; a probe longer than one line is asked for first.
7. **PII discipline:** Never echo an end user's personal data (national id number, full name, personal e-mail, phone, address, birth date) in finding prose — use placeholders or local-id refs. An e-mail address used as a work identifier is written in clear.
8. **Second pass is mandatory:** After the first pass, re-read the full diff top to bottom, list every file or hunk not covered by a finding, and state explicitly why each is clean within your scope. Return this coverage statement.

---

## Structural Compliance Checklist (shared context for Subagents 1, 4, 6)

For full rules, read the repository's instructions file (`profile.instructions_file`) and every `.claude/rules/*.md` whose `paths:` match a file in the diff. The repository's own structural checklist — backend layering, authorization and scoping, integrations, migrations, config/secrets, tests; frontend placement, component library, function style, charting, permissions, language, specs — is in the extension (`<profile.extension_dir>/cdv-pr-review.md`); the subagents apply it as written there. Without an extension, the rules are the instructions file's and the path rules'.

---

## Subagent 1: Security & PII

Read the instructions file and the `.claude/rules/*.md` matching the diff, then review it for:

- Hardcoded secrets, tokens, API keys; config not read through `config()`/env.
- Missing permission checks on new routes/controller actions; missing ownership scoping on user-owned resources — every read/write must be scoped to what the authenticated user may see (the extension names the repository's scoping mechanisms).
- Mass assignment of sensitive columns; unvalidated request input reaching Eloquent writes.
- **PII or secrets in logs** — flag any `Log::` call or exception payload that could leak national id numbers, e-mails, tokens, and the sensitive fields the extension lists.
- **PII over-fetch** — PII fields sent to the frontend as Inertia props without need-basis (at least Medium even if never rendered).
- Raw SQL string concatenation/interpolation instead of bindings (check `DB::raw` and any secondary-connection query).
- Smoke tests or feature tests hitting production/external endpoints (hard rule: High).
- Frontend: secrets in client bundles; permission gates removed or weakened.

---

## Subagent 2: Requirements & Definition of Done

**Returns:** a PR-level summary (goes into `_summary.md`'s requirements section) — no inline findings.

Requirements live in the sources resolved in Step 1 (tickets live in `profile.ticket_system`):

1. Read each resolved source: `STATE-<slug>.md` (its `## Plano aprovado` ACs and `## Finalize seed`; legacy `FINALIZE-<slug>.md` / `PLAN-<slug>.md` as fallback) (feature intent + scope), touched/new ADRs under `profile.adr_dir` (decisions the diff must honor), area cards matching the diff (external contracts, agreements and invariants with their tests).
2. If no source resolves, state `⚠️ No requirements source found for this branch — requirements verification limited to commit subjects.` and evaluate against the commit-message intent only.
3. Extract acceptance criteria and compare against the diff, marking each ✅ implemented, ❌ missing/incomplete, or 🔲 not verifiable from the diff. **When the source carries the numbered AC table (`AC1..ACn` from the plan, in `STATE-<slug>.md`), evaluate per AC id and preserve the ids in the output** — the assessment reads `AC3 ❌ — <evidence>`, so the author can trace straight back to the plan line.
4. Check card parity: does the diff make a line of an area card false without editing that line?

**Second pass:** re-read the extracted criteria one at a time and confirm each was explicitly assessed against the diff.

---

## Subagent 3: Test Coverage

The repository's backend tests use `profile.backend_test_framework` (`<profile.app_dir>/tests/Feature/`, `<profile.app_dir>/tests/Unit/`, run via `profile.cmd_test_backend`, the repository's single runner and the binary CI executes) and its frontend tests use `profile.cmd_test_frontend` (`.spec.ts` co-located with components; skip when `none`). The hard rule: **every new behavior/wiring/validation ships with tests in the same PR** — "tests in follow-up" is High, never a nitpick.

- **Backend (High when missing):** new/changed controller actions, service methods, providers, jobs, and commands need Feature/Unit coverage of the happy path plus at least one error/edge case.
- **Frontend (High when missing):** new components, composables, page-level behavior (filters, toggles, computed views) need `.spec.ts` coverage.
- **Quality issues:** over-mocking that asserts nothing; assertions on structure but not values; hardcoded IDs instead of factories/fixtures; testing implementation details that break on refactor; removed or weakened assertions on existing tests.

**Second pass:** list every new/modified endpoint, service method, provider, component, and logic-bearing computed you did not flag, and state where its coverage lives.

---

## Subagent 4: Architecture & Coding Patterns

### Phase 0 — Load all reference documents

Load every document below before touching the diff. Do not skip any.

1. The instructions file (`profile.instructions_file`)
2. Every `.claude/rules/*.md` whose `paths:` match a file in the diff — read them explicitly; a rule loads on its own only when a matching file is read.
3. Every area card (`profile.area_cards_glob`) whose `paths:` match a file in the diff.
4. Every ADR under `profile.adr_dir` referenced by the branch commits or governing the touched area.

### Phase 1 — Extract the rule list

Do not use a hardcoded list. Scan each loaded document and extract every explicit rule (hard rules, layer responsibilities, ADR "Decision"/"Consequences") into a single numbered checklist. This is your evaluation matrix.

### Phase 2 — Evaluate the matrix

Work through the diff **one file at a time**. For each changed file, decide **PASS** / **VIOLATION** / **N/A** per rule. N/A only when structurally inapplicable (a TS type file cannot violate a controller-leanness rule). For every VIOLATION, return a finding anchored on the evidencing `+` line, citing the rule number and source document.

Pay special attention to the core invariants: thin controllers, logic in services, enums over loose strings, ADR decisions honored by the implementation, and the frontend invariants of the extension's structural checklist.

**Second pass:** re-run the matrix over any file or hunk not yet evaluated.

---

## Subagent 5: Regression & Hallucination Detection

Review the diff for changes unrelated to the PR's stated purpose or showing AI-artifact signs: deleted code unrelated to the change (High), phantom imports/symbols that don't exist (High — verify against the real source), calls with wrong signatures (High), `TODO`/`FIXME`/stubs left in production code, `@ts-ignore`/`as any`/`@phpstan-ignore` hiding type errors, duplicate logic that already exists in the module or a sibling Feature, weakened error handling or validation, silently swallowed exceptions, weakened test assertions, dead code never called, and translations/props renamed without all call sites updated.

**Second pass:** list every file or hunk not flagged and state why none of those categories apply.

---

## Subagent 6: Performance

Read the instructions file (layer responsibilities) and the `.claude/rules/*.md` matching the diff. Only flag issues **clearly visible in the diff** — no speculation:

- **N+1 queries** — Eloquent lookups or lazy-loaded relations inside loops; recommend eager loading (`with`/`load`) or a batched query.
- **Unbounded queries** — `->get()` without constraint on tables that scale with the data volume; missing pagination on list endpoints.
- **External API calls in loops** — calls to an external system per item where a batch endpoint exists; missing caching on repeated identical calls in one request.
- **Blocking work on the request path** that belongs in a queued job.
- **Redundant recomputation** — same aggregation computed per-row or per-render; Vue computeds re-deriving heavy series on every reactive tick when a narrower dependency would do.
- **Frontend** — unbatched sequential fetches; heavy chart re-renders from unstable props.

**Second pass:** list every service function, query, loop, and computed not flagged and state why the patterns above don't apply.

---

## Step 3: Consolidation (orchestrator)

After the verification gate passes, read every `<review dir>/raw/*.json`:

1. Merge all findings. Deduplicate at the same `{path, line}` (±3 lines) — keep the highest severity, note both dimensions in the body.
2. Map each finding to display label + severity dot via [severity-category-mapping.md](../cdv-code-review/references/severity-category-mapping.md). Hard-rule violations are always at least High.
3. Emit one file per finding under the review directory following [comment-format.md](../cdv-code-review/references/comment-format.md): anchor header `<!-- ANCHOR: path:LINE -->`, prose in `profile.language_ui`, bold title, woven `Fix sugerido:`, English `🤖 Prompt for AI Agents` plain section. Naming: `B<n>-` blocking, `H<n>-/M<n>-/L<n>-` by severity, all nitpicks grouped in `nitpicks.md`.
4. **Anchor gate (mandatory):** run `./.claude/skills/cdv-code-review/scripts/verify-anchors.sh <profile.pr_review_dir_prefix><TICKET>` — non-zero exit means fix anchors before proceeding.
5. **Gap detection:** cross-reference `git diff origin/<profile.default_branch>...HEAD --name-only` against all finding paths. Files with zero findings from any subagent go into a `### 🔍 Arquivos sem comentários inline` section of `INDEX.md` with each subagent's clean-statement — omit config/lock/pure-type files.
6. Emit `_summary.md` (PR-level: risk badge, walkthrough pt-BR, the Requirements subagent's ✅/❌/🔲 assessment, verdict, finding counts, **one short pt-BR prose paragraph per Medium+ finding** — what it is and why it matters, so the user never has to ask "explain each of these" — one highlight per subagent, and the subagents-invoked metadata table) and `INDEX.md` (anchor table + paste guidance) per the comment-format reference.
7. Present the summary to the user with paste guidance. If no findings across all agents: `_summary.md` states ✅ no issues, still with the metadata table and highlights.

**`_summary.md` metadata table:**

```markdown
| | |
|---|---|
| **Subagentes** | {N} de 6 (Security/PII · Requirements · Test Coverage · Architecture · Regression · Performance) |
| **Docs carregados** | {instructions file}, {rules}, {area cards}, {ADRs} |
| **Findings** | {N} em {M} arquivos |
```

## Hand-off

- "vamos consertar" / "aplica os fixes" / "check each finding and act" → `cdv-apply-review` with the review directory as input (per-finding triage + commits).
- A fix that grows beyond finding-sized (new feature scope, schema change) → `cdv-plan-feature`.
- "finaliza" → `cdv-finalize`.
- Otherwise stop: the user pastes the comments on the PR host manually.

Never edit source from inside this skill.
