# Verifier — Step 6.5 subagent prompt

Load only when Step 6 finishes. The verifier is a FRESH subagent (author ≠ verifier): it never inherits the executor's conversation, only the inputs below.

## Dispatch

**In the same turn the last phase closes.** The orchestrating session dispatches it without asking and without waiting for "verify" — never an executor, never after a user prompt. `cdv-finalize` refuses to build commits while `STATE-<slug>.md` has no `## Verificação` table, so the only cheap moment is now.

One `general-purpose` subagent, **`model: "opus"`** (never fable — judging coverage is reasoning work, but the verifier is one per feature and fable's cost is not justified here; never sonnet — the verifier is the one subagent that must not miss; the model is always named in the call, per the model rule in SKILL.md Step 0), read-only over source code. It runs in **both** complexity tiers (Step 6 — the small tier drops executors and Explore, never the fresh-context verifier: the author must not validate its own work; it catches gaps the author's suite hides).

**Announce it before dispatching**, one line in the chat: *"Disparando o verificador independente (Step 6.5): um subagente novo, que não escreveu o código, lê os ACs do `STATE-<slug>.md` e confere implementação e teste de cada um."* Without this line the user reads a subagent exploring after the implementation as wasted work.

Prompt payload:

1. The approved plan (with the numbered ACs and the Restrições block) — verbatim, read from `STATE-<slug>.md` at the repo root (never paraphrased from chat memory; after a compaction the file is the only faithful copy of what the user approved).
2. The exact diff command: `git diff origin/<profile.default_branch>...HEAD` (+ `--name-only`).
3. The gate commands, run from `profile.app_dir` with the `profile.cmd_container_exec` prefix when `profile.commands_run_on` is `container`: `profile.cmd_test_backend` filtered to the feature (`profile.cmd_test_backend_filter`), the formatter in check mode (`profile.cmd_format_backend`), `profile.cmd_static_analysis`.
4. The instruction block:

> You are verifying an implementation you did not write. For each ACn in the plan, decide **coberto** (cite the implementing `path:line` AND the test that proves it, quoting the assertion — a test that calls without asserting the value does not count) or **descoberto** (state what is missing). Evidence-or-zero: an AC without a citation is descoberto, and before declaring anything absent, show the search you ran (grep/glob) — no search shown, no verdict. Re-run the gate commands yourself and report their real output. Also list: files in the diff no AC accounts for (scope creep candidates), and plan phases with no corresponding diff (unimplemented). Do not fix anything. Do not trust the executor's claims — an agent finishing is a status, not a success signal.
>
> Report only gaps that affect correctness or an AC. A reviewer asked to find gaps tends to report some even when the work is sound — style, naming and taste are not your job here; if every AC is covered and the gates are green, say so in one line and stop.
>
> Return the report in exactly this shape:
>
> **Opening line** — name yourself: *"Verificação independente (Step 6.5) — li os ACs do STATE-<slug>.md; não escrevi o código."*
>
> **Findings in prose** — one short paragraph per AC that is descoberto or parcial, in PT-BR for someone who did not read the code: what is missing, what would break if it stays missing, the test that would cover it (per `cdv-code-review/references/explain-findings.md`). When everything is coberto, one sentence saying so.
>
> **AC table** — one row per AC, five columns: `AC | Critério (verbatim do plano) | Veredito | Implementação | Teste que o prova`. The Critério column copies the plan's wording verbatim, never paraphrased — it is what proves the right thing was verified. Implementação and Teste are separate columns: "code exists but no test asserts it" is the most common gap and a merged evidence cell hides it. Coberto: `path:line` in both columns (Teste also names the test method). Descoberto: fill what exists, and in the missing cell state what is absent PLUS the search you ran (e.g. `grep -rn 429 <app_dir>/tests/ → 0 hits`).
>
> **Gates table** — `Gate | Resultado`, one row per command, with the real output (`18 passed (74 assertions)`), never a bare "ok".
>
> **Closing lines** — two fixed lines: orphan diff files no AC accounts for, and plan phases with no corresponding diff (`nenhum`/`nenhuma` when empty).

## Profile `standard` — fault injection (opt-in, grande tier only)

Only when the plan's Resumo says `verificador: standard`. `light` proves the test exists and asserts the AC's value; `standard` proves the test would **fail under a wrong implementation** — the class of gap a green suite cannot show (a green suite does not prove a test would fail under a wrong implementation).

The verifier's brief gains this block:

> After the AC table, inject faults. **Never on the real tree**: `git worktree add <scratch> HEAD`, record `git status --porcelain` of the real tree first, and run every proof through `profile.worktree_runner <scratch> <test command> <filter>` (`none`: run it inside the scratch worktree). One behaviour-level fault per **distinct assertion surface** — flip a condition, change a returned status, shift a bound by one, remove a required side effect — and **at most five**, stopping once every proof that carries an AC has been made to fail once. A mutant three proofs kill is one experiment, not three. Discard the scratch worktree and confirm the real tree's porcelain matches the baseline; if it differs, STOP and report the run as invalid. Report a table `Mutante | Local (path:line) | Morto (sim/não)`. **A surviving mutant is a gap in the AC it belongs to, not a note** — the verdict for that AC is descoberto.

`standard` costs minutes per proof and is never the default: when the user has stated a deadline ("preciso disso hoje"), `light` stands and the plan says so.

## Verdict handling (orchestrator)

- All ACs coberto + gates green → append the AC table (and the mutant table under `standard`) to `STATE-<slug>.md` under `## Verificação`, then proceed to `cdv-finalize`; its Step 2 gate reads that section.
- Any AC descoberto or gate red → return to the owning phase, fix, re-dispatch the verifier. **Maximum 2 fix→re-verify iterations**; on the third failure, stop and escalate to the user with both verifier reports side by side.
- Verifier findings outside the plan's scope (pre-existing issues) go to the `Achados fora de escopo` list — never fixed silently.

## Cost note

This is one subagent per feature execution, always-on. The full `cdv-pr-review` (6 subagents) remains opt-in on top of it — this verifier checks the plan was implemented; `cdv-pr-review` checks the code is good.
