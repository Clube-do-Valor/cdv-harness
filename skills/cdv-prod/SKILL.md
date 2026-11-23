---
name: cdv-prod
description: >
  Answer a question about production the safe way - registry data from the local copy first,
  production itself only for run history, the state after a deploy and the environment, always
  through `.claude/harness/bin/prod-read` (one SSH hop into the application container on a
  read-only session, rows capped, every call logged); and a production write, when one is needed,
  only through its protocol (one question per mutation, guarded by the old value, the row printed
  before and after, never unattended). Triggers on "olha em produção", "check production",
  "confere no banco de prod", "o job rodou hoje?", "subiu a migration?", "what does prod say", a
  production step of cdv-rollout, or a production read inside cdv-debug. Do NOT use for local data
  questions the local copy answers, for a deploy (never), or for a smoke test that writes
  (production-affecting paths are the developer's).
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Production

Production is read through one script and written only through one protocol. "Read only" does not
rest on care: the script opens a read-only session before the probe, caps the rows and logs the
call, and the `prod-ssh` hook refuses any other SSH to a production host.

## Step 0 - Load the profile and the extension

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its
   keys win). Stop when `profile.yaml` is missing: this skill runs only inside a consumer
   repository.
2. Read `<profile.extension_dir>/cdv-prod.md` when it exists (which tables hold what, the local
   copy and how fresh it is, the traps). The extension only adds or restricts; where it and this
   skill differ, the extension wins for this repository.
3. Read [production-safety.md](../../harness/references/production-safety.md).

Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the
repository does not have that thing: skip the step that needs it. With `profile.prod_ssh_target`
`none`, production is not read from this repository: answer from the local copy and say so.

## Step 1 - Where the answer is

Answer a question about registry data (a record, its fields, who changed it, counts) from the local copy first: the local database holds a production dump, so check its freshness (the newest `updated_at` of the table, or the dump's date the extension names) and say how old the answer is.

Read production only for run history (jobs, scheduled runs, failed jobs), state after a deploy (migrations, the running version) and environment (configuration, the log), or when the local copy is older than the question allows - and say why in one line before the read.

## Step 2 - Read through `prod-read`

Every production read is one call of `.claude/harness/bin/prod-read` from the repository root:

| Call | Reads | Exit |
| --- | --- | --- |
| `prod-read --probe <file>` | a PHP probe for the application's REPL | `0` read, `2` a key missing (no connection), `3` a read the script does not do, `4` SSH failed or timed out |
| `prod-read --migrate-status` | the migration status | same |
| `prod-read --failed-jobs` | the failed queue jobs | same |
| `prod-read --job-runs <name>` | the recorded runs of the jobs whose name holds `<name>` (`profile.prod_job_runs_table`) | same |
| `prod-read --logs <pattern>` | the log lines that hold `<pattern>`, newest first | same |

- The script connects to `profile.prod_ssh_target`, enters `profile.prod_app_container` as
  `profile.prod_exec_user`, sets `profile.prod_readonly_connection` when the repository has one,
  runs `profile.prod_session_readonly_sql` (default `SET SESSION TRANSACTION READ ONLY`) and then
  the probe; it prints at most `profile.prod_row_cap` lines, stops after
  `profile.prod_timeout_seconds` and appends one line per call to `profile.prod_log`.
- Write the probe in the work folder (never committed): no `<?php`, no `use` lines (full class
  names), one `echo` per row with only the columns the question needs.
- Never print a secret or a token: print its length, or `set` / `empty`. Personal data stays in
  the output only when the question needs it, and never goes into a committed file.
- Never `ssh` to a host of `profile.prod_hosts` any other way, and never retry a refused read in
  another shape: a read the script does not do (exit `3`) is a question for the developer.

## Step 3 - A production write

A production write is one question per mutation, labelled as production (`[PRODUCTION]` at the start of the question), with the statement, the row it changes and what else it triggers in the question.

1. Guard the statement by the old value: the `where` holds the key and the value read just before (`->where('id', 42)->where('status', 'draft')`), so a row that changed since the read is not touched.
2. Print the row before and after the change inside the same snippet (`dump($before)`, the update, `dump($after)`), and the number of rows changed.
3. `prod-read` cannot write: the developer runs the approved snippet in their own terminal and pastes the output back, and you check the row after against what the question promised.
4. Record the write as one comment on the card through `cdv-notion-ticket` (what ran, when, by whom, the result: what changed, the old and the new value), never as a line in its body.

Never run a production write in an unattended mode (`plan-then-build` or `autonomous` with the developer away): stop at the question and wait. One answer covers one mutation; the next one is asked again.
