---
paths:
  - "{app_dir}/tests/**"
  - "{app_dir}/resources/js/**/*.spec.ts"
  - "{app_dir}/resources/js/**/*.spec.js"
---

# Tests

The tests-in-the-same-PR rule is in the house block of the instructions file. Where tests live, the commands that run them and the framework details are the repository's (`.claude/harness/profile.yaml` and its own rules).

- Use the existing test file for the touched module when one exists; only add a new test file when the module does not yet have coverage.
- A test asserts observable behaviour, never the implementation. A mocked dependency returns the exact shape the real one returns, including the keys the code under test must strip; a mock of the wrong type passes green while production fails.
- Never fix a slow or flaky test by raising its timeout. Split it, or share the expensive setup when the cases do not need a fresh one.

## Regression tests — when to include, when to skip

Practical decision guide for whether a code change requires a regression test. This is not a rule that says "always write a regression test." It is a heuristic for deciding case by case, so that the suite stays useful instead of noisy.

### Core rule

A regression test protects a **contractual** or **invariant** behavior of a flow that already exists in production. The trigger for "I must include a regression test in this PR" is:

> My change alters the contract, semantics, or sequencing of a flow that already has callers, consumers, or downstream observers.

If yes, include a regression test that demonstrates the pre-change behavior is preserved or that the new contract is honored under the old caller patterns. If no, a fresh unit/feature test for the new code is enough — no separate regression suite needed.

### Practical heuristics

When the core rule is ambiguous, fall back to these:

1. **The "regret test."** If this regresses without alerting, will I regret it? If yes, write the test.
2. **Signal / noise ratio.** Will the test fail **only** when the bug returns, or will it fail on every innocent refactor? If it's the second, rewrite or skip.
3. **Cost balance.** `cost_of_failure × probability_of_regression` should exceed `cost_of_maintaining_the_test`. Fowler discusses this calculus in [TestPyramid](https://martinfowler.com/articles/practical-test-pyramid.html).
4. **Behavior over implementation.** A regression test asserts **observable external behavior** (output given input, side effect given trigger), not how the code internally achieves it. If you have to read the production code to understand the assertion, the test is testing implementation details.
5. **Test what you'd grep for.** If a stakeholder says "make sure X never breaks," that phrase is the test name. If you can't articulate the "X," the test probably isn't worth writing.
6. **Hyrum's Law.** For any API with more than one consumer, **some** consumer depends on **any** observable behavior. Testing public contracts is defense against implicit coupling you don't know exists.

### Typical triggers

- **Integration endpoint response shape changes** (an envelope going from object to array). External consumers depend on the shape; a wrong consumer branch on a payload variant is invisible at code-review time.
- **Guard / skip semantics changes** (a skip reason whose scope moves from the whole batch to one group). The guard must still fire for the cases it used to fire for, and must NOT fire for the cases it shouldn't.
- **Permission / authorization changes.** Every permission that gates a route already in production must continue to gate it under the same conditions.
- **Domain enum value mapping changes.** Downstream code (jobs, services, controllers) relies on those mappings.
- **Job dispatch / retry behavior changes.** Anything that changes when a job is dispatched, retries, or fails affects queue volume and error-tracker signal.
- **Database schema changes that affect existing rows.** Backfills, column type widening, FK constraint changes all need a test that asserts old rows still satisfy invariants.

Triggers that do **not** require a regression test:

- Brand-new endpoint with no existing caller (fresh tests only, no regression).
- Brand-new model / table with no migration affecting existing rows.
- Pure CSS / template cosmetics (covered by visual QA, not unit tests).
- One-shot maintenance commands (a smoke test + dry-run gate is usually enough).

The repository's own rule lists the triggers seen in its codebase and where each kind of test is anchored.

### Naming

The description is the test's name, and a name filter matches a substring of it:

- `it('preserves <old behavior> when <new behavior is introduced>')` — guards the old path.
- `it('<new behavior> <scenario>')` — guards the new path.
- `it('keeps <guard or skip> within <scope>')` — guards a semantic boundary.

### Practical PR checklist for regression tests

When opening a PR that touches a flow already in production, the description should make these explicit:

- [ ] The pre-change behavior is documented (in the context section of the PR).
- [ ] At least one test in the suite covers the **old caller pattern** under the new code.
- [ ] If a test had to be adapted (assertion shape changed), the `test:` commit message says so explicitly (e.g., `test(scope): adapt sync assertions to array envelope`).
- [ ] If a regression test would have low ROI (trivial delegation, snapshot noise, one-shot script), the PR description states **why** it was skipped, not just that it was.

### When this guide does not apply

This guide is about **regression** tests specifically (tests that protect behavior that already shipped). It does **not** cover:

- New-feature coverage on greenfield code — see the tests rule in the house block.
- Mutation testing, property-based testing, fuzzing — out of scope here.
