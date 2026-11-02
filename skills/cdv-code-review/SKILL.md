---
name: cdv-code-review
description: >
  Single-pass code review of a feature branch, emitting paste-ready inline-comment files under
  <profile.pr_review_dir_prefix>[TICKET]/ (prose in the repository's UI language, verified file:line
  anchors, _summary.md + INDEX.md). Triggers on 'revise esse PR', 'gera os comentários do code review',
  'review my branch before I open the PR'. Read-only — never edits source, never posts. Do NOT use for
  the multi-agent protocol ("review PR with subagents" → cdv-pr-review), debugging (cdv-debug),
  planning (cdv-grilling/cdv-plan-feature), or PR/commit generation (cdv-finalize).
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Code Review

Generates grounded, paste-ready inline-comment files for a feature branch. Read-only by design — sits between implementation (`cdv-plan-feature` execution / `cdv-finalize`) and the human opening the PR on the host.

**Two destinations for the output — feeding `cdv-apply-review` is the common one.** The review directory (`<profile.pr_review_dir_prefix><TICKET>/` at the repo root; "the review directory" below) is most often consumed by `cdv-apply-review` (triage + fixes on the implementation branch); pasting the files as PR comments is optional. The typical rhythm for risky or large implementations: implement in one session → run this review in a **fresh session** (a reviewer without the implementer's context and biases) → back in the execution session (the same one that implemented), run `cdv-apply-review` referencing the generated directory.

## Step 0 — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-code-review.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

Host-specific steps (reading a PR by number, pasting the comments) are in `references/vcs-<profile.vcs_host>.md` — read that file when a step below points to it.

## Operating principles

- **Read-only.** Never edits source, never pushes, never posts to the PR host. The only writes are the comment files under the review directory at repo root. Facts may be probed with read-only one-line REPL queries (`profile.cmd_tinker`, `--execute` style), never writes; a probe longer than one line is asked for first.
- **Pre-existing review directory = ask, never overwrite.** If the review directory already exists (this skill's or `cdv-pr-review`'s output), load its findings as existing comments and ask whether this run is a *continuation* (only new findings, skip covered `{path,line}`) or a *re-review* (archive the old directory to `<profile.pr_review_dir_prefix><TICKET>-prev/` first). Silently clobbering the other skill's output is forbidden.
- **Evidence over hypothesis.** Every cited `file:line` is verified against the real source via [scripts/verify-anchors.sh](scripts/verify-anchors.sh) before any comment file is written. Wrong line = wrong comment.
- **Repo conventions are the judgement basis.** The repository's instructions file (`profile.instructions_file`, already in context), and the path rules in [.claude/rules/](../../rules/) whose `paths:` match the diff — area cards (`profile.area_cards_glob`) included. Read the matching rule files explicitly: a rule loads on its own only when a matching file is read, and a review starts from the diff. Generic framework idioms are not the standard — these are.
- **Findings as facts, not weighed choices.** Each `Fix sugerido:` is a single recommendation backed by a doc, commit, or PR reference. No A/B menus.
- **Tests in the same PR is a hard rule.** New behavior/wiring/validation/API surface without tests in this branch is `⚠️ Potential issue | 🔴 High`. "Tests in follow-up PR" is a blocker, never a nitpick.
- **PII discipline.** PII over-fetch or PII in logs/payloads is `⚠️ Potential issue` (security). Never echo an end user's personal data in the comment prose — use placeholders or local-id refs. An e-mail address used as a work identifier (to name the account in a reproduction) is written in clear; other personal data stays masked.
- **Prose in `profile.language_ui`, English Prompt for AI Agents.** Bold category, bold severity, bold title, woven `Fix sugerido:`, then `🔬 Como reproduzir` (screen-only), then a plain `🤖 Prompt for AI Agents` section (no `<details>`/`<summary>` wrapper) — single canonical format per [references/comment-format.md](references/comment-format.md).
- **Three layers, always.** Every finding is written so that someone who knows the product but did not read the code understands it first, can see it on the screen second, and an agent can fix it third. The doctrine, the chat presentation and the exemplar live in [references/explain-findings.md](references/explain-findings.md) — load it before Step 8.
- **Fresh refs before any diff.** The branch under review may be behind its remote and the local default branch is possibly far behind `origin/<profile.default_branch>`; both have produced reviews of the wrong scope. Step 2 fetches and computes scope against `origin/<profile.default_branch>` only.
- **One finding per file.** Paste works because each comment file is self-contained markdown. Consolidated multi-section documents fall into a code block on paste and render raw.

## When to use

- The user wants inline review comments on a feature branch before opening the PR.
- The user wants a second, deeper, repo-grounded review after the automatic reviewer of the host ran.
- Trigger phrases: "revise esse PR", "gera os comentários do code review", "code review com comentários inline", "review the branch with inline comments", "gera review pro PR", "review this branch", "review my branch before I open the PR", "preparar comentários antes do PR".

## When NOT to use

- The user asks for the **multi-agent protocol** ("cdv-pr-review", "review PR with subagents", "multi-agent code review") → use `cdv-pr-review`. This skill is the single-pass lane; both emit the same review-directory format.
- Bug investigation from a stack trace, error-tracker issue, or application log → use `cdv-debug`.
- Planning a not-yet-implemented feature → use `cdv-grilling` (decisions) → `cdv-plan-feature` (plan).
- Generating the PR description or atomic commits → use `cdv-finalize`.
- Implementing fixes from this review's findings → hand off to `cdv-apply-review` (Step 10). Never edit source from inside this skill.
- Auto-posting to the PR host — out of scope by design. The user pastes manually or runs the API path themselves.

## Workflow

### Step 0 — Ensure feature branch and resolve ticket id

Confirm the current branch is a feature branch (a prefix from `profile.branch_prefixes`). Run `git branch --show-current`:

- If on `profile.default_branch` or any protected branch: refuse and ask the user to switch first. This skill reviews work that is already on a feature branch; it never creates one.
- Otherwise: resolve the ticket id with [scripts/resolve-ticket-id.sh](scripts/resolve-ticket-id.sh), which extracts a key matching `profile.ticket_key_pattern` from the branch name and falls back to a positional override. If neither resolves, ask the user once for the ticket id before any other step.

**Whose branch is it?** Ask once, in the same turn as the ticket id when that is asked: *"Branch sua (tem sessão que implementou) ou de terceiro (PR de outra pessoa)?"* Skip the question when the answer is evident from the conversation (the user names the author, or this session's history shows the implementation). The answer changes Step 10: a third-party branch gets the comment files and the chat explanation, and is **never** routed to `cdv-apply-review` — that skill only makes sense when a session that implemented the branch exists to triage and commit on it. Record the answer for Step 10.

### Step 1 — Load base context (always, parallel)

Read in parallel the base docs named under **Repo conventions are the judgement basis** (operating principles above).

These inform every finding. Never review without them in context.

### Step 2 — Preflight, then compute diff scope

**Preflight (mandatory, three commands, before any diff):**

1. `git fetch origin` — refresh every ref. A review computed against stale refs is a review of the wrong code; stale refs produce a review of the wrong tree.
2. `git rev-list --count HEAD..origin/<branch>` — when `> 0`, the local branch is behind its remote: fast-forward it (`git merge --ff-only origin/<branch>`) before reviewing. If the fast-forward is not possible (local commits not on the remote), surface both counts and ask which tree to review.
3. Scope is **always** computed against `origin/<profile.default_branch>`, never against the local default-branch ref — the local ref is possibly far behind and turns the diff into hundreds of unrelated files.

Then run in parallel: `git diff origin/<profile.default_branch>...HEAD --stat`, `git diff origin/<profile.default_branch>...HEAD --name-only`, `git log --oneline origin/<profile.default_branch>..HEAD`. Every later mention of `<default-branch>...HEAD` in this skill and in [scripts/verify-anchors.sh](scripts/verify-anchors.sh) means `origin/<profile.default_branch>...HEAD`.

For PR-number mode (the user provides a PR number as arg): read the PR as `references/vcs-<profile.vcs_host>.md` says (head branch, base branch, changed files), then `git fetch origin <head-ref>` and run the diff against `origin/<base-ref>`.

**Existing review directory.** If the review directory already exists, ask now (not at Step 8) whether this run is a continuation or a re-review, per the operating principle — and in a re-review, state explicitly which old findings the current tree already resolved instead of repeating them.

### Step 2b — Cite `cdv-frontend` when frontend files are present

If `git diff origin/<profile.default_branch>...HEAD --name-only` includes any frontend file (`.vue`, `.ts`, or composable files under `<profile.app_dir>/resources/js/`), load the `cdv-frontend` skill and apply its **Hard Rules Registry (canonical)** as additional review criteria — do not re-enumerate the rules here; the loaded skill is the single source of truth for them.

These frontend checks are additive — run them alongside all other review dimensions, not instead of them.

### Step 3 — Read the area cards the diff touches

An area card (a file matching `profile.area_cards_glob`; skip this step when that is `none`) is a path rule: list the cards and read every one whose `paths:` match a file in the diff. Its lines are the external contracts, agreements and invariants (each with its test) the change must keep. The code stays the source of truth.

### Step 4 — Map the touched code (delegate to Explore)

Spawn an isolated Explore subagent:

```
Task(
  subagent_type="Explore",
  model="sonnet",
  description="Map touched code for <feature>",
  prompt="In the repository root <repo root>, for these changed files <list>:
    (1) controllers/services/jobs/commands/models/enums under <profile.app_dir>/app/ — paths + 1-line purpose;
    (2) frontend files under <profile.app_dir>/resources/js/ (the features directory and any legacy one);
    (3) existing tests under <profile.app_dir>/tests/ that touch this area (or note absence);
    (4) external integrations involved + their api-client path (the extension names them);
    (5) any sibling feature with the same UX/domain shape to reference.
    Return a concise file map (paths + 1-line purpose). Skip irrelevant scaffolding."
)
```

If the diff touches multiple distinct areas, dispatch multiple Explore agents in parallel. Use the returned map to inform findings — never review from generic framework assumptions.

### Step 5 — Apply the alignment checklist

Walk the diff against [references/alignment-checklist.md](references/alignment-checklist.md). Six passes:

1. **Repo hard rules** — backend: thin controllers, logic in services, jobs delegate to services. Frontend: apply the `cdv-frontend` Hard Rules Registry (loaded in Step 2b when frontend files are present) — do not re-list its rules here.
2. **PII scan** — PII over-fetch in payloads, PII in logs, missing PII-guard tests.
3. **Tests-with-PR rule** — new behavior without tests in this branch → high.
4. **Production-impact heuristics** — smoke tests against real external endpoints → high.
5. **Layer drift heuristics** — fat controllers, models with business logic, jobs not delegating, missing enums for domain states.
6. **Naming language** — identifiers in the wrong language, or mixed-language identifiers, introduced by the diff, outside the four allowed cases.

Produce a draft list with `path:line`, severity, category, one-line title for each finding.

### Step 6 — Map findings to display labels

Use [references/severity-category-mapping.md](references/severity-category-mapping.md) to convert each draft finding's severity (high/medium/low) and category (bug/security/perf/maintainability) to its display label (`⚠️ Potential issue` / `🛠️ Refactor suggestion` / `🧹 Nitpick`) and severity dot (`🔴` / `🟠` / `🟡`).

### Step 7 — Verify anchors (mandatory gate)

Before writing any comment file, draft them in a scratch directory (or directly to the review directory with the intent to delete-on-fail) and run:

```
./.claude/skills/cdv-code-review/scripts/verify-anchors.sh <profile.pr_review_dir_prefix><TICKET>
```

The script extracts every `path:line` cited in the draft markdown and asserts:

- The file is in `git diff origin/<profile.default_branch>...HEAD --name-only`.
- The cited line is a `+` line in the diff hunk (added or modified), not a context line.
- The line is within the file's current length.

Non-zero exit → fix the anchors before proceeding. A wrong anchor renders as an unrelated inline comment and erodes trust in the whole review.

### Step 8 — Emit per-comment files

Write the comment files under the review directory at repo root (untracked, like `<slug>-pr.md`; it matches `profile.ephemeral_patterns` and is never committed). For each finding, one file following the template in [references/comment-format.md](references/comment-format.md). **Read two of the golden examples first** — the extension lists the exemplars (`<profile.extension_dir>/cdv-code-review/examples/`): real, praised findings with all three layers, plus older per-category files that show the shape of each category label but predate the `🔬 Como reproduzir` section:

- **First line of every per-finding file is the anchor header** `<!-- ANCHOR: path/to/file.ext:LINE -->` (HTML comment, invisible on the host, consumed by `verify-anchors.sh`). `_summary.md`, `INDEX.md`, and `nitpicks.md` skip the anchor header.
- Naming: `B<n>-<slug>.md` for high-severity blocking issues that prevent merge, `H<n>-/M<n>-/L<n>-<slug>.md` for the remaining severities, `nitpicks.md` for the grouped nitpicks file (one comment containing all nitpick bullets — never inline).
- Prose in `profile.language_ui`; bold title (no `file:line` in the title — the anchor handles it).
- `Fix sugerido:` woven inline as a single recommendation, citing the instructions file / the matching `.claude/rules/*.md` / a prior commit / a related PR when relevant.
- `**🔬 Como reproduzir**` on every 🔴/🟠 finding (and on 🟡 with a visual symptom): screen-only steps on a real case from the local QA environment (`profile.qa_env`) — URL on `profile.qa_url` with real ids, literal labels grepped from the `.vue`, numbers to note before acting, what changes vs what should, a restore step by screen gesture, `Quando acontece em geral:`. No REPL/console/SQL. When nothing is visible on screen, say so and name the condition under which the risk appears. Rules in [references/explain-findings.md](references/explain-findings.md).
- Prompt for AI Agents in English as a plain section — a bold `**🤖 Prompt for AI Agents**` header followed by a fenced code block, with no `<details>`/`<summary>` wrapper.
- Never echo an end user's personal data — use placeholders or local-id refs.

### Step 9 — Emit `_summary.md` and `INDEX.md`

`_summary.md` is the PR-level comment (not inline): risk badge, walkthrough paragraph, counts by severity. `INDEX.md` is the anchor table mapping each comment file to its `file:line`, category, and severity, plus the paste guidance (see [references/comment-format.md](references/comment-format.md) and `references/vcs-<profile.vcs_host>.md`): paste one file at a time into an empty comment editor, with the host's fallback if the paste still falls into a code block.

### Step 10 — Present and hand off

**Present in chat per [references/explain-findings.md](references/explain-findings.md), never by pasting the files.** One block per finding, most severe first: **O problema** (three or four short sentences, no undefined term), **Como ver na tela** (the condensed Como reproduzir, or the plain statement that there is no visual symptom), **Recomendação** (one). Nitpicks as one bullet list. Then the summary table `ID | severidade | arquivo:linha | uma linha`, one sentence on which gates ran and their result, and the paste guidance.

Then route by intent — **but first by ownership** (Step 0):

- **Third-party branch:** the deliverable is the comment files and the explanation above. Do not offer `cdv-apply-review` (there is no implementing session to triage on). If the user wants a fix applied anyway, treat it as a new request outside this skill: a fresh branch from the remote branch, with the user deciding whether to push over the author's branch.
- **Own branch:** "vamos consertar X" / "aplica esse fix" / "implementa as correções" / "check each finding and act" → hand off to `cdv-apply-review` with the review directory as input (per-finding triage + commits on the same branch). Only a fix that outgrows finding size (new feature scope, schema change) routes to `cdv-plan-feature`.
- "finaliza" / "wrap up" → hand off to `cdv-finalize`.
- "investiga isso" / pasted stack trace → hand off to `cdv-debug`.
- Otherwise: stop. The user pastes the comments and continues on the host.

Never edit source from inside this skill. Producing a code fix here is a hard error — route it out.

## Output format

The canonical template, field rules, and anti-patterns live in [references/comment-format.md](references/comment-format.md). Do not deviate from it. The validated examples that illustrate each comment shape are listed by the extension (`<profile.extension_dir>/cdv-code-review/examples/`).

## Severity and category mapping

[references/severity-category-mapping.md](references/severity-category-mapping.md) is the single source of truth for category-label and severity-dot selection.

## Alignment checklist

[references/alignment-checklist.md](references/alignment-checklist.md) defines what the review actually scans for: repo hard rules, PII, tests-with-PR, production-impact, layer drift, naming language.

## Hard rules

- **Never write a final comment file before `verify-anchors.sh` exits 0.**
- **Never echo an end user's personal data** (national id number, full name with surname, personal e-mail, phone, address, ID document, birth date, and the fields the extension lists) in the comment prose. Use placeholders or local-id refs. (An e-mail address used as a work identifier is the one exception, per the PII principle above.)
- **Never auto-post to the PR host.** API posting is out of scope by design.
- **One finding per file.** Consolidated documents do not paste correctly into the host's comment editor.
- **Never edit source code.** Hand off to `cdv-plan-feature` for any fix work.
