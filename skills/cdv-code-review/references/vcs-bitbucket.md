# Bitbucket — host specifics for the code review

Read by `cdv-code-review` (and `cdv-pr-review`) when `profile.vcs_host` is `bitbucket`. The PR client is the bundled `bb` of `cdv-open-pr` (`profile.pr_cli`); there is no `gh` here. Auto-posting is out of scope by design: the review skills write local files and never call a posting command.

## Reading a PR by number (PR-number mode)

1. `<profile.pr_cli> pr view <n>` prints the header, which carries the source and destination branch names (`#<n> OPEN <source> → <destination>`), and the description. Those are the head ref and the base ref.
2. The changed-file list comes from git, not from the host: `git fetch origin <head-ref>`, then `git diff origin/<base-ref>...origin/<head-ref> --name-only` (and the `--stat` and `git log` equivalents). Run `verify-anchors.sh <review dir> origin/<base-ref> origin/<head-ref>` to validate anchors without a checkout.
3. The comments already on the PR are not exposed by `pr view`; when the user wants them counted as existing findings, they paste them into the chat.

## Paste guidance (copy into `INDEX.md`)

1. Open the Bitbucket PR diff. For each per-finding file, navigate to the cited `file:line` and click "Add comment" on that line.
2. Paste the **entire** file body into the empty comment editor — one file at a time. Do not concatenate multiple findings into a single comment; the Bitbucket editor wraps multi-section markdown in a code block and breaks rendering.
3. `_summary.md` goes as a *general* PR comment (the comment box at the bottom of the PR, not on a diff line).
4. If a paste still renders raw inside a code block, the fallback is posting via the Bitbucket API with the file content as `content.raw` — Bitbucket renders markdown reliably on that path. `<profile.pr_cli> pr comment <n> --body-file <file>` posts a general comment that way, and only when the user asks.

`INDEX.md`'s one-line tip (pt-BR): *Clique no editor de comentário vazio do Bitbucket e cole. Se ainda assim virar code block, o caminho garantido é postar via API do Bitbucket usando o conteúdo como `content.raw`.*
