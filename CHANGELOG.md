# Changelog

## Unreleased

- **New skill `cdv-notion`:** Notion through the public REST API with one token on the machine, no Notion MCP. The bundled client `skills/cdv-notion/scripts/notion` (Python standard library) reads a page or a data source from any reference form (url, id, the collection form of a data source id, ticket key, data source title), writes properties in the short format the MCP used (`--set 'Status=Done'`, `date:<Prop>:start`, `user://`, `__YES__`), edits the body in Notion-flavored Markdown (`--edit OLD NEW`, `--append-file`, `--replace-file`), queries with a readable `--where` condition compiled into the API filter (`--count`, `--group-by`), searches, comments (signed with the name of `me`), uploads and downloads files, finds people, and runs `doctor [--write-check]`. It waits out 429s and never resends a create that ended in 502, 503, 504 or a timeout. Token: `$NOTION_API_TOKEN`, the keyring (`service notion-api`), then `~/.config/notion/credentials`; cache in `~/.cache/cdv-notion/`, settings in `~/.config/cdv-notion/config.json`. `sync --user` installs it too.
- `cdv-notion-ticket`, `cdv-open-pr`, `cdv-debug` and the references `ticket-format.md` and `notion-ticket-template.md` name the `cdv-notion` commands where they named Notion MCP tools; the templates point at the skill's markdown reference.
- `prod-read` runs `docker exec` with `-e HOME=/tmp`: an exec user with no writable home (`www-data` in a PHP image) made tinker exit `1` on "Writing to directory .config/psysh is not allowed", so every read failed with exit `4`.
- **New skill `cdv-kickoff`:** one command starts a feature: `scripts/propose_profile.py` proposes the run profile (track, mode, chain, workspace, roles, optional steps) from the request's signals, `run_profile.py validate` gates it, and the chain runs through `run_status.py`, `role_target.py` and `brief.py` with no prompt per stage. The run profile (`run.yaml`, or `RUN-<slug>.yaml` with no plan) and its work folder are git-ignored.
- **Optional steps of a kickoff run:** `skills/cdv-kickoff/references/optional/` holds the recipes `slack-draft`, `mock-before-after`, `blind-judges` and `validation-page`, each with Signal, When it runs, Recipe, Output and Stop.
- **New skill `cdv-qa`:** the agent runs the browser QA itself, records each step with its screenshot (`scripts/qa_report.py add|render`, the list goes into the final report) and keeps the external test records it creates in `scripts/qa_manifest.py add|done|pending`, deleting them at the end. `step-by-step` mode hands each step to the developer.
- **Delivery:** `cdv-finalize/scripts/watch_pipeline.py --branch <b> --timeout <s>` waits for the pipeline through `profile.pr_cli` (exit `0` green, `1` red naming the failed step, `2` no pipelines command, `3` timeout); `cdv-finalize` fixes a red pipeline in the same pull request at most twice. The bundled Bitbucket client gains `bb pipelines --steps <build>`. `cdv-notion-ticket` follows the layout of the project's three most recent cards, links the PR both ways and sets `ticket_status_pr_open`. New skill `cdv-rollout`: the merged and deployed statuses, then the production steps one per question. On a big track the kickoff writes the approved plan to a page under the project in the ticket system, never to a commit.
- **Removed skills:** `cdv-plan-feature`, `cdv-flows` and `cdv-interactive-qa`. `sync` deletes them from each repository. Planning is `tlc-spec-lean`, started by `cdv-kickoff`; the browser QA is `cdv-qa`. A consumer moves what its extension files for the three skills held, and drops every pointer to them from its instructions file, rules and skills index.
- **Shared references:** `references/naming-language.md`, `module-opt-in.md`, `production-safety.md`, `worktree-safe-commands.md` and the new `qa-fixtures.md` are vendored to `.claude/harness/references/`. A repository's own notes for one of them live in `<extension_dir>/references/<name>.md` (the headings "Module opt-in", "Production safety" and "QA authoring" of the extension of the removed planning skill move there).
- **`tlc-spec-lean` is vendored into repositories again** (`"vendor": false` removed from `third-party.json`), so a child on any account loads it from the checkout; `sync --user` still installs it per user.
- **Hooks:** `hooks/require-model`, `hooks/prod-ssh` and `hooks/suite-lock` are vendored to `.claude/harness/hooks/`, and `sync` merges `settings/hooks-core.json` into `.claude/settings.json` under `hooks.PreToolUse` (the repository's own hooks stay; an entry the core drops is removed). Each core hook command is `"$CLAUDE_PROJECT_DIR"/.claude/harness/hooks/<name>`, so a hook still runs after the session's shell changes directory; `sync` refuses any other command shape in `settings/hooks-core.json`. The lock records the merged entries under the new key `hooks`; `schema` stays `1` and `verify.sh` is unchanged.
- `sync` vendors every `bin/` script but `harness` to `.claude/harness/bin/` (for `prod-read`).
- **Production reads:** `bin/prod-read` (vendored to `.claude/harness/bin/prod-read`) runs a probe or one of four fixed reads (`--migrate-status`, `--failed-jobs`, `--job-runs <name>`, `--logs <pattern>`) through one SSH hop into the application container, after `DB::setDefaultConnection` (when `prod_readonly_connection` is set) and the read-only session statement; output capped at `prod_row_cap`, stopped after `prod_timeout_seconds`, one line per call in `prod_log` (required). New optional key `prod_job_runs_table`. New skill `cdv-prod`: the local copy first, production for run history, deploy state and environment, and the production write protocol.
- The house block no longer asks whether to search the docs before a feature or whether to update documentation after one: search first, always; every child names its model from the role table; Fable only when the user names it; plan with `tlc-spec-lean`; start a feature with `cdv-kickoff`.
- `profile.schema.yaml`: the role lines (`role_orchestrator` … `role_judge`), the key families `account_<name>` and `model_<alias>`, `delegate_tool`, the `prod_*` keys, `qa_side_stack_script`, `qa_test_marker` and the three `ticket_status_*` keys, all optional.
- `release --adjust` cuts the next patch tag inside the 7-day window of the last tag.
- The core deny list also covers `.claude/harness/hooks/`, `.claude/harness/references/` and `.claude/skills/tlc-spec-lean/`.
- `cdv-code-review`'s `verify-anchors.sh` reads the cited file's length from `<head-ref>` instead of the working tree, so `verify-anchors.sh <dir> <base> <branch>` works without a checkout, as the PR-number mode promises. Before, every anchor reported `out-of-file` when the working tree was on another branch.
- `sync` also stages `.claude/harness/profile.yaml` with `git add -f`, so a repository that ignores `.claude/` commits its profile with the first sync. `profile.local.yaml` stays out of git.

## v0.2.1

- `tlc-spec-lean` is installed per user only (`"vendor": false` in `third-party.json`): `sync` no longer copies it into repositories, and `sync --user` still installs it.

## v0.2.0

- Three third-party skills copied from the Tech Leads Club catalog: `tlc-spec-lean`, `create-adr` and `modular-design-principles` (CC-BY-4.0, see `THIRD_PARTY.md`). They are vendored into consumers like the house skills and installed per user by `sync --user`.
- `bin/harness third-party` copies new upstream versions listed in `third-party.json`; `--check` only reports them. A weekly workflow runs it and opens a PR.
- `sync` vendors every skill under `skills/`, not only `cdv-*`.

## v0.1.0

First release.

- 17 house skills: `cdv-plan-feature`, `cdv-finalize`, `cdv-open-pr`, `cdv-code-review`, `cdv-pr-review`, `cdv-apply-review`, `cdv-debug`, `cdv-interactive-qa`, `cdv-notion-ticket`, `cdv-grilling`, `cdv-grill-me`, `cdv-research-round`, `cdv-frontend`, `cdv-factory-small-feature`, `cdv-factory-finalize`, `cdv-handoff`, `cdv-flows`. Each reads the repository profile in its step 0 and its optional extension.
- House rules `cdv-config-env`, `cdv-tests` and `cdv-migrations`, the house instructions block and the core deny list (production-affecting command families, inline PHP, and Edit on the vendored paths).
- `profile.schema.yaml`: the variables a consumer declares.
- `bin/harness` with `sync`, `sync --user`, `verify`, `propose`, `catalog`, `release`, `lint` and `scan`; `bin/verify.sh` as the offline CI gate.
- Generated `CATALOG.md` and `registry.json`.
