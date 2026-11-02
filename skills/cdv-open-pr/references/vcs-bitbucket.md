# Bitbucket — how `cdv-open-pr` talks to the host

Read when `profile.vcs_host` is `bitbucket`. `profile.pr_cli` is the bundled client, `scripts/bb` in this skill (installed as `.claude/skills/cdv-open-pr/scripts/bb`). The repository is parsed from `git remote get-url origin`; `$BITBUCKET_REPO` (`profile.vcs_repo`, `workspace/repo`) overrides it. The default destination of `pr create` is `profile.default_branch`.

## Setup (once per developer)

1. https://id.atlassian.com/manage-profile/security/api-tokens → **Create API token with scopes** → app **Bitbucket** → scopes `read:pullrequest:bitbucket`, `write:pullrequest:bitbucket`, `read:repository:bitbucket`, `read:pipeline:bitbucket`, `read:user:bitbucket`. No repository write scope: the push goes over SSH.
2. In a terminal at the repository root (not through the chat — the prompt needs a real TTY): `<profile.pr_cli> auth login`. It asks for the token with hidden input, checks it against Bitbucket and stores it in the GNOME keyring, like `gh auth login`; without a keyring it writes `~/.config/bitbucket/credentials` with mode 600. The e-mail comes from `git config user.email`. Never paste the token in the chat.
3. `bb auth status` must print your own name. A token in `$BITBUCKET_API_TOKEN` or in that credentials file also works.

`bb` authenticates with the developer's own Atlassian *API token with scopes*, so the PR, its notifications and the "author cannot approve" rule stay with whoever wrote the code. A repository access token (`ATCT…`) also works but authors the PR as a bot — not for interactive sessions. Never print the credentials file.

## Commands

| Need | Command |
|---|---|
| credential check | `bb auth status` (exit 0 = valid) |
| open PR of a branch (Step 2) | `bb pr for-branch <branch>` (prints it; exit 1 = none) |
| create (Step 5) | `bb pr create --title "<title>" --body-file <slug>-pr.md` — adds the repository's default reviewers minus the author, `close_source_branch`, and the Claude Code footer once; not draft unless `--draft` |
| update the description (Step 6) | `bb pr edit <N> --body-file <slug>-pr.md` |
| read a PR back | `bb pr view <N>` |
| list PRs | `bb pr list [--state OPEN\|MERGED\|DECLINED]` |
| comment (only when the user asks to post) | `bb pr comment <N> --body-file <f>` |
| CI status of a branch | `bb pipelines --branch <branch>` |
| mention a person in a description | `bb mention <name>` → the `@{account_id}` markup |

## Fallback without a token — Claude in Chrome

Only when the developer has no token and does not want to create one now (Step 0). Run Steps 2–4 the same way, then open the PR from the user's logged-in Chrome instead of `bb pr create`: navigate a tab to the `pull-requests/` page of the repository on the Bitbucket web host (`profile.vcs_repo`) and, with `javascript_tool`, `fetch('/!api/2.0/repositories/<profile.vcs_repo>/pullrequests', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': <the csrftoken cookie>}, body: JSON.stringify(payload)})`, where the payload is the one `bb` would send — title, description (the file's content, JSON-encoded), source and destination branches, `close_source_branch: true`, and the reviewers from `/!api/2.0/repositories/<profile.vcs_repo>/effective-default-reviewers` minus the author. Read back `id` and `links.html.href`, close the tab, and end the report with one line recommending the token for the next PR. An update (Step 6) in Chrome is the same call with `PUT` on `pullrequests/<N>`.

## Pushing

`git push -u origin <branch>` prints a "create pull request" link for the branch. That link is for a human; the PR is opened with `bb pr create`, never by following it.
