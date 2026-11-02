---
name: cdv-flows
description: >
  Menu interativo dos fluxos de trabalho assistido do repositório — apresenta as situações em linguagem plana, as fronteiras entre skills parecidos e as jornadas compostas (quem passa o quê para quem), e faz hand-off para o skill escolhido. Só roda quando chamado explicitamente com /cdv-flows; nunca dispara por frase natural — quem já sabe o que quer fala direto com o skill de destino.
disable-model-invocation: true
metadata:
  version: 0.1.0
  owner: augusto-henriques
---

# Flows (porta de entrada)

Menu sob demanda para quem não sabe (ou quer relembrar) qual fluxo usar. Este skill não executa trabalho: orienta e entrega a conversa ao skill certo.

## Step 0 — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-flows.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

## Step 1 — Load the map

When the repository has a skills index (`.claude/skills/README.md`), read it — it is the source of truth for triggers, boundaries and cross-cutting conventions. This skill renders the interactive layer on top of it; when the two diverge, the index wins. Without an index, the menu below and the extension are the map.

## Step 2 — Render the menu

Render the menu below as plain text in the chat (never AskUserQuestion — the answer is free: a number, or a description of the situation). Situations in plain language:

> **O que você quer fazer?**
>
> 1. **Ideia vaga, não sei como deveria funcionar** → `cdv-grilling` ("grill me": entrevista até fechar o ledger de decisões). Spec decidida? Vá ao 2.
> 2. **Sei o que precisa ser feito: planejar e implementar** → `cdv-plan-feature`. Bug é o 3; ajuste de um arquivo só, edite direto.
> 3. **Algo quebrou / erro reportado** → `cdv-debug` (só investiga; o conserto ele entrega ao 2).
> 4. **Revisar uma branch** → `cdv-code-review` (passada única, o caso comum) ou `cdv-pr-review` (6 revisores paralelos, PR crítico; só roda chamado pelo nome). Ambos geram `<profile.pr_review_dir_prefix><TICKET>/`, que alimenta o 5 (colar no PR da `profile.vcs_host` é opcional).
> 5. **Tratar apontamentos de review (de qualquer origem)** → `cdv-apply-review` (triagem contra o código atual; aplica só os procedentes, um commit por item).
> 6. **Testar manualmente com segurança** → `cdv-interactive-qa` (escritas externas são sempre suas, nunca do agente).
> 7. **Commits organizados + PR aberto** → `cdv-finalize` (push e PR via `profile.pr_cli` e `cdv-open-pr`; só abrir ou atualizar um PR → `cdv-open-pr` direto).
> 8. **Nota de entrega para o card do Notion** (só quando `profile.ticket_system` é `notion`) → `cdv-notion-ticket`.
>
> **Trabalho de tela** em qualquer caminho: `cdv-frontend` e `profile.design_skill` (quando não é `none`) entram sozinhos na fase de frontend.
>
> Skills que só existem neste repositório (e o `profile.sessions_skill`, quando há) entram aqui pelas linhas que a extensão acrescenta.

## Step 3 — Journeys (quem passa o quê para quem)

When asked how flows connect, render the relevant chain — the value is the artifact that travels:

- **A — feature completa:** cdv-grilling ─(decisions.md + AC1..ACn)→ cdv-plan-feature ─(plano em STATE-<slug>.md)→ execução ─→ verificador (tabela AC a AC) ─→ cdv-finalize (commits + push + PR via cdv-open-pr) ─→ [cdv-interactive-qa] ─→ cdv-notion-ticket. Os ACs mantêm os mesmos ids do início ao fim.
- **B — bug ao conserto:** cdv-debug ─(relatório de causa raiz)→ cdv-plan-feature → segue a Jornada A.
- **C — review e correção:** implementação (sessão A) → review em **sessão nova** (olhos frescos) ─(`<profile.pr_review_dir_prefix><TICKET>/`)→ cdv-apply-review de volta na sessão da execução → cdv-finalize de novo.

Nenhuma jornada é obrigatória: todo skill funciona sozinho e dá para entrar em qualquer ponto da cadeia.

## Step 4 — Hand-off

- User picked a flow and already gave context → invoke the target skill via the `Skill` tool, passing that context verbatim.
- User picked a flow but has no context yet → end with the trigger phrase to use when ready (from the skills index or the skill's own description).
- User only wanted orientation → end after the menu/journey; do not invoke anything.

## Boundaries

- This skill never executes work, never edits files, never reviews code.
- Never auto-invoked (`disable-model-invocation`): natural-language triggers keep going straight to their skills; this menu exists only for `/cdv-flows`.
