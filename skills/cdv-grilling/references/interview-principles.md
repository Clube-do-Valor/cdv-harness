# Interview principles — the shared rules for asking

Loaded by `cdv-grilling` before its first question and by `cdv-plan-feature` Step 5 (through `references/question-rounds.md`). One file, two consumers: the rules that make a question cost the user a keystroke instead of a turn are the same in an open interview and in a planning Q&A. This file lives inside `cdv-grilling/` because that skill is installed on its own, per user, and must carry its references with it.

## Classification — what to ask, what to skip

Classify every candidate decision before opening your mouth:

| Type | Action |
|---|---|
| **Fact** ("Where is X stored?", "How many rows are in this state?", "What does the external workflow do on delete?") | Look it up — file reads, grep, a read-only one-line query (`profile.cmd_tinker`), an MCP query. A broad survey goes to an `Explore` subagent with `model="sonnet"`. Do NOT ask. |
| **User preference / scope** ("Should multi-select be allowed?", "Is this in the first PR?") | Ask. |
| **Hidden constraint** (deadline, compliance, downstream consumer, someone expecting a specific shape) | Ask. |
| **Trivial / cosmetic** (label position, spacing, debounce ms) | Decide from the neighbouring code. Do NOT ask. |
| **Hard-rule defaulted** (UI library for a new component, page placement) | Apply the default; ask only when the user introduced a conflicting option. |

**Anything the end user perceives is a decision, not a leaf**: TTL and refresh frequency, page sizes, limits, visible defaults, copy that changes meaning.

## Question composition

1. **Concrete options, never an open prompt.** 2–4 options in `AskUserQuestion`; "how should this look?" hands the work back.
2. **Every option carries its consequence in one line.** What the user gets, what it costs, what it closes. An option the user cannot picture comes back as confusion.
3. **One option is `(Recomendado)`, with its why in one line**, tied to a fact you read (`path:line`, a count from the DB, an existing pattern) or a goal the user stated. A recommendation with no why gets asked why as the next turn.
4. **A question you would answer the same way regardless of the reply is not asked.** State the default, mark it as an assumption in the ledger, move on.
5. **A fact is never asked.** How much a screen is used, what a table holds: if the environment can answer it, answer it yourself before the question that depends on it.
6. **Build on the previous answer.** The next question refines inside the chosen subtree, not in a parallel branch.
7. **No filler and no intermediate summaries.** Do not repeat back what the user just said. Only the closing ledger summarises.

## When the user did not understand

Re-explain the problem in one paragraph — what is true today, what this decision changes, why the options differ — and ask the question again with the options rewritten. Never answer "what would you like to clarify?": it spends the turn and hands the work back. If the same question is not understood twice, the options are wrong, not the user; split the decision or look up the fact that would make it concrete.

## Course correction

The user changes an earlier answer: absorb it and continue, no re-litigation, no apology loop. The user pushes back on an assumption: check it against evidence, then either name it as a wrong assumption and adjust, or show the evidence that holds it. The user asks to re-ask a previous question: ask it again in full. The user delegates ("you decide", "what do you recommend?"): decide, say why in one line, and record it as `[recomendação — pendente]` until the user confirms the ledger.

## Skipping ahead

A free-text answer that settles several decisions at once is absorbed whole; follow up only on what stayed ambiguous. Do not ask back what the user volunteered.

## Knowing when to stop

Stop when every root decision is settled, every first-tier dependent has an answer or a stated default, and what remains is leaf-level detail the code decides. A typical feature converges in 5–25 questions; past 25 you are asking leaves before the trunk — rebuild the tree. An interview that ends "for now nothing" is a valid outcome and gets a ledger too.

## Communication style

Justify defaults from what you read, in one clause ("o módulo `reports` já pagina server-side — recomendo o mesmo aqui"). Portuguese for the user-facing question when the conversation is in Portuguese; identifiers never translated.
