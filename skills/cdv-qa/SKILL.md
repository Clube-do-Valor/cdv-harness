---
name: cdv-qa
description: >
  Browser QA of a feature branch, run by the agent itself - open the local application (or the
  worktree's side stack), do each step the plan promises the way a user would, take a screenshot of
  what it saw, record every step with qa_report.py and put the rendered list in the final report;
  external test records are registered in qa_manifest.py before they are created, named with the
  repository's test marker and deleted at the end. A step-by-step mode hands each step to the
  developer instead. Triggers on the `qa` stage of a cdv-kickoff run, "testa no navegador", "faz o
  QA", "run the browser QA", "test it in Chrome". Do NOT use for writing unit or feature tests
  (the builder's work), for a design judgement of a screen (the repository's design skill), for a
  production smoke test (never), or for code review (cdv-code-review).
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Browser QA

The agent tests the feature in the browser and shows what it saw. You drive the browser yourself and never ask the developer to test by hand, except in `step-by-step` mode. Every step leaves a line
and a screenshot; the final report carries the list, so the pull request shows the QA without a
question.

The scripts live in `.claude/skills/cdv-qa/scripts/` and run with `python3` from the repository
root. Both write in the run's work folder (`.specs/features/<feature>/`, or `RUN-<feature>/` with no
plan), found from the run profile; `--dir <folder>` names another one.

| Script | Does | Exit |
| --- | --- | --- |
| `qa_report.py add --what <text> --expected <text> --result pass\|fail --screenshot <path>` | records one step | `0`, `2` a field missing or bad, naming it |
| `qa_report.py render` | the Markdown list of the steps, one line each, with its image link | `0`, `2` no work folder |
| `qa_manifest.py add --system <s> --type <t> --id <id> [--name <name>]`, `done ...`, `pending` | the external records of the run and which are still to delete | `0`, `2` a field missing, naming it |

## Step 0 - Load the profile, the extension and the run

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its
   keys win). Stop when `profile.yaml` is missing: this skill runs only inside a consumer
   repository.
2. Read `<profile.extension_dir>/cdv-qa.md` when it exists (the repository's QA stack, login,
   data and traps). The extension only adds or restricts; where it and this skill differ, the
   extension wins for this repository.
3. Read the run profile (`.specs/features/<feature>/run.yaml`, or `RUN-<feature>.yaml`): `qa`,
   `mode` and `workspace` decide the steps below. Outside a kickoff run, ask the developer which
   `qa` value applies and pass `--dir` to the scripts.
4. Read [qa-fixtures.md](../../harness/references/qa-fixtures.md) and
   [production-safety.md](../../harness/references/production-safety.md) before writing a step.

Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the
repository does not have that thing: skip the step that needs it.

## Step 1 - Reach the application

- With `workspace: main`, the application of the main checkout is the one under test, at
  `profile.qa_url`.
- With `workspace: worktree`, start `profile.qa_side_stack_script` from the worktree and read the address and the login link it prints. The final report gives the address and a login link of the side stack, so the developer can open what you tested.
- When `profile.qa_side_stack_script` is `none`, ask to bring the branch to the main checkout (with its consequence: the main checkout leaves the branch it is on) and wait for the answer; never switch the branch of a checkout another session works in.

Log in through the login link or the route the extension names; never type a password, and never
ask for one.

## Step 2 - Write the steps

From the plan's criteria (or, with no plan, the request), write the steps a user would take, each
with what to do and what to expect, in the language of the screen. Every step names a real local
fixture the way the screen names it and the numbers it should show
([qa-fixtures.md](../../harness/references/qa-fixtures.md)). A step that writes to a system shared
with production is `[PRODUCTION-AFFECTING]`: Step 4 decides whether it runs.

## Step 3 - Run them in the browser

You drive the browser yourself, with the browser tools of the host, one step at a time:

1. Do the step as the user would: click, type, wait for the screen to settle.
2. Save a screenshot of the state the step checks in the work folder (`shots/<n>-<slug>.png`).
3. Record every step with `qa_report.py add` the moment its screenshot is saved: `--what` the
   action, `--expected` what the plan promises, `--result pass` or `--result fail`, `--screenshot`
   the file. A step that fails is recorded as `fail` with what you saw in `--note`; go on with the
   steps that do not depend on it.

In `step-by-step` mode, hand each step to the developer (what to do and what to expect) and record their answer as the result with `qa_report.py add`, with the screenshot they send or the one you take of the state they describe.

## Step 4 - External records

The only external records a run creates without asking are its own test records
(`unattended: own-test-records`).

- With `qa: browser-external-test-records`, register each external record with `qa_manifest.py add` before you create it: `--system`, `--type` and, until the system gives an id, the name it will carry as `--id`; once created, `add` again with the real `--id` and `--name <that name>`.
- Name every record you create with `profile.qa_test_marker`, so it can be found and deleted even when the manifest is lost.
- Before a step that changes an external record, name the automations that change triggers (workflows, webhooks, notifications, syncs); if one reaches a person or a live automation, stop and ask.
- At the end, delete every pending record that `qa_manifest.py pending` lists, and close each one with `qa_manifest.py done` once its system confirms the deletion.
- A record that cannot be deleted stays pending, and the final report lists it with its system, type and id.

With `qa: browser-local`, no step creates or changes an external record: a step that would is
reported as not run, with the reason.

## Step 5 - The final report

Put the output of `qa_report.py render` in the final report of the run, unedited, followed by:

- the address and the login link, when the QA ran on a side stack;
- the output of `qa_manifest.py pending`, or "no external record left";
- each failed step in one line with what you saw, so the fix child can start from it.

The orchestrator copies the list into the pull request description; the screenshots stay in the
work folder, which is never committed.
