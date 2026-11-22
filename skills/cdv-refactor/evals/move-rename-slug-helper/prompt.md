---
tags: [cdv-refactor]
max_turns: 80
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

Move `lib/helpers/slugify.js` to `src/text/slug.js` and rename `mkSlug` to `toSlug` everywhere. No re-export shim at the old path, I want one home for it. While you are in there, `mkSlugLegacy` is dead since the URL migration: delete it and its tests. `npm test` has to stay green.

Commit your work on the current branch with clear messages (it is a scratch repository, main is fine). I am offline until tomorrow, so do not wait on me: put anything you would have asked me in your final message, together with a short report of what you did.
