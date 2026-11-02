# PR link — Bitbucket (`profile.vcs_host: bitbucket`)

Read by `cdv-factory-finalize` Step 5.4. The factory never creates the PR (not through `profile.pr_cli` either): it hands the human the link that opens the creation form with the branch already chosen. `<host>` below is the host of `git remote get-url origin` (the Bitbucket Cloud host, or the self-hosted one).

1. The Bitbucket push prints `remote: Create pull request for <target>:` followed by a line of the form `https://<host>/<workspace>/<repo>/pull-requests/new?source=<target>&t=1` — copy that URL.
2. When the output has none (hook output swallowed, a quiet push), build it from `profile.vcs_repo` (`<workspace>/<repo>`): `https://<host>/<profile.vcs_repo>/pull-requests/new?source=<target>&t=1`. When `profile.vcs_repo` is missing, derive `<workspace>/<repo>` from `git remote get-url origin` (an SSH remote `<user>@<host>:<workspace>/<repo>.git` or an HTTPS one).
3. In the delivery form, the host is called *Bitbucket* ("a descrição do PR está pronta no worktree, para colar no Bitbucket").
