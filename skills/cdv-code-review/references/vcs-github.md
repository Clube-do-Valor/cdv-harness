# GitHub — host specifics for the code review

Read by `cdv-code-review` (and `cdv-pr-review`) when `profile.vcs_host` is `github`. The PR client is `gh` (`profile.pr_cli`). Auto-posting is out of scope by design: the review skills write local files and never call a posting command.

## Reading a PR by number (PR-number mode)

1. `gh pr view <n> --json headRefName,baseRefName,number` gives the head ref and the base ref; `gh pr diff <n> --name-only` lists the changed files.
2. `git fetch origin <head-ref>` and run the diff against `origin/<base-ref>` (`git diff origin/<base-ref>...origin/<head-ref>`). Run `verify-anchors.sh <review dir> origin/<base-ref> origin/<head-ref>` to validate anchors without a checkout.
3. The comments already on the PR: `gh pr view <n> --comments`; load them as existing findings.

## Paste guidance (copy into `INDEX.md`)

1. Open the PR's "Files changed" tab. For each per-finding file, navigate to the cited `file:line`, click the `+` on that line and paste.
2. Paste the **entire** file body into the empty comment box — one file at a time. Do not concatenate findings into a single comment. GitHub renders the markdown (headers, bold, fenced blocks) as it is written.
3. `_summary.md` goes as a *general* PR comment (the "Conversation" tab, or `gh pr comment <n> --body-file <review dir>/_summary.md` when the user asks to post it).
4. A paste that renders raw is rare on GitHub; if it happens, post the file with `gh pr comment <n> --body-file <file>` (general comment) and mention the anchor in the first line.

`INDEX.md`'s one-line tip (pt-BR): *Abra "Files changed", clique no `+` da linha indicada e cole o arquivo inteiro. Para o `_summary.md`, use a aba Conversation.*
