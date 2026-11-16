# Optional step: mock-before-after

One page that shows the screen as it is today and as it would be, so how it looks is decided by
looking, before anyone writes the plan.

## Signal

`propose_profile.py` lists `mock-before-after` when how something looks is still to be decided
(`appearance_decision: true`) or the change touches an existing screen
(`changes_existing_screen: true`).

## When it runs

After the screen and the grilling, before the plan: the stop `plan-approval` comes after the
developer has chosen on the mock.

## Recipe

1. Capture today's screen from the running local application: the markup of the screen, its
   states (empty, full, error) and the real records it shows (local QA data, never production).
2. Build one page that switches between today and the proposal with a single toggle (and a toggle per state or mode when the screen has them), with almost no text around it.
3. Build it from the application's own tokens (its colours, spacing, type and components, read from the source) and real labels copied from the screen's source, so the proposal looks exactly as it would ship, with no annotation layer marking what is new.
4. When there is more than one proposal, number them and mark the recommended one; the developer
   answers with the number.
5. Publish it as a private page with the host's page tool (an artifact) or, without one, as
   `mock-before-after.html` in the run's work folder.
6. Show it to the developer before the plan, with one line asking for the choice.

## Output

The page's link or path, the choice the developer made, and that choice carried into the plan as
a decision with the page as its source.

## Stop

Stop at the choice: no plan is written until the developer has looked at the page and answered.
Any name in the page that is not a real label of the screen is invented, and checked against the
local data so it names no real person or client.
