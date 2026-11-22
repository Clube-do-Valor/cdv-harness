# The method in detail

Read the section a step of `SKILL.md` sends you to. Each rule says what it guards against; a rule
whose reason does not hold in your repository is raised with the developer, not skipped in silence.

## Nets

### What to record

Record behaviour where it leaves the application, because that is what must not change and it is
what survives the refactor:

- an endpoint, per role and per kind of input: the status, the answer, the page data;
- a command, a queued job, a scheduled entry: its output and what it leaves behind;
- the rows written and their order, the jobs and events released after the transaction, the
  requests sent to other systems (to fakes, always);
- a screen: the rendered markup after removing what a person cannot see (framework comment
  anchors, whitespace) and the requests it sends, per state and per role.

A test of an inner class is rewritten by the refactor that splits the class, so it proves nothing
about that refactor. Keep the existing ones green; put the new proof at the door.

What makes a record trustworthy:

- **It was taken on the old code and committed before the change it judges.** A record committed
  with or after the change proves that the new code equals itself.
- **Nothing in it moves by itself.** Freeze the clock, the time zone and every source of
  randomness; replace generated ids by stable tokens; sort what has no order, on purpose.
- **Its world holds every value the code branches on**: a second user, an author different from the
  actor, a date per field. A world that leaves them empty cannot see the branch.
- **It fails when it captured nothing.** Give every recorder a floor, and make a click or a query on
  a missing element throw.
- **It reaches the hidden states.** A tooltip, a menu or a dialog that is closed in the record is not
  recorded: open it in a case of its own, on the old code.
- **It is never updated to pass.** A record that differs after a change is a difference in the code.
  Recording again is a declared act, in the commit that makes it, with the reason.

### Old against new on the same inputs

Where the application can be started twice, the strongest net is a replay: one set of cases - every
endpoint by role, every command, job and scheduled entry, on built data - run against the base
tree and against the changed tree, and everything observable compared: answers, page data, rows,
queued work, outbound requests. An empty difference is the proof; a difference names its case.

- The cases come from the base tree's own inventory, so new entries of the main branch are covered
  without anyone adding them.
- Differences made on purpose live in short lists with a reason each (an entry retired, an entry
  added, a value added to or taken from an answer), as narrow as the cases that really change, and
  the comparison is judged from a fixed revision of its own code.
- A slice runs the cases of its own area before it lands; the whole set runs every night.
- Inputs taken from real traffic, with personal data removed, beat built data when they can be had.
- **Prove the replay itself** with planted changes: patches that change behaviour must show as a
  difference naming the case, pure refactors must come out empty. Plants age: each is a patch
  against the tree of the day it was written. Check that every plant still applies after each
  integration, and run the whole proof after every merge of the main branch and at each phase
  close - a plant that applies can still be wrong when newer code names what it moves.

### When there are no tests

Add them as the code is, through the doors, before any change, and let them pin what is wrong as
well as what is right. With no tests the code is the only truth: a test that asserts today's defect
is correct today. Change the code and the test together only after the refactor, as a fix.

### Proving a net

Before a net is trusted: one planted change per claim it makes goes red; changes a careful refactor
is allowed to make (a private method renamed, two methods reordered, a comment) stay green, because
a net that blocks legitimate work gets switched off; the tests pass twice and once in random order.

## Rules as tests

- Each rule is a test with an allow-list of today's violations. The list may only shrink; a commit
  that moves a violation to another file moves its entry in the same commit.
- A new rule enters with its violations measured, never with a guessed list.
- A failure message names where the code goes instead. The reader of the message is an agent that
  has never seen this repository.
- **Every hub the refactor dissolves gets a rule in the same commit** that fails when the hub gets
  back the kind of code it gave away. Without it the hub grows back at the first merge.
- Prefer a structural check ("this file only requires other files") to a size limit, which lets the
  next ten additions in.
- "One home" for a concept needs a rule too: the commit that empties a folder or removes a second
  copy adds the rule that refuses the next one.
- When code leaves a folder, read again every check and every pipeline path filter that named the
  folder: a check that scans one place goes quiet without failing.

## Twins

Two copies of one job are never the same, and nobody knows every difference. When they become one,
each difference is an explicit option named after what it does, kept, and listed for the developer:
which copy does it, in which file and line. A difference the builder did not expect is reported.
Unifying behaviour is a feature, decided by its owner, after the refactor.

## Deleting

- Dead means unreachable by every path, not unreferenced by import: a name in a string, a dynamic
  call, a template, a schedule, a page resolved by name, a component registered globally.
- A deletion that is safe only if production holds no caller, no queued payload and no stored row
  gets a read-only check, written to run as it stands, with the answer that makes it safe. The
  developer runs it before the merge.
- Deleted tests are read one by one: a test that pinned code that stays is replaced before it goes.
  A counter that held the number of tests is lowered in the commit that removes them, with their
  names.
- Search the importers of every export of the files next to the deleted ones: an export that only
  the deleted file used is dead too.
- Before retiring a recorded test, list the states it holds against the records that stay.

## Moving names

Frozen, unless the developer decides otherwise for a named case: every name that is stored or sent.
Before a class, a file or a symbol moves or is renamed, search for its name in: queue payloads and
failed-job tables, type columns, caches that hold serialized objects, logs an alert reads, the
documents the application serves, the instruction files and guides, the pipeline's path filters,
tests that scan a folder, and tests that read lines of source.

## Frontend splits

- An element that moves from a template into a child loses the parent's scoped-style attribute:
  where a style is scoped, only the script moves.
- A handler that moves into a child inside a transition stops answering while the child leaves:
  pass it down, or leave it.
- A dialog or drawer that teleports is recorded from the document, not from its wrapper.
- Text written between tags that becomes an interpolated value loses the whitespace around it.
- Dependency injection works only during setup of a component under its provider: code that reads
  an injected value may move to a function called from that setup, not to one called later.
- Listeners are registered and removed at the same moments, on the same target, in the same order.
- A write to the address bar stays the kind of write it is: which one decides what Back does.

## A branch that lives long

Choose it knowing the price: every commit of the main branch is applied a second time, by hand,
into code that moved; documents and planted tests go stale; a regression is found far from its
cause. When the developer chooses it:

- The main branch comes in at fixed points, each merge proven by comparing the merged tree against
  the main branch it merged - never against the refactor's old base.
- A merge carries the main branch's change to where that code lives now. A file the refactor split
  or deleted is never restored, and a split part never grows back into the old file.
- A record the main branch's change moves is taken again from the main branch's code, not from the
  merged code, and the merged code must then reproduce it.
- Meanwhile the feature sessions follow a written rule: new logic in new files, the hubs
  append-only, no rename of what the refactor moves.
- The whole gate still runs every night on the branch.

## Running it

- The machine is shared. Heavy runs go through one queue, one at a time while a person uses the
  machine; the whole gate runs alone.
- A process is stopped by its pid, never by a pattern that the calling shell's own command line
  also matches. A scratch checkout is removed by its exact path.
- A file is edited by exact replacement of text read from it, never by a pattern typed from
  memory.
- A check that compares two trees lists the files that differ on purpose before it is run.
- A child gets the task file and the skill. It never certifies its own work: what it reports is
  run again by someone else before it lands.
- A child cut by a limit resumes in its own thread from its notes; every slice keeps notes outside
  temporary folders from its first decision on.
- `STATE.md` is rewritten at every stop, short enough to be read whole by a session that knows
  nothing else.
