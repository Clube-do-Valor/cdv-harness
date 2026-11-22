# Template - the task file of a slice

Save it as `tasks/<slice id>.md` in the state folder. Keep it under one page. It states where the
work is and what "done" means; it does not describe what the code does - the builder reads the
code. Every number or path in it was read from the code on the day it was written; anything else
says "recount".

```markdown
# <slice id> - <what changes shape, in one line>

Follow the skill `cdv-refactor` (the five rules and Step 6) and the repository's extension. Read
`STATE.md` and `decisions.md` of this folder first.

## Goal

<Two to five lines: which files hold several jobs today, and the shape they have afterwards.
Behaviour does not change. Name the decision of `decisions.md` this slice serves.>

## Yours

<The files and folders only this slice edits. New files stay inside them.>

## Not yours

<What sits next to it and belongs to another slice, to the main branch, or to nobody yet.>

## Shape to reach

<The parts, by name, and what each owns. One line each. Where two copies become one: "the
differences stay, as named options".>

## Records missing today

<What no record holds yet and this slice will change. The builder completes the list by reading the
code and records each on the code as it is, before any other edit.>

## Error classes that apply

<Headings of `references/error-classes.md`: for example "Recording", "Moving and splitting".>

## Done when

- Every record that existed at the start is unchanged and passes.
- <the targeted checks of this slice, as commands>
- <the cases of old against new that belong to this slice come out empty>
- `docs_follow_code.py --base <start>` exits 0.
- <N> planted changes go red and are removed: <one line each>.
- <a size or a list that must fall, with today's number: recount>

## Stop and ask

<The decisions this slice may meet and must not take alone: a difference between copies, a defect,
a name that may be stored, a file of another slice.>

## Report

Commits oldest first; the map "part of the old file -> new file"; the differences kept; defects
pinned (also appended to `bugs.md`); what was not run. Notes kept in <a folder outside temporary
storage> from the first decision on.
```
