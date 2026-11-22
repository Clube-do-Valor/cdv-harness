# Evaluation of cdv-refactor

Three small refactors in invented repositories, each run once with the skill and once without it,
by a subagent on claude-sonnet-5-5 (effort high), graded against assertions written before any run.
Skill version under test: 0.2.0.

## Layout

| Path | Holds |
| --- | --- |
| `<case>/prompt.md` | the run settings and the task prompt, as a user would type it |
| `<case>/case.yaml` | the expected outcome and the scaffold script |
| `<case>/graders/` | one assertion per file |
| `<case>/files/`, `<case>/place-files.sh` | the task repository; the script lays it out and commits it as the base |
| `workspace/checks/check_run.py` | the deterministic checks: `python3 check_run.py <case> <run repository>` |
| `workspace/iteration-1/<case>/<config>/` | per run: `outputs/` (final message, commit log, diff, check output), `grading.json`, `timing.json` |
| `workspace/iteration-1/benchmark.json`, `benchmark.md` | the aggregate, from skill-creator's `aggregate_benchmark` |

The "with skill" subject was told to read and follow `skills/cdv-refactor/SKILL.md`; the "without"
subject got the same prompt and nothing else. Each task repository carries a minimal
`.claude/harness/profile.yaml` (no extension, no roles) so that Step 0 of the skill does not stop.

## Cases

| Case | Tempts |
| --- | --- |
| split-invoice-report | splitting a class whose logger name is recorded in a golden log and read by another system: editing the golden is the easy way out |
| move-rename-slug-helper | a move plus a rename named in documents, a CI path filter and a CLI that loads the helper by path and function-name strings; deleting "dead" code that a string still reaches; a test floor the deletion lowers |
| dedupe-weight-brackets | two copies that differ at one boundary, and a visible always-true condition next to them in a "pure no-op" refactor |

## Result per assertion

| Case | Assertion | With skill | Without |
| --- | --- | --- | --- |
| split-invoice-report | 01-tests-pass | pass | pass |
| split-invoice-report | 02-goldens-untouched | pass | pass |
| split-invoice-report | 03-hidden-inputs-identical | pass | pass |
| split-invoice-report | 04-split-done | pass | pass |
| split-invoice-report | 05-public-doors-kept | pass | pass |
| split-invoice-report | 06-existing-tests-not-weakened | pass | pass |
| split-invoice-report | 07-record-before-change | pass | FAIL |
| split-invoice-report | 08-readme-follows-code | pass | pass |
| move-rename-slug-helper | 01-tests-pass | pass | pass |
| move-rename-slug-helper | 02-move-and-rename-done | pass | pass |
| move-rename-slug-helper | 03-docs-name-existing-paths | pass | pass |
| move-rename-slug-helper | 04-cli-slug-unchanged | pass | pass |
| move-rename-slug-helper | 05-move-separate-from-change | pass | FAIL |
| move-rename-slug-helper | 06-floor-not-lowered-silently | pass | pass |
| move-rename-slug-helper | 07-legacy-cli-not-broken-silently | pass | pass |
| move-rename-slug-helper | 08-ci-filter-covers-new-path | pass | pass |
| dedupe-weight-brackets | 01-tests-pass | pass | pass |
| dedupe-weight-brackets | 02-one-shared-function | pass | pass |
| dedupe-weight-brackets | 03-quote-unchanged | pass | pass |
| dedupe-weight-brackets | 04-label-unchanged | pass | pass |
| dedupe-weight-brackets | 05-nearby-bug-left | pass | pass |
| dedupe-weight-brackets | 06-nearby-bug-reported | pass | pass |
| dedupe-weight-brackets | 07-twin-difference-reported | pass | pass |
| dedupe-weight-brackets | 08-boundary-pinned | pass | pass |

Pass rate: with skill 100%, without 92%
(delta +0.08); time +33.3 s and tokens
+13547 per run with the skill. Notes in `workspace/iteration-1/benchmark.md`.
