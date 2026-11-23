---
name: cdv-rollout
description: >
  After a pull request is merged or deployed - close the card through cdv-notion-ticket (its closing
  and the status of that event, a comment per production step), then list
  the production steps the deploy does not run by itself (migrations run by hand, configuration,
  backfills, flags, a worker restart, a data fix) and take the developer through them one per
  question, each read through cdv-prod and each write through its protocol. Triggers on "mergeou",
  "merged", "foi pro ar", "deployed", "subiu em produção", "o que falta em produção?", "rollout
  dessa feature". Do NOT use to merge, tag or deploy (the developer does that, or says so
  explicitly), before the pull request exists (cdv-finalize), or for an investigation in
  production (cdv-debug with cdv-prod).
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Rollout

What happens after the pull request, on the developer's word. The card follows the events; the
steps the deploy does not run by itself are done one at a time, each one asked.

## Step 0 - Load the profile and the extension

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its
   keys win). Stop when `profile.yaml` is missing: this skill runs only inside a consumer
   repository.
2. Read `<profile.extension_dir>/cdv-rollout.md` when it exists (the repository's deploy, its
   tags and its production habits). The extension only adds or restricts; where it and this skill
   differ, the extension wins for this repository.

Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the
repository does not have that thing: skip the step that needs it.

## Step 1 - The event moves the card

When the developer says the pull request merged or deployed, call the closing moment of `cdv-notion-ticket`: `## Fechamento` with 1 to 3 items and the status of that event.

- The card is the one the pull request's `🏷️ Ticket` section links; with `profile.ticket_system`
  `none` there is no card. While the card lists a pull request of another repository that has
  not reached the same event, `cdv-notion-ticket` leaves the status and says which one it waits for.
- Only the developer's word starts a move: never infer a merge or a deploy from the branch, and
  never merge, tag or deploy yourself unless the developer says so for that action.
- After a deploy, confirm it landed before Step 2: `.claude/harness/bin/prod-read
  --migrate-status` through `cdv-prod` shows the branch's migrations as run.

## Step 2 - The production steps, one per question

Read the pull request's `## 🚀 Pós-deploy` section, the approved plan and the diff (migrations
the deploy does not run, configuration keys, backfill commands, feature flags, queue restarts,
scheduled jobs that need a first run, data fixes). Then list the production steps that are not automatic and ask them one per question, in the order they must run, each with its exact command and what it changes.

- Each question is labelled `[PRODUCTION]` and offers: run it now, the developer runs it, or
  wait (with the time to come back, when the step depends on a scheduled job).
- A read the step needs goes through `cdv-prod` (`.claude/harness/bin/prod-read`); a write goes
  through the `cdv-prod` write protocol: one question per mutation, guarded by the old value, the
  row printed before and after.
- After each manual production step, record it as one comment on the card through `cdv-notion-ticket` (what ran, when, by whom, the result), and write no line in the body.
- With the developer away, stop at the first step: production steps are never unattended.

## Step 3 - Report

One line per step: done, done by the developer, waiting (until when), or skipped (why), and the
card's status after the last move. A step left waiting is the first thing the next session asks
about.
