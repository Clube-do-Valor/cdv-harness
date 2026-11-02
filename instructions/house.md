## House rules (cdv-harness)

This block is written by `harness sync` from the cdv-harness core. Change it in the core (`harness propose`), never here: the next sync overwrites it. The facts of this repository live in `.claude/harness/profile.yaml`, in the extensions under the profile's `extension_dir`, and in the rest of this file.

### The vendored core

- `.claude/skills/cdv-*`, `.claude/rules/core/` and `.claude/harness/bin/` are copies of the core, pinned by `.claude/harness.lock`. The CI gate (`sh .claude/harness/bin/verify.sh`) fails a pull request that edits them. A change to them goes to the core first: `harness propose`, then a new tag and `harness sync`. An emergency commit that must touch them carries a `Harness-skip: <reason>` trailer.
- A fact of this repository that a core skill needs goes to the profile or to that skill's extension (`<extension_dir>/cdv-<skill>.md`), never into the vendored copy.

### Load context before editing

The code is the source of truth. What it cannot hold — external contracts, agreements with other teams, invariants and the tests that prove them, traps an agent already fell into — lives in the repository's rules and docs (the profile's `docs_dirs`, `area_cards_glob` and `adr_dir`). A doc that disagrees with the code is stale, not an authority. An "out of scope" or "not built" list is never a decision.

### Session hygiene

- **Waiting:** never `sleep N` in Bash. One `Monitor` per long-running process; when it expires, re-arm it and say so.
- **Automatic notifications** (a fork source, a notification for a waiter that was killed, a teammate idle notice) carry no user text. Answer with one line at most, or not at all. Never re-explain the session state or ask the pending question again — the user did not speak.
- **Chrome MCP:** text before pixels. `get_page_text`/`read_page` first; screenshot only when layout matters; never navigate to or capture a `chrome-extension://` URL (the extension cannot see it). Heavy single-page apps freeze the renderer under repeated screenshots — one screenshot, then text tools.
- **Investigating is not implementing.** In planning or debugging steps, probes are read-only one-line REPL queries (the profile's `cmd_tinker`), grep and file reads. No file is written — not in the app, not in a container's `/tmp` — before the user approves a plan. A probe that needs more than one line is asked for first.

### Working standards

**Before starting a new feature:** ask the programmer whether to search the docs (the profile's `docs_dirs`), `.claude/rules/` and `.claude/skills/` for existing documentation, a rule or a skill covering the requested feature. Only skip this prompt if the request is clearly a bug fix or a small localized change.

**After finishing a task:** ask the programmer whether documentation should be created or updated — a rule under `.claude/rules/`, a skill extension under the profile's `extension_dir`, a repository skill, or a doc — to reflect what was built. Only skip this prompt for trivial fixes with no behavioral impact.

**Tests:**
- Every change that introduces new behavior, wiring, validation rules, service logic, or API surface MUST ship with tests in the same PR.
- Tests are not deferrable to a follow-up PR, even when the change feels "schema + wiring only" — migrations that wire up new payload fields require a feature test exercising the new endpoint shape.
- Defensive checks in services (e.g., "only stamp X when payload has Y") require coverage of both branches.
- A PR description that says the tests come in a follow-up PR is a blocker; stop and add the tests before requesting review.

**Commits:** use [Conventional Commits](https://www.conventionalcommits.org/) in English, with a scope (`feat(scope): ...`, `fix(scope): ...`, `refactor:`, `docs:`, `chore:`, `ci:`, `test:`). Describe intent, not the file changed. Never add a `Co-Authored-By` trailer. Push only feature branches (the profile's `branch_prefixes`), never with `--force`.

**Language:** the profile's `language_code` is the default for everything an engineer types — classes, enum case names, methods, variables, columns, component filenames, tests, config keys, commits and docs. One concept has one name, in one language: mixed-language identifiers are prohibited, and there is no "established business term" exception. The profile's `language_ui` is allowed only in user-facing copy, in URL paths already published, in external contract field names quoted as string literals, and in already-persisted data values. Full rule with examples: `.claude/skills/cdv-plan-feature/references/naming-language.md`.

**Ephemeral files:** the root files the skills write and never commit (the profile's `ephemeral_patterns`: `*-pr.md`, `QA-*`, `STATE-*`, `HANDOFF-*`, `handoff-*`, `decisions-*`, `delivery-*`, review directories) are ignored by git and deleted at the wrap-up.

**Subagents:** every `Agent`/`Task` call names `model` explicitly — `sonnet` for Explore, executors and mining or analysis agents; `opus` for the verifier and for judgement calls; never Fable in a subagent.

**Personal data:** e-mail addresses appear in clear as a work identifier in debugging, QA and reports; other personal data stays masked.

**When finishing a task, state:**
- What changed and which files are central to the change
- Which business rules were assumed
- The functional impact and risk of any behavior change
- Which validations were executed or remain pending
