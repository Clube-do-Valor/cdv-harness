# Optional step: validation-page

A page the owner of the business rule reads and confirms before the build, one rule at a time.

## Signal

`propose_profile.py` lists `validation-page` when a business rule must be confirmed by someone who
is not the developer before the build (`owner_must_validate: true`).

## When it runs

After the plan is drafted and before the stop `plan-approval`: the owner's answers can still change
the criteria.

## Recipe

1. List the rules the plan's criteria encode, one by one; never summarise them as a count.
2. Write each rule as Given, When, Then in business language, with one concrete example (people and values invented, the same cast in every example so the numbers agree) and a realistic mock beside it of the screen or the message where the rule shows.
3. Next to each rule, quote the passage of the request (the card, the document, the prototype)
   it comes from, or say that it is new.
4. Leave every estimate out: no dates, effort or size, only the rules and what they do.
5. Check every invented name against the local data before publishing, so no example puts a real person or client beside a rule or a flag.
6. Publish it as a private page with the host's page tool (an artifact), or, without one, as
   `validation-page.html` in the run's work folder.

## Output

The page's link or path, and one question per rule for the owner (confirm, change, remove), whose
answers go into the plan before its approval.

## Stop

Stop at the publication: the page is handed to the owner by the developer, never by the agent,
and the build does not start until the rules the owner changed are back in the plan.
