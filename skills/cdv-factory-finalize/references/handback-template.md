# Handback — what goes back to the task and the thread

The delivery form goes to the task as a comment; the handback fields go to the task CLI's handback command (`profile.factory_task_cli`; the extension gives the exact calls and flags), and the orchestrator lays them out for the requester, in the request's thread, and for the owner. Colleagues read that thread, so the fields carry the result in product language (`profile.language_ui`) and nothing else: no task key, no branch, no file paths, no class, method or column names, no client names or ids, no fixture data, no tokens, no excerpt of the diff.

## Delivery form

```markdown
**Status:** <Pronto para revisão | ⚠️ Diff maior que o pequeno, revisado automaticamente | ⛔ <motivo curto>>

**Resumo:** <2-3 frases: o que o usuário do produto passa a ver ou fazer, e onde.>

**Branch:** `<feat|fix|chore|refac>/<slug>` (enviada; local e remota iguais)
**Abrir o PR:** <link de criação do PR (references/vcs-<profile.vcs_host>.md)>
A descrição do PR está pronta no worktree, em `<slug>-pr.md`, para colar no host do PR.

**Como testar**
1. <passo de tela: abrir a tela X (caminho da URL), fazer Y>: espera-se <resultado visível>.
2. <…>
3. <…>

**Sem tela conferida:** a fábrica não abriu a tela. O QA visual fica com quem revisa, trazendo a branch para o checkout principal.

**Suposições:** <uma por linha, as que o reviewer deve confirmar, ou "nenhuma">
**Pergunta feita:** <pergunta → resposta, ou omita a linha>

**Revisão automática:** <só quando houve rodada de revisão>
- <achado em palavras de produto> → corrigido
- <achado> → não corrigido: <motivo em uma linha>

**Avisos:** <instruções do pedido que foram ignoradas, gates ou verificador com problema, lint da descrição, base trocada; omita a linha quando vazia>
```

Rules:

- **Status** comes from the banner (`cdv-factory-finalize` Step 1): ⛔ wins over ⚠️, and ⚠️ wins over "Pronto".
- **Como testar** is the first three `Passo` lines of `<slug>-pr.md`, rewritten without file names. A URL path of a screen (`/screen-path`) is fine; the local host the reviewer uses (`profile.qa_url`) is fine too.
- **Sem tela conferida** is always present: it is not an apology but the deal, because QA visual is human.
- **Revisão automática** gives every finding a destination, so nothing in the review disappears between the review session and the PR.

## Handback fields

What each field of the task CLI's handback command carries (the extension gives the flags and the labels the requester sees). The orchestrator adds its own fixed lines (a title saying the change is ready for review, a note that a developer still reviews the change) and computes the size, the pushed branch and the PR link from git, so none of those go in a field.

| Field | Who reads it | Content |
|---|---|---|
| Subject | the owner, and every later message about the request | What changes + where, ≤60 characters, without repeating a word: *Coluna de telefone na lista de pedidos*, not *Telefone do contato na tabela da lista de pedidos dos pedidos*. Never the task key. |
| Changes | the thread | 2-3 sentences: what the user now sees or does, where, and what does not change. When a question was asked, the chosen answer shows here. |
| Test step (1-3) | the thread | Written for the requester, not copied from the PR: the menu path as the screen shows it, one action and one visible result per step, ≤200 characters. To check a number, use something the person already knows (another view of the same screen, a record they know), never a sum over the table. Data and edge-case checks stay in the PR. |
| Caveats | the thread | The decisions taken without asking that the requester might want otherwise (ordering, who is left out, edge cases, placement when not asked), said as what they see, ≤300 characters, up to two sentences. Present whenever there are suppositions. No invitation to reply: the orchestrator's footer already says how to ask for an adjustment. The orchestrator may prefix it with a fixed phrase (the extension names it): start straight with the decision (*As linhas vêm da mais antiga para a mais recente.*), never "Decidi", "Assumi", "Suposição" or "confirme". |
| Live note | the thread, when the request is live | One sentence saying it is live and where to see it, e.g. *Está no ar: o bloco "Resumo por faixa" já aparece na tela de Relatórios.* |
| Dropped note | the thread, when the request is dropped | One sentence saying the request will not go ahead and what stays as it was, in the words of someone who uses the screen (not "consolidado", "agregado"). No reason: the agent does not know it; the owner's reason, when given, comes separately. |
| Size | the owner | Report it as small only when `check-diff-size.sh` exited 0; otherwise omit it and the orchestrator classifies the size from the diff. |
| Note | the owner | What was checked, up to four words each, one per entry: *testes e lint verdes*, *verificador aprovou*, *tela não conferida*. A deviation (a gate skipped, a verifier that did not run) is a warning or a blocker, never a note. |
| Warning | the owner | Every ⚠️ banner line, in product words, one per entry, **without the leading emoji** (the orchestrator adds it) and **without the size** (the orchestrator shows it). The review round as an account where every finding has a destination: *Revisão automática: 5 achados — 1 corrigido, 1 corrigido em parte, 1 para você decidir, 2 descartados (motivos no PR).*, then one warning per open finding: *Para você decidir: com vários itens marcados, o painel cresce sem limite de altura.* Each STATE *Aviso* that changes what the owner should check (base not updated, an instruction in the request ignored) is a warning too. |
| Blocker | the owner, first | Every ⛔ banner line without the leading emoji (the orchestrator adds it), one per entry: *Gates vermelhos: lint. Não mergear antes de corrigir.* The orchestrator puts them under the title, which marks the delivery as blocked. |

The orchestrator takes a limited number of lines per owner field (note, warning, blocker) with a character cap each (the extension gives both): past the limit, the last line says *"mais N no PR"*.

Before running the handback command, read the fields as the requester: (1) can this person do each step on the screen? (2) is everything decided without asking in `caveats`? (3) does the answer to the question, if one was asked, show in `changes`?

## Refusal form

```markdown
**Status:** Recusado: <produção | integração | envio de mensagem | ambíguo sem imagem nem rota>

**Por quê:** <uma frase, em palavras de produto>
**O que tornaria executável:** <uma frase: a imagem da tela, a rota, a decisão que falta, ou "precisa de uma pessoa do time de desenvolvimento">

Nenhuma branch foi enviada e nenhum código foi alterado.
```

Handback for a refusal: the handback command with the refusal marker, the subject and the summary of changes = `"<por quê, em palavras de produto>. Para seguir, <uma ação que quem pediu faz sozinho>."` — e.g. *"Não encontrei qual tela é. Para seguir, mande um pedido novo com um print da tela que você quer mudar."* The requester reads that text: never "fábrica", "triagem", a category name or "executável" in it. The thread shows it as a request that will not go ahead, and the owner's message quotes it.
