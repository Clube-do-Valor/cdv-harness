# Error classes and their guards

The mistakes a long refactor made, grouped by the kind of slice that makes them. A task file names
the classes that apply to its slice (by the heading below), so that a builder reads ten lines, not
all of them. A guard that is a command is run; a guard that is a habit is checked by the verifier.

## Recording

| Mistake | Guard |
| --- | --- |
| A record that changes with the day, the time zone or a random value | Freeze all three in the test world; record once under another time zone to prove it |
| A recorder that passes because it captured nothing | A floor on every recording; a missing element throws |
| A record committed with the change it judges | Record commits come first and add files only; the integration runs each where it lands |
| A state that exists only behind a closed tooltip, menu or dialog | An opened record for it, taken before the change |
| A retired test that held the only record of a state | List its states against the records that stay before retiring it |
| A screen fed with hand-written data where a role shapes it | Feed the screen from data the server recorded for that role |

## Moving and splitting

| Mistake | Guard |
| --- | --- |
| A move and a change of form in one commit | Two commits; the first is checked as a pure move |
| A class name that travels in a queue payload, a type column or a cache | Search the stored and sent names before moving; frozen unless decided |
| A test that reads a line of source the slice moved | Run the tests that read source files in every slice that touches those files |
| A check that scanned the folder the code left | Read again every scanning test and pipeline path filter that names the folder |
| A hub that grows back at the next merge | A rule in the same commit that dissolves it |
| A second copy created again after the first was removed | A rule in the commit that removes it |
| Two copies unified silently | Every difference is a named option, listed for the developer |
| A lazily computed value that became eager, or the reverse | Compare the kind of each value before and after; compare the queries of one recorded case |

## Deleting

| Mistake | Guard |
| --- | --- |
| Code deleted as dead that a string, a dynamic call or a template reaches | Search each deleted name as text, on the parent commit and on the tip |
| A deletion that rests on production with no check written | A read-only probe in the state folder, runnable as written, before the merge |
| Tests deleted while the counter of tests stays | Lower the counter in the commit that deletes them, naming them |
| An export left behind that only the deleted file used | Search the importers of the neighbours' exports |
| A guide that still describes the deleted method | `docs_follow_code.py`, then read the guide whole for the name |

## Documents and instructions

| Mistake | Guard |
| --- | --- |
| An instruction that sends new code to a file the refactor emptied | The slice that moves code fixes every sentence that names it, in the same slice |
| A correction made in one instruction file and not in its copies | Search every instruction file for the claim before closing |
| A workflow written from memory that names a step in the wrong order | Run the workflow once on a scratch tree; say "read, not run" where it was only read |
| A number, a path or a list typed into a task file and wrong | State few facts; each was read when written, or says "recount" |

## Bookkeeping

| Mistake | Guard |
| --- | --- |
| A count or a floor kept by hand that nobody lowered or raised | `ratchet.py`; a count in a document is printed by a script |
| Commit ids typed into documents, then history rebuilt | No ids in documents; fix forward |
| A planted test patch that no longer applies, or applies and means something else | Check every plant after each integration; run the whole proof after each merge and at each phase close |
| A check that compares two trees and stops on a file that differs by design | List the intended differences before running it |

## Tooling and the machine

| Mistake | Guard |
| --- | --- |
| A guard that judges only the first and last commit of a range | Judge every commit; a cap never lives in the file it caps |
| A process killed by a pattern that matched the caller's own shell | Kill by pid, read from a pid file |
| Scratch checkouts removed by a filter that matched other sessions' checkouts | Remove by exact path |
| Two heavy runs at once on a shared machine | One queue; the whole gate alone |
| A patch edited with a pattern typed from memory | Exact replacement of text read from the file |
| A tool tested only by its own author's happy path | Through its command line, with a case for each refusal |

## Merging the main branch into a long-lived branch

| Mistake | Guard |
| --- | --- |
| A file the refactor split, restored by the merge | Carry the change to where the code lives; the old file stays gone |
| A record taken again from the merged code | Take it from the main branch's code; the merged code must reproduce it |
| A merge proven against the refactor's old base | Compare the merged tree with the main branch it merged |
| New logic of the main branch written into a hub the refactor split | The feature sessions' rule, and the hub's own rule once it lands |
