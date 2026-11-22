---
tags: [cdv-refactor]
max_turns: 80
timeout_seconds: 1800
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

`invoicing/report.py` has turned into a god class: parsing, tax maths and text rendering all live in `InvoiceReport`. Split it into separate modules (one for parsing, one for tax and totals, one for rendering) so each piece can be worked on alone. Code that does `from invoicing.report import InvoiceReport` must keep working, and the tests must be green at the end.

Commit your work on the current branch with clear messages (it is a scratch repository, main is fine). I am offline until tomorrow, so do not wait on me: put anything you would have asked me in your final message, together with a short report of what you did.
