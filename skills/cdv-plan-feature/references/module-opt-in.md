# Module opt-in — does this feature get born as a module?

Loaded by the **Module gate** in Step 1. The decision that adopted modules, how to build and keep a module once it exists, and the repository's own examples are in the extension (`<profile.extension_dir>/cdv-plan-feature.md`, heading "Module opt-in"); a repository whose extension names no module convention skips the gate.

**Scope test.** This applies when a **greenfield** feature is being planned and the opt-in question ("does it get born as a module?") is on the table. It does **not** apply to retrofitting existing code into modules (that requires a dedicated project, never a side effect of a feature), to features that clearly live inside an existing domain's services, or to frontend work (the frontend's own modularity stays where it is).

## Opt-in criteria (the judgment call)

A feature MAY be born as a module when most of these hold (per `profile.module_design_skill` — use it when the call is not obvious; skip when `none`):

- It has its **own ubiquitous language** — nouns/verbs that mean something specific inside the feature and little outside (a booking, its window, requester, approver, cancellation reason).
- Its **integration surface with the rest of the app is small and nameable** — a handful of read points and signals, not diffuse coupling.
- It has a **distinct lifecycle** the rest of the app does not share.
- It would otherwise scatter across the services, models and console folders with nothing stating its boundary.

When in doubt, don't: a plain service folder per domain is not a failure, and merging a premature module back is more expensive than promoting a folder later. Modules are **opt-in by judgment**: a greenfield feature is born as one only when the criteria hold, and existing code moves only in a dedicated retrofit project. Modules are not the default, and the criterion above, not the pattern, decides.
