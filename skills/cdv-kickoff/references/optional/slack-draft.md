# Optional step: slack-draft

A reply to the person who asked, written in the developer's voice and left as a draft.

## Signal

`propose_profile.py` lists `slack-draft` when the request came from a chat thread
(`origin: chat-thread`) or someone is waiting for an answer (`waiting_reply: true`).

## When it runs

At the end of the stage whose result that person is waiting for: after the screen for a question
about scope, after the plan for a proposal, after the pull request for a delivery. The run profile's
chain does not wait for it.

## Recipe

1. First, read the whole thread and three messages the developer wrote to that person, through the chat connector (the newest ones in a direct conversation, or in a shared channel when there is none), to take their language, length and tone.
2. Write the reply in that voice: what was decided or delivered, what the person has to do (if
   anything), and the link (the artifact, the plan page, the pull request), with no internal
   detail the person did not ask for.
3. Save it as a draft in the thread with the connector's draft tool, or, when the connector has no
   draft tool, as `slack-draft.md` in the run's work folder.

## Output

The draft (where it was saved) and its text in the final report of the stage, so the developer
reads it before anything else.

## Stop

The step ends at the draft. Never send the draft and never post it in the thread: the developer
reads it and decides. A recipient the developer has never written to is no reason to guess a tone:
say so in the report and keep the draft neutral.
