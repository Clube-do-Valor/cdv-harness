# Template - the state folder

One folder holds the refactor for as long as it lives: `<profile.research_dir>/<date>-<slug>/`. A
session that knows nothing else reads `STATE.md`, then what `STATE.md` points to.

| File | Holds | Written by |
| --- | --- | --- |
| `STATE.md` | The phase and the slices in progress, what is running, what comes next, what waits for the developer. Rewritten at every stop, never appended; short enough to be read whole | the orchestrator; its table comes from `refactor_state.py render` |
| `state.json` | Phases and slices with their status, their children and their commit ranges | `refactor_state.py` only |
| `LEDGER.md` | What landed, slice by slice, with commits and files counted from git | `refactor_state.py render` only |
| `decisions.md` | The decisions, each with who took it | `cdv-grilling` |
| `phases.md` | The roadmap: per phase its goal, its exit criteria, its slices. Detailed for the phase in progress and the next | the orchestrator |
| `tasks/<slice>.md` | One task file per slice | the orchestrator |
| `bugs.md` | Defects found on the way: where, what, the test that pins it. Not fixed here | builders, appending |
| `ratchet.json`, `baseline.json` | The counters that may only move one way, and their values | the orchestrator; `ratchet.py` |
| `production-checks/` | One read-only check per deletion that rests on production, with the safe answer | the builder or verifier that found the need |
| `reports/` | One report per phase from its verifier; a builder's report when it is worth keeping | children |
| `lessons.md` | Lessons seen at least twice, one line each with the file that grounds it | the orchestrator |
| `lessons-log.md` | Everything else that was learned once. Read on demand, never loaded by default | the orchestrator |

## `STATE.md` starter

```markdown
# <slug> - state

Updated <date and time>. Read `decisions.md` once; then this file is enough to continue.

## Now

<the phase in progress, in one line; what is running (child, slice, since when); what the session
that reads this should do first>

## Slices

<!-- refactor-state:begin -->
<!-- refactor-state:end -->

## Waiting for the developer

<questions and checks only the developer can answer, each with what it blocks>

## Traps known today

<three to six lines: what has gone wrong more than once in this repository>
```

## `ratchet.json` starter

```json
{
  "counters": [
    {"name": "files-over-400-lines", "cmd": "git ls-files 'src/**' | xargs wc -l | awk '$1 > 400 && $2 != \"total\"' | wc -l", "direction": "down"},
    {"name": "tests", "cmd": "<a command that prints the number of tests>", "direction": "up"}
  ]
}
```

`direction` is `down` (may only fall), `up` (may only rise) or `same`. A counter that must move the
other way for a reason - tests deleted with the code they tested - is moved by `ratchet.py snapshot`
in the commit that says why.
