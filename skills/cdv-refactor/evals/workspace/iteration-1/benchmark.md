# Skill Benchmark: cdv-refactor

**Model**: claude-sonnet-5-5 (effort high), graded by claude-opus-5-5
**Date**: 2026-11-22T09:44:26Z
**Evals**: dedupe-weight-brackets, move-rename-slug-helper, split-invoice-report (1 run each per configuration)

## Summary

| Metric | With Skill | Without Skill | Delta |
|--------|------------|---------------|-------|
| Pass Rate | 100% ± 0% | 92% ± 7% | +0.08 |
| Time | 67.1s ± 43.4s | 33.9s ± 11.1s | +33.3s |
| Tokens | 74567 ± 10565 | 61020 ± 3128 | +13547 |

## Notes

- Only 2 of 24 assertions discriminate: split-invoice-report/07 (a record committed before the code changes) and move-rename-slug-helper/05 (the move as its own 100%-similarity commit). Both are rules 3 and 4 of the skill; the baseline met every outcome assertion (goldens, behaviour, docs, floor, nearby bug) on its own.
- dedupe-weight-brackets: no benefit. Both runs found the twin difference at 10 kg, kept it behind a flag, pinned it, left the always-true zone condition and reported it. The skill only moved the pinning test into a commit before the change and wrote bugs.md.
- Both slug runs deleted the --legacy CLI path that reaches mkSlugLegacy by a string, after naming it in the report; --legacy now falls into the slug text ('legacy-hello-world'). Assertion 07 passes on the report clause, so it hides a weakness shared by both configurations.
- Cost: the skill adds +33 s and +13.5k tokens per run on average; split-invoice-report took 2.5x the baseline time (state folder, decisions.md, mixin move commit, 2,000-input comparison left uncommitted).
- One run per configuration: no variance estimate. The pass-rate stddev is across cases, not repeats.
