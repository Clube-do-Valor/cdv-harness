# Template - the state folder

One folder holds the refactor for as long as it lives: `<profile.research_dir>/<date>-<slug>/`. A
session that knows nothing else reads `STATE.md`, then what `STATE.md` points to.

| File | Holds | Written by |
| --- | --- | --- |
| `STATE.md` | The phase and the slices in progress, what is running, what comes next, what waits for the developer. Rewritten at every stop, never appended; short enough to be read whole | the orchestrator; its table comes from `refactor_state.py render` |
| `state.json` | `base` (the commit the refactor starts from), phases and slices with their status, the start commit of each phase, their children and their commit ranges | `refactor_state.py` only |
| `LEDGER.md` | What landed, slice by slice, with commits and files counted from git | `refactor_state.py render` only |
| `decisions.md` | The decisions, each with who took it | `cdv-grilling` |
| `phases.md` | The roadmap: per phase its goal, its exit criteria, its slices. Detailed for the phase in progress and the next | the orchestrator |
| `tasks/<slice>.md` | One task file per slice | the orchestrator |
| `bugs.md` | Defects found on the way: where, what, the test that pins it. Not fixed here | builders, appending |
| `ratchet.json`, `baseline.json` | The counters that may only move one way, and their values | the orchestrator; `ratchet.py` |
| `records.json` | The frozen locations (`frozen`, `excludes`), the changes declared to them (`declared`) and the counter moves accepted (`accepted`). Judged from git, commit by commit | the orchestrator; read by `records_guard.py` and `ratchet.py --base` |
| `instruction-paths.json`, `instruction-paths.allow` | Which files are instruction files and where their paths resolve; the dangling references accepted today, a list that only shrinks | the orchestrator; read by `instruction_paths.py` |
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
in a commit that also adds its `accepted` entry to `records.json` with the reason; `ratchet.py check
--base` fails any other commit that lowers the baseline or rewrites a command.

## `records.json` starter

```json
{
  "frozen": ["tests/records/", "src/**/__snapshots__/**", "scripts/gate.sh"],
  "excludes": ["tests/records/registry.json"],
  "declared": [],
  "accepted": []
}
```

`frozen` lists the records and the guards themselves: a folder (ends with `/`), a path, or a glob
(`*` within a folder, `**` across folders). `excludes` are what a frozen entry covers that is not
frozen. A file under a frozen location that is modified, deleted or renamed away changes only with
an entry of `declared` **added by the same commit**, with a reason:

```json
{"path": "tests/records/routes.json", "change": "modified", "reason": "route retired, decision 4", "count": 1}
```

`path` is a file or a glob that matches within one folder (never `**`, never a whole frozen
location); `change` is `modified`, `deleted` or `any`; `count` is required past ten files. Adding a
file is always allowed, once. The frozen list is read from every version of the file in the range, so
removing an entry in the commit that edits the record does not unfreeze it: an entry once written
freezes for good, and an exclusion counts only when every version has it.

`accepted` holds the one way a ratchet may be loosened, in the commit that does it:
`{"counter": "tests", "reason": "tests deleted with the code they tested, decision 7"}`.
