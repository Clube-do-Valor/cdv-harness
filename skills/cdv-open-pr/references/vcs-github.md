# GitHub — how `cdv-open-pr` talks to the host

Read when `profile.vcs_host` is `github`. `profile.pr_cli` is `gh` (the GitHub CLI), already authenticated for the developer. The repository (`profile.vcs_repo`, `owner/repo`) comes from the `origin` remote; pass `--repo <profile.vcs_repo>` when the working directory has more than one remote.

## Setup (once per developer)

`gh auth login` in a terminal (not through the chat — the prompt needs a real TTY), with the scopes `repo` and `read:org`. `gh auth status` must show your own account. Never paste a token in the chat and never print one.

## Commands

| Need | Command |
|---|---|
| credential check | `gh auth status` (exit 0 = valid) |
| open PR of a branch (Step 2) | `gh pr list --head <branch> --state open` (empty = none) |
| create (Step 5) | `gh pr create --base <profile.default_branch> --head <branch> --title "<title>" --body-file <slug>-pr.md` — not draft unless `--draft`; add the Claude Code footer to the body once before writing it; reviewers come from CODEOWNERS, add `--reviewer` only when the user asked |
| update the description (Step 6) | `gh pr edit <N> --body-file <slug>-pr.md` |
| read a PR back | `gh pr view <N>` (the body alone: `gh pr view <N> --json body --jq .body`) |
| list PRs | `gh pr list [--state open\|merged\|closed]` |
| comment (only when the user asks to post) | `gh pr comment <N> --body-file <f>` |
| CI status of a branch | `gh run list --branch <branch>` |
| mention a person in a description | `@login` |

`close_source_branch` has no per-PR flag on GitHub: delete-branch-on-merge is a repository setting. There is no token fallback through Chrome: without a valid `gh` login, ask the user to log in and stop.

## Pushing

`git push -u origin <branch>` prints a "create a pull request" link for the branch. That link is for a human; the PR is opened with `gh pr create`.
