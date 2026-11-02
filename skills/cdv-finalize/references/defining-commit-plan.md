# Defining the Commit Plan

How to propose the atomic commit tree when finalizing a branch, or when the user asks:
- "which commits should be done?"
- "split commits better"
- "separate unrelated changes"

---

## Goal

Produce a commit plan that is:
- complete (no changed relevant file forgotten);
- scoped (no unrelated files mixed);
- review-friendly (one concern per commit);
- consistent with local history style (`feat(scope):`, `fix(scope):`, `test:`, `chore:`, `docs:`, `refactor:`).

---

## Mandatory Workflow

1. Inspect the full working tree first — never from memory of what was edited; include untracked files (`git ls-files --others --exclude-standard`). The command set is `SKILL.md` Step 2.

2. Group by concern, not by folder only.
- Database persistence (migrations, models, factories).
- Backend behavior (services, controllers, requests, routes).
- Queue/command execution (jobs, console commands, schedules).
- Frontend (`profile.frontend_root`, components, types).
- Tests.
- Docs (area cards in `profile.area_cards_glob`, `profile.adr_dir`, skill references).
- Config/chore.

3. Detect unrelated changes explicitly.
- If a file is not part of the requested feature, do not include it in feature commits.
- If needed, propose either:
  - a separate `chore:` commit, or
  - exclude it from the PR.

4. Return numbered commits with exact file lists.
- Message + files must be deterministic and actionable.
- List files as plain `path` entries (no markdown links) so paste-into-terminal is clean — same rule as `SKILL.md` Step 5.

---

## Strong Rules

1. Do not miss files after a partial scan.
- Always build the commit plan from the full tree, never from memory of what was edited.

2. Separate unrelated config changes.
- Example: a `{app_dir}/config/*.php` tweak unrelated to the feature is isolated in its own `chore:` commit (or excluded).

3. Keep docs split from code.
- Area card, ADR (`profile.adr_dir`) and skill-reference updates go in dedicated `docs:` commits unless the user asks otherwise.

4. Keep tests in a dedicated commit when possible.
- Prefer a `test:` commit after the behavior commits it covers.

5. Ephemeral artifacts are NEVER part of any commit.
- `<slug>-pr.md`, `QA-<slug>.md`, `STATE-<slug>.md`, the review directories under `profile.pr_review_dir_prefix` (everything in `profile.ephemeral_patterns`) stay local.

---

## Commit Message Style

Types, scope inference and the recent-history examples live in `SKILL.md`, Step 5 — this file defers to that cheatsheet.

---

## Output Format (when the user asks for commits)

Important:
- The commit plan must be delivered in the chat response.
- Do not append commit plans to workflow/plan markdown files unless the user explicitly asks to persist it in a file.
- The commit plan content (titles, notes, and grouping labels) must be written in English.

Use this structure:

1. `type(scope): concise message`
- `path/file-a`
- `path/file-b`

2. `type(scope): concise message`
- `path/file-c`

Add an optional note for unrelated files:
- "Keep out of PR" or "separate as chore".

---

## Final Check Before Sending the Commit Plan

- Every relevant changed file is covered exactly once.
- No unrelated file is silently included.
- Commit order follows dependency flow (DB → backend → frontend → tests → docs/chore).
- If the user requested extra separation, prefer more commits over mixed commits.
