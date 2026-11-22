---
name: cdv-refactor
description: >
  Run a refactor or a migration that must keep behaviour - split a large class or screen, dissolve a
  hub file, give a concept one home, delete dead code, move code into another structure, port it to
  another framework or language - as a project in phases, with the old code as the source of truth,
  proof recorded before each change, the state of the work kept on disk and one independent
  verifier per phase. Triggers on "refactor this", "split this class", "break up this file",
  "migrate this module", "reorganize the codebase", "make the codebase easier for agents",
  "refatora", "quebra esse arquivo", "migra esse módulo", "/cdv-refactor", or a hand-off from
  cdv-kickoff. Do NOT use for a feature or a fix, however small (cdv-kickoff), for a root-cause
  investigation (cdv-debug), for a review of a branch (cdv-code-review), or for a change that alters
  behaviour on purpose: a refactor that also changes behaviour is two pieces of work, and the
  behaviour change goes through cdv-kickoff.
metadata:
  version: 0.2.0
  owner: augusto-henriques
---

# Refactor

Change the structure of working code and prove that what it does did not change. Three things make
this different from a feature, and the rest of this skill follows from them:

1. **The old code is the specification.** Nothing is written in between. A description of what the
   code "should do" gets read instead of the code, and whatever it did not mention is left behind.
2. **Proof comes first and is deterministic.** What the code does today is recorded before it is
   touched; the same record, unchanged, must pass afterwards. A model saying "equivalent" is not
   evidence.
3. **The work outlives every session.** Its state is a folder on disk, written at each step, so
   that any session - a fresh one, a cheaper one, one after a compaction - can ask "where are we?"
   and read the answer from files.

The scripts live in `.claude/skills/cdv-refactor/scripts/` and run with `python3` from the
repository root. Every script ends with one verdict line on stdout, `<tool> <mode>: PASS|FAIL|PARTIAL — <what was judged>`,
and exits `0` (PASS), `1` (FAIL: the thing guarded moved), `2` (usage: a bad argument, a missing
configuration), `3` (environment: git failed, a step was refused) or `4` (PARTIAL: nothing failed, but
part of what was asked was not judged - an empty frozen list, an unreadable version, no history for a
list that needs it). **Partial is never a pass**: the night run and any script around these judge by that
line. A guard that is given no `--base` reads it from `state.json`: the start of the running phase, else
the base `init` recorded.

| Script | Does | Exit |
| --- | --- | --- |
| `refactor_state.py --folder <state folder> init\|phase\|slice\|where\|render` | keeps `state.json`, the one record of phases and slices (with `base`, and the start commit of each phase), and renders `STATE.md` and `LEDGER.md` from it and from git | `0`, `2` unknown id or bad argument, `3` refused |
| `docs_follow_code.py [--base <rev>] [--folder <state folder>] [--docs <path> ...] [--name <symbol> ...]` | lists every mention, in the documents, of a file the range deleted or renamed and of each named symbol | `0` none, `1` stale mentions, `2`, `3`, `4` no document searched |
| `ratchet.py --folder <state folder> snapshot\|check [--tighten] [--base [<rev>]]` | counters that may only move one way (`ratchet.json` says which, `baseline.json` holds them); with `--base`, the history of both files is judged commit by commit: a baseline moved the wrong way, a counter's command or direction rewritten, or a counter removed fails unless the same commit accepts it in `records.json` | `0`, `1` a counter moved the wrong way or a commit loosened one, `2` no configuration, `3`, `4` a commit could not be read |
| `records_guard.py --folder <state folder> [--base <rev>] [--worktree]` | a file under a frozen location of `records.json` that changes without a declaration added by the same commit; judged commit by commit over `<base>..HEAD`, the frozen list read from every version in the range | `0`, `1` an undeclared change or a stale declaration, `2`, `3`, `4` nothing frozen or a version unreadable |
| `instruction_paths.py [--folder <state folder>] [--instructions <path\|glob> ...] [--resolve-from <dir> ...] [--base [<rev>]]` | every path an instruction file names exists; its allow list only shrinks, judged from git | `0`, `1` a new dangling path, a stale entry or a list that grew, `2`, `3`, `4` no file read, or an allow list with no base |

## Step 0 - Load the profile and the extension

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its
   keys win). Stop when `profile.yaml` is missing: this skill runs only inside a consumer
   repository.
2. Read `<profile.extension_dir>/cdv-refactor.md` when it exists. It names the repository's own
   nets and tools (its gate, its recorders, its architecture rules) and the decisions already taken
   for a refactor in flight. The extension only adds or restricts; where it and this skill differ,
   the extension wins for this repository.
3. When a state folder already exists (Step 2), read its `STATE.md` before anything else and go on
   from what it says: never plan again what is already decided.

Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the
repository does not have that thing: skip the step that needs it.

## Why this shape

Each rule here answers a cost that a long, agent-run refactor paid:

- A task file that describes the code gets wrong what it describes. In one whole-codebase refactor,
  the largest class of logged mistakes was briefs that stated a fact the code contradicted. A brief
  that points at the code has no fact to get wrong.
- The second largest class came from the machinery around the refactor, not from the code moves:
  counters kept by hand, commit ids typed into documents, lists nobody regenerated. What a script
  can produce is never typed.
- Documents rot silently. A path check passes while the sentence beside the path sends the next
  agent to the file the refactor emptied.
- One branch that lives for weeks pays for every commit the main branch gains: each one is applied
  again, by hand, into code that has moved.
- Nets built for the whole application cost more than the refactor. Nets are built for what a phase
  touches.

## The five rules

1. **Behaviour stays.** Behaviour is everything a person, another system or a stored row can
   observe: answers and pages, rows written, jobs queued, requests sent, the order of side effects,
   and every name that is stored or sent somewhere (a class name in a queue payload or a type
   column, a route name or address, a command signature, an enum value, a permission name). A
   defect found on the way is pinned by a test as it is, written to `bugs.md`, and fixed after the
   refactor - never inside it.
2. **The old code is the source.** A builder reads the code it moves. Its task file says where,
   towards which shape, with which criteria and where to stop; it does not restate what the code
   does.
3. **A move and a change never share a commit.** First the code moves, byte for byte. Then its
   form changes. Each can be checked against something that still exists.
4. **The record comes before the change** and is not edited by it. A record that differs after the
   change is a difference in the code, and the code is wrong.
5. **Fix forward.** A fix is a new commit that names the commit it corrects. History is not
   rebuilt to hide it, and a document never carries a commit id, a count or a list that a script
   could have printed.

## Step 1 - Measure, and decide what not to touch

Before proposing anything, measure where work on this codebase costs most: the files an agent must
open for a typical task and their size, the hubs every change passes through, the concepts written
in more than one place, the places a session reads too much or searches too long. Rank candidates
by size times how often they change. **Code that works and is easy to work in is left alone.**

Freeze the inventory on a date and write it down. Code written after that date is not part of the
refactor: it is listed as follow-up work.

## Step 2 - Open the state folder and decide the one-way doors

The state folder is `<profile.research_dir>/<date>-<slug>/` (the folder a `cdv-research-round` or a
`cdv-grilling` already opened for this work, when there is one). Lay it out from
[references/templates/state-folder.md](references/templates/state-folder.md) and run
`refactor_state.py --folder <it> init`.

Then settle with the developer, through `cdv-grilling`, the decisions that cannot be taken back
cheaply. Ask them; do not assume them:

- **How it lands.** One pull request per phase is the default: the main branch always holds the
  refactored code, and nothing is applied twice. One pull request at the end is a choice the
  developer makes knowing its price, and it then needs the next answer.
- **How the main branch comes in**, when the refactor's branch lives long: at fixed points, or
  each time it moves, or by the author of each feature porting it. And what the feature sessions
  must respect meanwhile (new logic in new files, no rename of what the refactor moves).
- **What is frozen**: the stored and sent names of rule 1, listed for this repository.
- **What counts as proof** for each kind of change, and the cadence of the whole gate (Step 7).
- **What is out**: migrations, dependency upgrades, behaviour changes however tempting.
- **Who runs what**: the roles of the profile and how many builders work at once.

## Step 3 - Phase 0: the repository answers fast

No production code changes in this phase. An agent checks its own work by running the
repository's commands, so they come first:

- One command that says pass or fail for the whole repository: tests, static analysis, type check,
  lint, build. It must be reproducible (the same image or lockfile every time) and fast enough to
  run often; where the whole takes long, name the targeted form a builder runs per commit.
- Existing debt becomes ratchets, not noise: a baseline of today's errors and violations that may
  only shrink. Write them into `ratchet.json` and take `ratchet.py snapshot`.
- Declare what is frozen in `records.json` of the state folder: the locations of the records (and
  the guards themselves) under `frozen`, with their `excludes`. From then on a record changes only
  by a declaration in the commit that changes it, and `records_guard.py` says so.
- Name the instruction files and where their paths resolve in `instruction-paths.json` (or by
  arguments); `instruction_paths.py --write-allowlist` lists today's dangling references once, in a
  commit of its own, and the list only shrinks from there.
- Fitness rules for the structure the refactor is heading to, as tests with allow-lists that only
  shrink: who may import whom, what may live where, how large a file or a method may be.

## Step 4 - Plan in phases, one phase ahead

Write `phases.md`: each phase with its goal, its exit criteria and the order that makes it safe -
subtract before splitting (dead code, second copies), dissolve hubs before the code that depends
on them, the tangled core before its periphery or after it, by evidence. Detail only the phase in
progress and the next one: phase 3 depends on what phase 2 finds.

Cut each phase into **slices**: one module, one class family or one page folder, with files no
other running slice edits. Register each with `refactor_state.py slice add`, and write its task
file from [references/templates/task-file.md](references/templates/task-file.md). The backlog of a
phase comes from a script (the files above a size, the entries of a list, the callers of a
function), never from a list typed by hand.

## Step 5 - Nets, for what the phase touches

Read [references/method.md](references/method.md), "Nets", before building any. In short:

- Record behaviour through the outer doors - a route, a command, a job, a rendered screen - not
  through the classes about to be split: a test of an inner class is rewritten by the refactor and
  proves nothing about it.
- Where the application allows it, compare old and new code directly on the same inputs.
- A net is itself proven: a planted change it must catch goes red, an allowed change stays green,
  and a recorder that captured nothing fails.
- Only for what this phase touches. A net for code no slice will change is cost without proof.

## Step 6 - The slice loop

For each slice, in a checkout of its own:

1. `refactor_state.py slice start <id> --child <name>`. The builder gets the task file and this
   skill - not a rewritten copy of the rules.
2. **Record** what is missing, on the code as it is; commits that add tests and records only.
3. **Move**, then **change form**, in separate commits; the repository's targeted checks pass on
   every commit.
4. **Prove**: every record that existed before is unchanged and passes - `records_guard.py
   --folder <state folder>` exits `0`, and a change that had to happen is declared, with its reason,
   in the commit that makes it; the slice's planted changes go red and are removed.
5. **Documents follow code**: `docs_follow_code.py --base <start of the slice>` exits `0`,
   `instruction_paths.py --folder <state folder> --base` exits `0`, and every guide that describes
   what moved now describes where it is.
6. The orchestrator integrates: the slice's targeted checks and its own comparison of old against
   new, run by someone other than the builder; then `refactor_state.py slice landed <id> --range
   <a>..<b>` and `ratchet.py --folder <state folder> check --base --tighten`: the counters are judged
   against the history of the phase, so a cap that a commit moved is seen, then tightened.

A builder that meets something unclear stops and asks; it does not decide a difference between two
copies, a defect, or a name that might be stored. [references/error-classes.md](references/error-classes.md)
lists the mistakes each kind of slice makes and the guard for each: the task file names the classes
that apply.

## Step 7 - Verify

- **Every night, by machine**: the whole gate and the whole comparison of old against new run on
  the tip from a script and leave one result line. No session waits for it.
- **At the end of each phase, one independent verifier** - a fresh child that built none of it, on
  the profile's `verifier` role - from [references/templates/verifier-brief.md](references/templates/verifier-brief.md):
  did everything the phase promised move, is anything left behind or reachable that was deleted,
  does the result follow the agreed shape, do the documents tell the truth. Review effort goes
  where the invariants are, not evenly.
- A finding is fixed forward and its lesson recorded only when it has been seen twice.

## Step 8 - Deliver

Each pull request carries: what moved, in one table generated by `refactor_state.py render`; the
proof (the gate, the comparison, the verifier's verdict); what was found and not fixed (`bugs.md`);
and, for every deletion that is safe only if production holds no caller, no queued payload or no
stored row, a read-only check the developer can run as it stands, with the answer that makes it
safe.

## Rules of the run

- **The orchestrator decides and builds nothing.** Integration is scripts; the session wakes for a
  finished child or a finished run, and writes `STATE.md` before it stops.
- **Models by role**, from the profile (`role_target.py` of `cdv-kickoff`): the plan and the
  verifier on the strongest role, builders on the builder role, never an automatic choice of the
  cheapest. A whole slice per child keeps its cache; do not change a session's model in the middle
  of its work unless the developer says so.
- **Briefs state few facts.** Every number or path in a task file was read from the code when it
  was written, or says "recount".
- **Stop and ask** before: a difference between old and new that is not plainly a mistake of the
  refactor; a deletion that waits for a production check; anything that would change a frozen
  name; a step that sends something to a person or a live system.
- **Loaded context stays small.** `lessons.md` holds only what was seen twice; the log of
  everything else is read on demand.

## Where this file lives

Installed per repository by cdv-harness. Edit the core (`skills/cdv-refactor/` in the cdv-harness
repository), never the installed copy.
