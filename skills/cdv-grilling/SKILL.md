---
name: cdv-grilling
description: Grill the user relentlessly about a plan, decision or idea until a shared understanding exists and is written down. Use when the user wants to stress-test their thinking or uses any 'grill' trigger phrase ("grill me", "me entrevista", "ask me interactively"). Do NOT use to cut a settled plan into phases (`cdv-plan-feature`) or to implement.
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Grilling

Interview the user until nothing decidable is left silently assumed, then hand them a written ledger of what was decided and ask what to do with it. The decisions are the user's; the facts, the ordering and the record are yours.

## Step 0 — Load the profile and the extension

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). This skill is also installed per user, outside any repository (`harness sync --user`), so a missing `profile.yaml` does not stop it: outside a consumer repository, use the neutral defaults stated in this file (the ledger goes under `docs/research/` when that folder exists, or in a folder the user names, or `decisions-<slug>.md` in the working directory; no task tracker; no area cards or ADR directory) and say in your first message that you are running without a profile.
2. Read `<profile.extension_dir>/cdv-grilling.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.

Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

## Why this shape

What works: a recommended option on every question, looking facts up instead of asking, and the user's own free-text answers, which carry the best design decisions. What fails: questions whose options have no stated consequence (each one costs a clarify round-trip), asking for facts the repo or an MCP could answer, decisions rendered only in chat and lost, and no step for what comes after the interview (a handoff or a decisions file gets asked for).

## The design tree

Before the first question, map the decisions as a tree: every decision branches into the decisions that hang off it. The **frontier** is every decision whose prerequisites are already settled. Work the frontier root-first; a question whose answer depends on another still-open question waits for the next turn. The tree is your internal map. It is never rendered to the user, and the user never has to tell you which question comes next.

## Cadence

- **Up to two independent questions per turn, exactly one when they are dependent.** Two independent questions save a turn; a dependent pair wastes one, because the second answer prunes what the first would have asked. Three or more in one turn reads as a form, and forms get answered by agreeing.
- Ask through `AskUserQuestion`, 2–4 concrete options each, one labelled `(Recomendado)`. Free text is always a valid answer and is where the user's own design usually arrives; absorb it and re-plan the frontier.
- **Multi-select** is for low-stakes packages only ("which of these do you approve as they stand?"), never for a root decision.
- When the user says "one at a time", "interactively" or "uma por vez", that wins for the rest of the session: one question per turn.
- Never front-load a findings summary instead of asking. Say what you found in the line above the question that needs it, not in a page before the first question.

## The question itself

Load [references/interview-principles.md](references/interview-principles.md) before the first question. The five rules that decide whether a question costs the user a turn or a keystroke:

1. Every option carries its consequence in one line. An option the user cannot picture is a question they will send back.
2. The recommendation carries its why in one line, tied to a fact you read or a goal the user stated.
3. A question you would answer the same way regardless of the reply is not asked. State the default and move on; it lands in the ledger as an assumption.
4. A fact the repo, the docs or an MCP can answer is looked up, never asked. Inline reads for a handful of files; an `Explore` subagent with `model="sonnet"` when the survey is broad. Questions downstream of a lookup wait for it; the rest of the frontier does not.
5. When the user says they did not understand, re-explain the problem in one paragraph — what is true today, what the decision changes, why the options differ — and ask again. Never reply "what would you like to clarify?": that spends the turn and hands the work back.

## Course correction

The user changes an earlier answer: absorb it, re-plan the frontier, do not re-litigate. The user asks to re-ask a previous question: ask it again in full. The user asks to skip a branch ("ignore deploy for now"): mark every decision under it as out of scope and say which questions that removed. The user pushes back on a premise: check it against evidence before conceding or insisting.

## Closing

The interview is done when the frontier is empty. Then, in one message:

1. **The ledger.** Every decision with a provenance tag — `[user, Qn]` when the user picked or wrote it, `[recomendação — pendente]` when it is your default and the user has not said yes, `[código]` when the repo or the data settled it. Then an **Assumptions** table (assumption · chosen default · rationale · confirmed y/n) for every default you applied without asking, an **Out of scope** list with the reason per item, and **Open questions**, which must be empty or explicitly handed on. A ledger with `pendente` items is a draft, not a settled understanding.
2. **Write it to disk.** `<profile.research_dir>/<date>-<slug>/decisions.md` when the repository has that folder (without a profile: `docs/research/` when it exists, or a folder the user names); otherwise `decisions-<slug>.md` at the repository root (gitignored: `decisions-*` is among `profile.ephemeral_patterns`). Then tie the ledger to a task in the task tracker named by the profile (`profile.research_task_cli`) or the user, when there is one. When the folder's `README.md` already carries a task key (a `cdv-research-round` opened it), reuse that key and create nothing. Otherwise create the task, with the absolute path of the folder and the objective in one line as its description, and write the key it prints into the header of `decisions.md`. When there is no tracker, or it refuses, say so in the closing message and go on without the task.
3. **One exit question**, via `AskUserQuestion`, with the exits that actually happened after interviews, each in one line: plan and build here (`cdv-plan-feature`, resolved-spec mode from the ledger); handoff for a fresh session (`cdv-handoff`); a visual artifact to validate the decisions before planning; an artifact for the manager (short, plain language, no code); an ADR (in `profile.adr_dir`, through the `create-adr` skill when it is installed) when a decision reaches past this feature; stop here. Offer only the exits whose skill or directory exists in this installation.

Do not act on the ledger before the exit answer. The next user command is not the go signal; the exit answer is.

## Where this file lives

Installed per repository by cdv-harness, or per user with `harness sync --user`. Edit the core (`skills/cdv-grilling/` in the cdv-harness repository), never the installed copy.
