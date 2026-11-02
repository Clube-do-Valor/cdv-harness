# Question Rounds — Step 5 Q&A Taxonomy

Load at the start of Step 5.

**Canonical Q&A meta-rules live in [`../../cdv-grilling/references/interview-principles.md`](../../cdv-grilling/references/interview-principles.md)** — classification table, the seven question-composition rules, course correction, skipping ahead, and communication style are defined there, not duplicated here. Read it first. This file holds only what is specific to the planning Q&A: the UI-first ordering, the architectural-vs-implementation boundary, and the plan-side stop conditions.

Two deltas over the canonical rules:

- The classification table gains two rows: **UI/visual placement** ("Where on the page? Which existing pattern? Which component variant?") → ask **before any backend architecture question** when the feature touches UI (hard rule); and **Implementation detail** ("Which Eloquent method? Which Vue helper? Debounce ms?") → decide autonomously during planning, do NOT ask.
- Composition rule 7 reads here as: only the final **plan in Step 4** summarizes (not the `cdv-grilling` ledger).

## Question ordering rule (hard rule)

**UI/visual placement comes in Round 2, never deferred.** When the feature touches a visible UI element, the very first scope question after bundling is about placement / visual weight / which existing pattern to follow. Failure to ask early bakes the wrong visual language into the plan and forces redesign after the fact.

Round structure:

- **Round 1 — Bundling / Scope boundary**: which entity/module owns this, what is included vs out of scope.
- **Round 2 — UI/visual placement** (when applicable) + **Backend architecture** (parallel, but UI first): drawer/inline/dedicated page, then async vs sync, job vs command, where to persist.
- **Round 3 — First-tier dependents**: permissions, audit, multi-value, persistence scope.
- **Round 4+** — Round-by-round refinement inside the chosen subtree.

If you find yourself asking implementation details (which method, which exact label), step back to Round 2 and verify the trunk is settled.

## Backend question rule — architectural level only

Backend questions stay at the **architectural** level:

- ✅ "Async via job na queue `default` ou sync no controller?"
- ✅ "Persist no banco ou em cache Redis com TTL?"
- ✅ "O sistema que dispara é a aplicação ou um workflow externo via webhook?"
- ✅ "Job dispara um único processamento ou batch?"

NOT at the implementation level:

- ❌ "Qual método do Eloquent usar para buscar?"
- ❌ "Qual controller method deveria chamar esse helper?"
- ❌ "Validation via `required` ou `present`?"
- ❌ "Qual a key do cache?"

Those are decisions the executor makes autonomously during the Step 6 phase execution.

## Knowing when to stop (plan-side)

Stop the Q&A when:

- Every Round 1–3 decision is resolved (scope, UI placement, backend shape, persistence, permissions).
- Remaining questions are Round 4 leaves (debounce ms, exact label text, operator order) → decide during planning.
- The plan can be rendered without gaps using the skeleton from [plan-skeleton.md](plan-skeleton.md).

A typical feature plan converges in **3–10 questions** when entering from a `cdv-grilling` ledger (most decisions already resolved upstream), or **8–20 questions** when entering cold.

## When entering from a `cdv-grilling` ledger

If the input is a `decisions.md` ledger written by `cdv-grilling` (or an equivalent settled doc), treat every `[user, Qn]` and `[código]` line as already-resolved. Skip Q&A on:

- Interaction model
- UI library and page location
- Persistence scope
- Sync model
- Permissions
- Auditing
- Locale

Only ask about the ledger's `[recomendação — pendente]` lines and its `Open questions`, or about a divergence surfaced by Step 3 that contradicts a ledger line.

This is the happy path of the pipeline: `cdv-grilling` did the upstream work, `cdv-plan-feature` should produce a plan in 3–5 turns.
