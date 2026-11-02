# PR link — GitHub (`profile.vcs_host: github`)

Read by `cdv-factory-finalize` Step 5.4. The factory never creates the PR (not through `gh pr create` either): it hands the human the link that opens the creation form with the branch already chosen. `<host>` below is the host of `git remote get-url origin` (github.com, or a GitHub Enterprise host).

1. The GitHub push prints `remote: Create a pull request for '<target>' on GitHub by visiting:` followed by a line of the form `https://<host>/<owner>/<repo>/pull/new/<target>` — copy that URL.
2. When the output has none, build it from `profile.vcs_repo` (`<owner>/<repo>`): `https://<host>/<profile.vcs_repo>/pull/new/<target>`. When `profile.vcs_repo` is missing, derive `<owner>/<repo>` from `git remote get-url origin` (an SSH remote `<user>@<host>:<owner>/<repo>.git` or an HTTPS one).
3. In the delivery form, the host is called *GitHub* ("a descrição do PR está pronta no worktree, para colar no GitHub").
