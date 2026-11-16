# Optional step: blind-judges

Two people who never saw the work try the new screen, each on their own, and say where they got
stuck.

## Signal

`propose_profile.py` lists `blind-judges` when the change adds a new screen (`new_screen: true`)
whose users are not the developer (`screen_audience_other: true`).

## When it runs

After the browser QA (`qa`) is green and before `finalize`, so the findings can still change the
screen in the same pull request.

## Recipe

1. Write one brief for both judges in the run's work folder (`judges/brief.md`): who the users
   are, the tasks to try in their words, the address and the login link, and nothing about how the
   screen was built or what the plan expects.
2. Run two judges one after the other on the role `judge` (`role_target.py judge` gives the provider, the model and the effort; `brief.py render judge` gives the start of each brief), never at the same time: they share one browser and one login.
3. Each judge works without the other judge's output: it receives the brief alone, writes `judges/judge-<n>.md` (each task, where it hesitated, what it expected, a screenshot of each problem) and never reads the folder.
4. Clear the screen's data between the two judges (the rows the first judge created or changed, back to the state the brief describes), so the second judge sees nothing the first one left.
5. When both are back, write `judges/synthesis.md`: the problems both judges hit first, then each
   one's alone, each with its screenshot and the change it suggests.

## Output

The synthesis in the final report and, for each problem worth fixing, one line for the fix child;
the problems left as they are go into the pull request description.

## Stop

A judge that would create or change anything outside the screen under test (an external record, a
message to a person) stops and asks the orchestrator, which stops and asks the developer when the
run is unattended. The judges never read the code, the plan or each other's notes.
