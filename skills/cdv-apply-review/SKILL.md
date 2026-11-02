---
name: cdv-apply-review
description: >
  Triage and apply code-review findings on a feature branch. Takes findings from a
  <profile.pr_review_dir_prefix><TICKET>/ directory, pasted review comments, or the host's automatic
  reviewer, verifies each against the current code, classifies real / falso-positivo / fora-de-escopo,
  decides act-or-not with a one-line justification per finding, and applies the accepted ones on the
  SAME branch with one commit per finding (or per logical group). Triggers on "check each finding
  against the code", "a code review has been made over this branch", "aplica os fixes do review",
  "triagem dos findings", "fix the nitpicks and commit", or the hand-off from cdv-pr-review /
  cdv-code-review. Do NOT use to produce a review (use cdv-code-review or cdv-pr-review), for fixes
  that grow beyond finding-sized scope (use cdv-plan-feature), or to push/merge (finalize owns the
  wrap-up).
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Apply Review

Owns what happens AFTER a code review: verify → decide → fix → commit, finding by finding.

## Step 0 — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-apply-review.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

**Typical rhythm:** the implementation happens in one session; the review (`cdv-code-review` or `cdv-pr-review`) runs in a **fresh session** (a reviewer without the implementer's context); then this skill runs back in the execution session (the same one that implemented) referencing the generated review directory (`<profile.pr_review_dir_prefix><TICKET>/` at the repo root) — that directory's most common destination is this skill, not the host's comment editor. Manual PR comments from a colleague or the host's automatic reviewer enter the same triage, pasted into the conversation.

## Operating principles

- **Same branch, always.** Review fixes land on the reviewed branch — never a separate fix/refactor branch.
- **Reason first, edit on "go".** The triage (verify + classify + recommend) is read-only. No code changes until the user approves the action set — a pasted review is a request for triage, not an implicit order to fix everything.
- **Every verdict is grounded.** A finding is only `real` or `falso-positivo` after reading the current source at the cited anchor — the code may have changed since the review, and reviewers hallucinate. Cite `path:line` in the verdict.
- **One commit per finding** (or per explicitly logical group). Conventional format with scope, per `cdv-finalize`'s cheatsheet. Never one blob commit "apply review feedback".

## Workflow

### Step 1 — Ingest the findings

Accept any of, in precedence order when several exist:

1. The review directory at repo root — read `INDEX.md` + the per-finding files (and `raw/*.json` when present).
2. Findings pasted in the chat (any format — `cdv-pr-review` output, the host's automatic reviewer, human comments).
3. A PR URL's comments pasted by the user.

Normalize into a working list: `id (B/H/M/L/N numbering when available) · path:line · title · severity · source`.

### Step 2 — Verify each finding against the current code (read-only)

For every finding, read the real source at the anchor (not just the diff) and classify. Facts may be probed with read-only one-line REPL queries (`profile.cmd_tinker`, `--execute` style), never writes; a probe longer than one line is asked for first.

- **`real`** — the defect exists in the current code as described.
- **`falso-positivo`** — the code does not have the defect (wrong reading, already handled elsewhere — cite where).
- **`obsoleto`** — was real, but the code changed since the review and it no longer applies.
- **`fora-de-escopo`** — real, but pre-existing on `profile.default_branch` or belonging to another branch/PR (evidence: `git log -S` / blame). Goes to an `Achados fora de escopo` note, not to this branch.

### Step 3 — Present the triage and decide

**Explain before asking.** For every `real` finding of Medium or higher, render one block per [explain-findings.md](../cdv-code-review/references/explain-findings.md) **before** the verdict table: **O problema** (short sentences, no undefined term, no metaphor), **Como ver na tela** (URL on `profile.qa_url` with a real case from the local QA environment and literal labels; when there is nothing to see on screen, say so instead of describing a query), **Recomendação** (one). The verdict and the "aplico?" question come after the reader understood the finding — a triage table alone is what produced follow-up turns asking what the problem is and where to see it. A REPL query (`profile.cmd_tinker`) never appears in "Como ver na tela"; it belongs to your own Step 2 verification, as a read-only one-liner.

Then render one table: `id · verdict · recomendação (agir / não agir) · justificativa em 1 linha · esforço (S/M/L)`. Then let the user drive in either mode:

- **Batch:** the user names the set ("M1, M2, M3, M5, L4") — confirm and proceed.
- **Interactive:** one finding per turn via AskUserQuestion, most severe first, each question carrying the finding's context + recommendation. Default to interactive when the user asked for it or the set has ≥3 Medium+ items with non-obvious trade-offs.

A finding the user declines gets its one-line reason recorded — the final report shows why each finding was or wasn't acted on.

### Step 4 — Apply and commit, finding by finding

For each accepted finding, in severity order:

1. Apply the minimal fix for THAT finding only. If the fix reveals a larger problem (schema, contract, feature gap), stop and route to `cdv-plan-feature` — do not grow the fix silently.
2. Gates per fix, run where `profile.commands_run_on` says (through `profile.cmd_container_exec` when it is `container`): targeted backend tests (`profile.cmd_test_backend` with `profile.cmd_test_backend_filter`), targeted frontend tests (`profile.cmd_test_frontend`) when the fix touches the frontend, and the backend formatter limited to changed files (`profile.cmd_format_backend`). A fix that changes behavior ships its test adjustment in the same commit.
3. Commit: `<type>(<scope>): <what the fix does>` — Conventional Commits in English with a scope, no `Co-Authored-By` trailer; the message describes the change, not "address review comment". The review directory is an ephemeral root file (`profile.ephemeral_patterns`): never stage it. Groups only when the user approved the grouping in Step 3.

### Step 5 — Close

Report: table `finding → verdict → decision → commit hash (or reason not acted)`, the `Achados fora de escopo` list, and residual findings left open on purpose.

**Then the divergence check — mandatory, before any hand-off offer.** Run `git rev-parse --verify origin/<branch>` and `git rev-list --count origin/<branch>..HEAD`. When the remote branch exists and the count is `> 0`, the fixes live **only locally while a PR is already open on them** — whoever approves that PR merges the pre-fix code and orphans these commits. Not pushing is the neutral choice only before a PR exists; after it, silence is what loses the work. State it and ask here, never deferring the question to a downstream skill:

> *"Os `<N>` commits de review estão só locais. O PR aberto ainda aponta para o código pré-fix — se for aprovado assim, esses commits ficam órfãos e as correções não entram. Faço `git push` agora?"*

Only with the remote in sync (or absent) does the close become a plain hand-off: offer `cdv-finalize` — the commit tree changed, so the PR description needs its refresh (finalize Step 8.5), and the push offer lives there.

## Composition

- `cdv-pr-review` / `cdv-code-review` — upstream producers of the findings; their review directory is this skill's native input.
- `cdv-plan-feature` — escape hatch when a fix outgrows finding size.
- `cdv-finalize` — downstream wrap-up (PR description refresh + push offer).
