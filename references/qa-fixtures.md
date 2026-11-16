# QA fixtures — real, named, local

Shared reference, vendored to `.claude/harness/references/`. Load it before writing or running a QA step: `cdv-qa` driving the browser, a `## How to test` section of a pull request, a review's "how to reproduce", a handoff for QA. The repository's note (`<profile.extension_dir>/references/qa-fixtures.md`) names its QA data source and its traps.

A QA step is only as good as the fixture it names. An abstract expectation passes on an empty screen; an id alone cannot be found in a name search; a production host turns a test into a production write.

## Rules

1. **Real fixtures, pre-queried.** Before writing a step, read the QA data (`profile.qa_env`, read-only and DEV-SAFE) and pick the richest real record for the feature's scope: the one that exercises every field and edge. Bake its real id and the counts it should show into the step. Never a placeholder (`<id>`, `{your-client}`, "pick one of your records"): a step that cannot run passes by being skipped. The only literal braces allowed are route patterns echoed verbatim from the router.
2. **Name the fixture the way the screen names it.** Where the tester finds the record through the screen — a search box, a dropdown, an autocomplete, a filter — the step carries the label that screen displays (the person's name, the client's name). Ids go where they are consumed: URLs, query parameters, read-only probes, expected values. Write both, from the same query: `user 15 (Jane Doe)`, never the id alone. Cheap tell: a step that says "pick user 15" on a screen with no id column cannot be run as written.
3. **Derive the scope from the code that defines it.** For an owner-scoped screen, find the guard and the method behind it that decide "in scope", call that method in a read-only probe and pick an id it returns; then reproduce the guard end to end, so the URL gives 200 and not 404. A look-alike column on the table can diverge from the real scope.
4. **Check what a scope parameter really matches.** A parameter named after one identifier may be matched against another; trace how it is consumed. Where the scope is carried by a cookie or the session, the step first performs the action that sets it.
5. **Counts from the same source as the scope.** The expected numbers come from the query the guard uses; a count from another query is the tell that the fixture came from the wrong place.
6. **Personal data stays out of committed text.** Prefer opaque ids and counts. When a step needs identifying values (external-only fields), a read-only probe writes them to a git-ignored scratch file and prints only its path; the step points at that file and says which fields only the source system holds.
7. **Local only.** Every browser step targets the local application (`profile.qa_url`) or the run's side stack, never a production host.
8. **External test records are named and cleaned up.** A record created in an external system during QA carries `profile.qa_test_marker` in its name, is registered before it is created, and is deleted at the end of the run (`cdv-qa`). A record that cannot be deleted is listed with its system, type and id.
9. **Production-affecting steps are the developer's.** A step that writes to an external system shared with production, or reaches a person, is labeled `[PRODUCTION-AFFECTING]` and handed to the developer ([production-safety.md](production-safety.md)).

## Example

> ❌ Open the screen as an owner and expect their records with all fields.
>
> ✅ Open `<profile.qa_url>/records?owner=42` as owner 42 (Jane Doe, found by name in the owner picker): **37** records, **12** with a due date; an empty due date is the common case.
