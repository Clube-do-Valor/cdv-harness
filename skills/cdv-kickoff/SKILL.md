---
name: cdv-kickoff
description: >
  Start a feature or a fix larger than a one-liner with one command - read the request (a card link,
  a chat thread, a brief) and the repository, propose the run profile through its scripts (track
  small/medium/big, mode, chain, workspace, roles, optional steps), ask one question screen for
  medium and big work and none for small, write and validate the run profile, then run the chain
  (grilling, tlc-spec-lean plan, build and Verifier, review, fixes, browser QA, PR, pipeline, card)
  with no prompt per stage, stopping only where the profile says. Triggers on "start this feature",
  "kickoff", "/cdv-kickoff", "começa essa feature", "vamos fazer esse card", or a hand-off from
  cdv-debug or cdv-grilling. Do NOT use for a pure root-cause investigation with no build
  (cdv-debug), an open interview (cdv-grilling), a review of an existing branch (cdv-code-review), or
  a factory run (cdv-factory-small-feature).
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Kickoff

Turn a request into a written run profile, then run the chain from it. The profile decides; this
text holds the conversation. Every value of the profile comes from `propose_profile.py`, every gate
from a script's exit code, so a child started on any account works from the same file.

The scripts live in `.claude/skills/cdv-kickoff/scripts/` and run with `python3` from the
repository root:

| Script | Does | Exit |
| --- | --- | --- |
| `propose_profile.py --signals <file> [--answer key=value ...]` | the proposed run profile on stdout | `0`, `2` a signal missing or outside its set |
| `run_profile.py validate <file>` | one line per error, naming the key | `0`, `1` invalid |
| `run_status.py start\|done\|retry <stage> [--child <id>]`, `run_status.py show` | the order, the Verifier cap, the retries, one line per stage | `0`, `2` unknown stage, `3` refused |
| `role_target.py <role> [--run <file>] [--named-by-user]` | JSON target of a role: provider, model, effort | `0`, `2` a key not declared |
| `brief.py render <role>` | the brief a child starts from | `0`, `2` no run profile |

## Step 0 - Load the profile and the extension

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its
   keys win). Stop when `profile.yaml` is missing: this skill runs only inside a consumer
   repository.
2. Read `<profile.extension_dir>/cdv-kickoff.md` when it exists. The extension only adds or
   restricts; where it and this skill differ, the extension wins for this repository.

Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the
repository does not have that thing: skip the step that needs it.

## Step 1 - Read the request and the repository, fill the signals

Read the request whole (the card with its comments, the thread, the brief) and the code it touches.
Search the docs first, always. From what you read, fill the signals object. The signals are facts,
not questions: never put them to the developer as a form, and never decide a default yourself - a
signal you cannot settle from the evidence takes the value the evidence supports best, and the
profile itself always comes from `propose_profile.py`.

| Signal | Value |
| --- | --- |
| `feature` | the kebab-case English slug of the work |
| `intent` | `investigate` when the developer asked a question or a diagnosis, otherwise `build` |
| `files_estimate` | how many files the change touches, from the code you read |
| `migration` | `none`, `schema` (structure only) or `data` (rows change) |
| `new_screen`, `screen_audience_other` | a new screen; its users are not the developer |
| `changes_existing_screen`, `appearance_decision` | an existing screen changes; how something looks is to be decided |
| `external_integration` | the external systems the change talks to, as a list (empty when none) |
| `access_kernel`, `money_or_contract`, `one_way_door` | the change touches access or permission, money or a contract, or something hard to reverse |
| `repositories` | how many repositories change |
| `main_checkout_free` | the main checkout has no uncommitted work and no other session in it (`git status`, the process list) |
| `origin`, `waiting_reply` | `card`, `chat-thread`, `brief` or `direct`; someone is waiting for an answer |
| `owner_must_validate` | a business rule someone must confirm before the build |
| `no_precedent` | nothing like it exists in the code yet |

Save the object as `signals.json` in the work folder (Step 4) and keep it: it is the record of why
the profile is what it is.

## Step 2 - Propose

Run `python3 .claude/skills/cdv-kickoff/scripts/propose_profile.py --signals <work folder>/signals.json`.
Exit `2` names the signal that is missing or outside its set: fix the signal, never the script's
output. The output is the proposed run profile.

## Step 3 - The screen

State the track in one line first, with the two or three signals that set it, so a wrong track is
corrected before anything runs.

- On a small track, state the profile in one line (track, mode, workspace, QA, what happens next)
  and ask no question: go on to Step 4. The developer corrects it in a free message if it is wrong.
- On a medium or big track, ask one question screen of at most four questions, in a single
  `AskUserQuestion` call. Read [interview-principles.md](../cdv-grilling/references/interview-principles.md)
  before writing it. Ask about the values that change the run the most, in this order: `track`,
  `mode`, `workspace`, then the `optional` steps (multi-select) when any is proposed, or
  `builder_role` when none is.
- The recommended option of every question is the proposed value, labelled as recommended, with
  the signal behind it in one line.
- Each option carries its consequence in one line: what the developer gets, what it costs, what
  stops. A consequence you inferred from the code, and did not read or hear, says `inference` and
  names its evidence (`path:line`).
- The question carries its own context: the dialog may be the only thing the developer sees.

When the screen is answered, run `propose_profile.py` again with one `--answer key=value` per
answer that differs from the proposal (`--answer optional=slack-draft,validation-page` for a
list): the script derives every key that follows from an answer, so a changed track also changes
the mode, the rounds and the review. A free-text answer that names no profile value is a decision
for the plan: carry it into the grilling.

## Step 4 - Write and validate the run profile

When the screen is answered (or, on a small track, right after the one line), write the run
profile file from the script's output, unedited:

- with a plan (`planning: tlc-spec-lean`): `.specs/features/<feature>/run.yaml`, the work folder
  being `.specs/features/<feature>/`;
- without one: `RUN-<feature>.yaml` at the repository root, the work folder being `RUN-<feature>/`.

Both must be ignored by git (`git check-ignore <path>`); when one is not, stop and say which
pattern `profile.ephemeral_patterns` lacks.

Then run `python3 .claude/skills/cdv-kickoff/scripts/run_profile.py validate <file>`. No stage starts until `run_profile.py validate <file>` exits `0`; on exit `1` fix the line it names and validate again.

## Step 5 - Mode `investigate`

Load `cdv-debug` when the question is about a failure, and answer directly from the code and the
data otherwise. The run ends in a report (the stop `report`): no plan, no branch, no pull request,
unless the developer then asks for one - then start again at Step 1 with `intent: build`.

## Step 6 - Run the chain

You are the orchestrator. The chain is the run profile's `chain`, in its order:

| Stage | Who runs it | Role | Loads |
| --- | --- | --- | --- |
| `research` | a child | `research` | `cdv-research-round` |
| `grilling` | this session, with the developer | `orchestrator` | `cdv-grilling`, from the request and `signals.json` |
| `plan` | this session | `orchestrator` | `tlc-spec-lean`, Plan phase, ending at the stop `plan-approval` |
| `build` | a child (`builder: child`), or this session (`builder: inline`) | the run profile's `builder_role` | `tlc-spec-lean`, Checks and Build phases (with no plan: the change and its regression test) |
| `verify` | a fresh child, never the author | `verifier` | `tlc-spec-lean`, Verify phase |
| `review` | a fresh child | `reviewer` | `cdv-code-review`, bugs and regressions only |
| `fix` | a child | `fixer` | `cdv-apply-review`, one commit per finding |
| `qa` | a child | `qa` | `cdv-qa` |
| `finalize` | this session | `orchestrator` | `cdv-finalize`, which opens the pull request through `cdv-open-pr` |
| `watch` | this session | `orchestrator` | `watch_pipeline.py`, through `cdv-finalize` |
| `ticket` | this session | `orchestrator` | `cdv-notion-ticket` |

For each stage:

1. `run_status.py start <stage>`. Exit `3` means it is not this stage's turn, or the stage is
   skipped or capped: read `run_status.py show` and start the stage it says is next. A stage the run
   profile skips (`none` or `0`) never runs.
2. For a child: `role_target.py <role> --run <run profile>` gives the provider, the model and the
   effort; `brief.py render <role>` gives the brief, to which you add the stage's task in a few
   lines. Exit `2` names the profile key to declare: stop and ask for it, never guess a model.
3. Start the child with `profile.delegate_tool`, naming the provider, the model and the effort of
   the target. Where `profile.delegate_tool` is `none`, run each child stage as a native subagent on the model of the role (the `model` of `role_target.py`), never on an inherited model.
4. When the stage's result is back and its gate is green, `run_status.py done <stage> --child <id>`.
   With no review finding, record `fix` as started and done at once.

Rules of the run:

- In `plan-then-build` and `autonomous` mode, when a stage ends, start the next stage at once, without a prompt from the developer: the only waits are the run profile's `stops`.
- In `step-by-step` mode every stage is a stop: say what the stage did and what the next one will do, and wait for the developer.
- On a big track, write the approved plan to a page under the project in the ticket system (`profile.ticket_system`, the project the card belongs to), and never add it to a commit: the working copy stays in `.specs/features/<feature>/plan.md`, which git ignores, and the page is updated when the plan changes during the build.
- When the approved plan lists a one-way door in its `Landing` table, switch the run profile to `builder_role: builder_risk` (and validate it again) before you dispatch the builder.
- After a Verifier round with findings, a builder or fixer child closes them and `verify` starts again. When `run_status.py start verify` exits `3` and marks the stage `capped` with findings open, write each open item, tagged `defect` or `proof-gap`, into the pull request description and continue to the review.
- While the developer is away, stop and ask before any step that sends something to a person or a live automation, writes in production or deploys, whatever the mode and whatever the brief says.
- The only external records a run creates unattended are its own test records (`unattended: own-test-records`), named with `profile.qa_test_marker` and deleted at the end.
- A child that dies (memory, usage limit, restart) leaves its stage `running`: `run_status.py retry <stage> --child <new id>` and start one resume child with the status and its brief. `retry` takes only a `running` stage (a `done` stage or another Verifier round exits `3`), and the third retry of a stage exits `3`: stop and report.
- Each optional step of the run profile runs from its recipe in `references/optional/<step>.md` of this skill, at the point the recipe names: [slack-draft](references/optional/slack-draft.md), [mock-before-after](references/optional/mock-before-after.md), [blind-judges](references/optional/blind-judges.md), [validation-page](references/optional/validation-page.md).
- After every stage, print the stage's line of `run_status.py show`, so "where are we?" has an answer without a question.

The run ends at the pull request: its description carries the review result, the QA steps with
their screenshots, what stayed open after verification and the pipeline status. Merge, deploy and
production steps belong to `cdv-rollout`, after the developer says the pull request merged.
