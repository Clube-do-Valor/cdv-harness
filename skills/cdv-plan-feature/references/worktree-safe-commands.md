# Worktree-safe commands

Load when the session is isolated in a worktree (large tier, Step 0). When the session runs under a command guard (the extension says whether it does), the guard checks every Bash call of a worktree-isolated session and **refuses any command it cannot prove stays inside the worktree**. It judges the shape of the command, not its intent. These are the shapes that pass and the ones that do not.

## Refused shapes

| Shape | Why it is refused | Example that failed |
|---|---|---|
| A variable inside `docker run`/`docker compose` | the guard cannot know what the variable expands to | `WT=$(pwd); <container command using $WT> …` |
| `cd` to the main checkout, then `git` | leaves the worktree | `cd <main checkout> && git log …` |
| Python/heredoc whose text mentions `git` | a program computed at runtime | `python3 - <<'EOF' … subprocess.run(["git", …]) … EOF` |
| Several `git` invocations chained with `;`/`&&`/`\|\|` in one line | "too complex to verify" | `git fetch && git rebase origin/<default branch> && git log --oneline -3` |
| `sed`/`awk` with a runtime value where an option could stand | the value could be an option | `sed -i "s/x/$D/" file` |

## Shapes that pass

- One `git` per Bash call, with literal arguments: `git status --porcelain`, `git log --oneline origin/<default branch>..HEAD`.
- Gates through the repository's worktree runner (`profile.worktree_runner`), which is a literal path: `<profile.worktree_runner> <worktree path> <test command> <filter>`. The variables live inside the script, where the guard does not look.
- Reads and edits of files inside the worktree with the `Read`/`Edit` tools (they are not Bash).
- `grep`, `find`, `cat` with literal paths inside the worktree.
- Comparing against the main checkout's tree without leaving: `git diff origin/<default branch>...HEAD -- <path>` (refs, not `cd`).

## Rules of thumb

1. Need a variable in a docker command? It belongs in the worktree runner script, not in the call.
2. Need to look at the main checkout? Use a ref (`origin/<default branch>`), never `cd`.
3. Need to script git? Write the script to the worktree with `Write`, then run it by literal path — or do one `git` per call.
4. When the guard refuses, do not retry the same shape with cosmetic changes; pick a passing shape from this page.

## Small tier does not need this page

Small-tier work (≤ ~3 files, no migration, no new screen) runs on the main checkout after `profile.bring_branch_script` confirmed no other session's WIP is there — no worktree, no guard, the container prefix (`profile.cmd_container_exec`) works as usual.
