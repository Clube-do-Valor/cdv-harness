---
name: cdv-handoff
description: >
  Write the handoff block that lets a FRESH Claude session pick up work in this repository — QA of a branch, a code review, a continued investigation — without the current session's context. Verified facts only (git counts, worktree, fixtures, production-affecting steps), rendered in the chat for copy-paste; a HANDOFF-<slug>.md file only on request. Triggers on "handoff prompt", "prompt pra outra sessão", "me dá um handoff", "hand this off to a fresh session", "passa isso pra uma sessão nova", and the wrap-up of `cdv-finalize`. Do NOT use to summarize a conversation for a human (write prose), to generate the PR description (`cdv-finalize`) or the ticket note (`cdv-notion-ticket`).
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Handoff

A fresh session does better QA and better review than the session that implemented — less context, no attachment to the code. That is a deliberate practice, and it lives or dies by the handoff. This skill makes every one of them that good.

## Operating principles

- **Facts are verified, not remembered.** Every count, path and id in the block comes from a command run now: `git rev-list --count origin/<branch>..HEAD`, `git worktree list`, `ls QA-<slug>.md`, the fixture ids grepped from the QA file. A handoff that says "3 commits may not be pushed" when the count is 5 sends the next session down the wrong path.
- **The reader has nothing but the block.** No "como vimos", no reference to this chat. Name the skill to invoke, the file to read, the command to run.
- **Chat by default.** The block is rendered in the chat inside a fenced code block for copy-paste. A `HANDOFF-<slug>.md` file (an ephemeral root file, `profile.ephemeral_patterns`: gitignored, never committed) only when the user asks for a file or the block exceeds ~60 lines.
- **Production-affecting steps are named, with the reason.** Not "cuidado com o passo 8" but what it writes where and why it cannot be undone.
- **PII discipline as everywhere:** ids and first names; emails are work identifiers and may appear; never national-id numbers, phone or address.

## When to use

- The `cdv-finalize` wrap-up (it prints the QA handoff itself, using this template).
- The user asks for a prompt to continue an investigation, run a review or run QA in another session.
- A session is about to be abandoned because its context grew (compaction looming, "this is getting long").

## Workflow

### Step 0 — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-handoff.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

### Step 1 — Determine the kind and gather facts (all read-only)

Kind ∈ `qa` | `review` | `investigation` | `continue-implementation`. Then run, and keep the raw output:

```
git branch --show-current
git worktree list --porcelain
git rev-list --count origin/<branch>..HEAD 2>/dev/null   # unpushed commits ('?' if no remote)
git rev-list --count HEAD..origin/<profile.default_branch> # behind the default branch
git status --porcelain | grep -v '^??'                   # uncommitted tracked
ls QA-<slug>.md STATE-<slug>.md <slug>-pr.md decisions-<slug>.md 2>/dev/null
grep -n 'PRODUCTION-AFFECTING' QA-<slug>.md 2>/dev/null
```

For `qa`: the fixtures come from the QA file's own steps (ids + display labels, the way `cdv-interactive-qa` needs them). For `review`: the ticket id via `cdv-code-review/scripts/resolve-ticket-id.sh` and whether a `<profile.pr_review_dir_prefix><TICKET>/` already exists. For `investigation`: the hypotheses block and the evidence table from the `cdv-debug` report, verbatim. For `continue-implementation`: the `STATE-<slug>.md` phase statuses, its `## Finalize seed` and whether `## Verificação` exists.

### Step 2 — Render the block

Fenced code block, in `profile.language_ui` (the PT-BR section headings below stay as written), in this order; drop a section only when it is truly empty, and say so (`Sem fixtures pré-consultadas.`):

```
<VERBO> da branch <branch> (<uma frase do que ela entrega>).

ONDE ESTÁ O CÓDIGO
- <worktree path | checkout principal `profile.main_checkout`>
- <N> commits à frente de origin/<profile.default_branch>; <M> commits NÃO pushados (confira: git rev-list --count origin/<branch>..HEAD)
- <uncommitted tracked files, or "árvore limpa">

ARMADILHA DO AMBIENTE  (only when the code is in a worktree and `profile.worktree_runner` is not `none`)
- O worktree não tem o ambiente do checkout principal (dependências, `.env`); `profile.cmd_container_exec` testa o checkout principal, não este.
- Todo gate por: <profile.worktree_runner> <worktree> <comando de teste> <filtro>
- Para QA na tela: trazer a branch com <profile.bring_branch_script> --check <branch> e depois sem --check. Se recusar, PARE e pergunte — é WIP de outra sessão. Nunca git stash.
- Baseline atual: <N passed (M assertions)>, formatador <PASS>, análise estática <OK>.

O QUE FAZER
- Invoque a skill <cdv-interactive-qa | cdv-code-review | cdv-debug | cdv-plan-feature>.
- <roteiro/arquivo a ler, with path> | <ticket id> | <report to start from>

FIXTURES REAIS (validadas em <data>)
- <entidade> <id> (<label como a tela mostra>) — <estado que interessa>
- ...

PASSOS QUE ESCREVEM FORA DO LOCAL  [PRODUCTION-AFFECTING]
- Passo <n>: escreve <o quê> em <sistema externo, de `profile.production_writing_integrations`>; irreversível porque <motivo>. Só o usuário roda, depois de confirmar <o quê>.
- (or) Nenhum — tudo é leitura ou escrita só no banco local.

CONTEXTO QUE MUDA A EXPECTATIVA
- <the one or two facts that would otherwise look like bugs: "o comando de exportação sai com exit 0 por decisão", "o export roda só de madrugada — testar com o comando manual é o esperado">

NÃO FAÇA
- Não troque a branch do checkout principal por cima de WIP alheio; não use git stash.
- <anything the user excluded: "não investigar os dois registros duplicados">
```

`<VERBO>` is `Rode o QA interativo`, `Faça o code review`, `Continue a investigação` or `Continue a implementação`.

### Step 3 — Self-check before printing

- Every number came from a command in Step 1 (re-run it if the tree changed).
- Every path exists (`ls`).
- No sentence needs this chat to be understood.
- The PRODUCTION-AFFECTING section is present (with content or with "Nenhum").

## Composition

- `cdv-finalize` — prints the `qa` kind at its wrap-up using this template; when this skill is invoked on its own after a finalize, reuse the state report's numbers instead of re-deriving them.
- `cdv-interactive-qa`, `cdv-code-review`, `cdv-debug`, `cdv-plan-feature` — the receivers. The block names which one to invoke.
- `cdv-code-review` third-party mode — a review handoff for a colleague's PR says so explicitly (`branch de terceiro: sem apply-review`).

## Example (qa kind, condensed)

```
Rode o QA interativo da branch fix/export-stale-file (o export escrevia o arquivo de ontem
depois de uma nova execução manual; agora grava o arquivo do dia e remove o anterior).

ONDE ESTÁ O CÓDIGO
- worktree .claude-worktrees/export-stale-file
- 5 commits à frente de origin/<branch padrão>; 2 NÃO pushados (git rev-list --count origin/fix/export-stale-file..HEAD)
- árvore limpa

ARMADILHA DO AMBIENTE
- Worktree sem o ambiente do checkout principal: gates pelo executor de worktree; para a tela, o script de trazer a branch com --check primeiro.
- Baseline: suíte de testes verde, formatador PASS, análise estática OK.

O QUE FAZER
- Invoque cdv-interactive-qa; roteiro em QA-export-stale-file.md (6 passos).

FIXTURES REAIS (validadas na data do handoff)
- relatório 7 (Vendas — semana) — exportado ontem, o arquivo antigo ainda existe (o caso a reparar)
- relatório 8 (Estoque — semana) — nunca exportado (o caso limpo)

PASSOS QUE ESCREVEM FORA DO LOCAL
- Passo 4: o one-off LÊ a API externa real (uma chamada por item) para conferir os totais; nunca escreve nela. Se algo sugerir escrita, pare.
- Nenhum outro — o export grava só no disco local.

CONTEXTO QUE MUDA A EXPECTATIVA
- O export roda só de madrugada — testar com o comando manual é o esperado.

NÃO FAÇA
- Não troque a branch do checkout principal por cima de WIP alheio; não use git stash.
```
