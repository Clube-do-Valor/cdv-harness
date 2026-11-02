---
name: cdv-research-round
description: Run a research round — survey the state of the art, the code and the usage evidence for a feature or idea through subagents — inside one folder on disk that holds a README, every subagent's output and the synthesis, tied to a task in the task tracker. Triggers on "rodada de pesquisa", "pesquisa essa feature", "levanta o estado da arte", "/cdv-research-round". Do NOT use to interview the user about decisions (`cdv-grilling`), to plan or implement a feature (`cdv-plan-feature`), or to debug (`cdv-debug`).
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Research round

A round is a folder, not a conversation. It opens with a README and a task in the task tracker before any subagent runs, every subagent writes into it, and it closes with a synthesis file that the `cdv-grilling` turns into `decisions.md` in the same folder.

## Step 0 — Load the profile and the extension

1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). This skill is also installed per user, outside any repository (`harness sync --user`), so a missing `profile.yaml` does not stop it: outside a consumer repository, use the neutral defaults stated in this file (the round goes under `docs/research/` in the working repository when it is a repository, or in a folder the user names; no task tracker) and say in your first message that you are running without a profile.
2. Read `<profile.extension_dir>/cdv-research-round.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.

Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

## Why this shape

Rounds that convert into a PR share one shape: a folder with a README, numbered research files, a synthesis and a decisions ledger.

## Step 1 — Open the round, before the first subagent

1. **Name it.** `<AAAA-MM-DD>-<slug>`, today's date and a kebab-case slug in English, as the `cdv-grilling` names its folders.
2. **Place it.** `<profile.research_dir>/<AAAA-MM-DD>-<slug>/` in the current repository (without a profile: `docs/research/`; create the research directory if missing). **Exception:** a repository that has no research directory and forbids committed research (its instructions file says so) gets the same structure in a folder outside the repository, at the location the extension or the user names. Say in your first message which of the two you used and why.
3. **Write `README.md`** from [references/readme-template.md](references/readme-template.md): title, one context paragraph (what is asked, why now, what is out), the `Tarefa` line and the file table. The table starts empty and gains one row per file as it lands.
4. **Create the task.** In the task tracker named by the profile (`profile.research_task_cli`) or the user, create a task titled `Pesquisa: <slug>` whose description is the absolute path of the folder and the objective in one line, and write the key it prints into the README's `Tarefa` line. When there is no tracker, or it is not available or refuses (a permission switched off, or this session is a delegated child of an orchestrator, to which task tools are not offered), write `Tarefa: nenhuma — <reason>` instead, say so in your message, and go on.

## Step 2 — Subagents write into the folder

1. **Every output lands in `research/NN-<tema>.md`** inside the folder — `NN` two digits in launch order, `tema` kebab-case in the language of the round. Never only in the chat: the chat reply is a summary of at most ten lines plus the file path.
2. **The brief names the absolute output path** and says the subagent writes the file itself. An agent without Write (`Explore`, `Plan`) returns its full output, and you write it to its file verbatim before reading the next result.
3. **Model rule.** Every `Agent`/`Task` call names `model` explicitly; nothing inherits. Research and `Explore` agents run on `sonnet` or `opus` — `opus` when the agent must judge or synthesize, `sonnet` for surveys and extraction. Never Fable.
4. **Scripts and raw data** go under `scripts/` (raw outputs in `scripts/out/`) inside the folder, so a number in a research file can be reproduced.
5. After each result, check the file exists and add its row to the README table.

## Step 3 — Publication

No claude.ai page by default. Publish an Artifact only when the round has a named external reader — the maintainer of another repository, a PM, a Notion card — and then keep its source under `artifact/` in the folder and write the link into the README (`Página publicada: <url> — para <reader>`). A page for the user alone is a file in the folder, read locally.

## Step 4 — Synthesis and exit

1. **Write `research/NN-sintese.md`** (the next number): what the round found, with a pointer to the research file behind each claim, the proposal, what would kill it, and the questions left for a decision. Add it to the README table.
2. **Offer the `cdv-grilling` as the next step**, via `AskUserQuestion`: interview the decisions now (`cdv-grilling` writes `decisions.md` in this same folder and reuses this round's task key from the README instead of creating another task); a handoff for a fresh session (`cdv-handoff`); stop here. Offer only the exits whose skill is installed.
3. **Say what is untracked.** A round in the repository's research directory is versioned whole: list the files not yet in git and offer a `docs(research):` commit. The external exception folder is never committed.

## Where this file lives

Installed per repository by cdv-harness, or per user with `harness sync --user`. Edit the core (`skills/cdv-research-round/` in the cdv-harness repository), never the installed copy.
