# Plan Skeleton — Step 4 Template

Load when ready to render the multi-phase plan inline in the chat. Do NOT persist to disk. The template is written in PT-BR; its headings stay as written because other steps read them, and the prose follows `profile.language_ui`. `<app_dir>` is `profile.app_dir`.

## Template

```markdown
## Plano — <feature title in PT-BR>

### Resumo
<3–5 sentences in PT-BR: goal, prior state, what is delivered, branch name>

**Tier:** pequeno | grande — <one clause with the criterion that decided it: "3 arquivos, sem migration, sem tela nova" / "migration + tela nova"> → <consequence: "inline no checkout principal" / "worktree, executores em paralelo nas fases 2 e 4">. **`verificador: light | standard`** — <`light` by default; `standard` (só tier grande) when a branch table, a guard or a boundary needs proof that the tests would fail under a wrong implementation, and no deadline was stated>

### Restrições aplicadas
- <decision 1 from the Q&A or from the Shared Understanding>
- <decision 2>
- <hard rule that constrains the implementation, e.g. "aditividade no schema">

### Fase 1 — Migrations + Models + Factories
- **Migration**: `<YYYY_MM_DD_HHMMSS_create_<table>_table.php>` — colunas, índices, FKs (sempre additive).
- **Model**: `<app_dir>/app/Models/<Model>.php` — fillable, casts, relacionamentos, scopes simples (mais o que a extensão exigir de todo model, ex.: trait de auditoria).
- **Factory**: `<app_dir>/database/factories/<Model>Factory.php` — para qualquer model sob teste.
- **Constraints**: nenhuma `dropColumn`/`dropForeign`/`change` em tabela existente sem aprovação explícita.

### Fase 2 — Services + Enums + Jobs
- **Service**: `<app_dir>/app/Services/<Module>/<Service>.php` — stateless, recebe dependências por construtor.
- **Enum**: `<app_dir>/app/Enums/<Module>/<Enum>.php` — quando há estado tipável.
- **Job** (se async): `<app_dir>/app/Jobs/<Job>.php` — delega para o service; fila conforme o precedente citado (gate de precedente).

### Fase 3 — Controllers + Requests + Routes
- **Controller**: `<app_dir>/app/Http/Controllers/<Module>/<Controller>.php` — thin, retorna `Inertia::render(...)` ou `response()->json(...)`.
- **FormRequest**: `<app_dir>/app/Http/Requests/<Module>/<Request>.php` — validação fora do controller.
- **Routes**: `<app_dir>/routes/web.php` ou `<app_dir>/routes/api.php` — middleware (`auth`, permission).
- **Rotas no frontend**: conforme `profile.frontend_routes` — nenhum passo de geração que o profile não nomeie.

### Fase 4 — Frontend
- **Design gate**: carregar `profile.design_skill` (pule quando `none`) e listar aqui os critérios 🔴/🟠 que **esta** tela precisa satisfazer — específicos, não genéricos (ex: "empty state do filtro sem resultados", "coluna de % alinhada à direita com formatação PT-BR", "ação primária única = Salvar"). Os componentes reutilizáveis identificados no inventário entram nos itens abaixo em vez de virarem componente novo.
- **Page**: o arquivo da página sob `<app_dir>/<profile.frontend_root>` + **Componentes** do módulo. Convenções (UI library, estilo, charts, permissões, referência visual) são da skill `cdv-frontend` — carregada quando a fase começa; liste aqui só as decisões da feature (quais páginas/componentes, qual referência visual quando houver, qual módulo). Os caminhos exatos de cada peça seguem `profile.frontend_rules` e a extensão.
- **Composables**: apenas se houver lógica reusável.
- **Types**: interfaces TS espelhando os payloads.
- **Lang**: strings no idioma de `profile.language_ui`.
- **Routes/menu**: entry com o permission gate que a regra de frontend do repositório exige.

### Fase 5 — Tests
- **Backend Feature**: `<app_dir>/tests/Feature/<Module>/<Controller>Test.php` — happy path + 2-3 sad paths.
- **Backend Unit**: `<app_dir>/tests/Unit/Services/<Service>Test.php` — quando o service tem lógica não trivial.
- **Frontend**: `<Component>.spec.ts` no lugar que a convenção de specs do repositório manda (`profile.frontend_rules`; a extensão traz a regra de co-location, se houver) — `profile.cmd_test_frontend`, render + interaction.
- **Mapa AC → teste** (obrigatório): uma linha por AC — `AC1 → <TestFile > descrição do test()>`. AC sem teste é declarado como gap explícito no plano, nunca omitido.

### Fase 6 — QA Plan (executável)

Um artefato efêmero é gerado na raiz do repo pelo skill no Step 4c (gitignored; consumido pelo `cdv-interactive-qa` e deletado no wrap-up do finalize):

1. **`QA-<slug>.md`** — Guia de verificação manual com passos numerados, comandos do ambiente (com o prefixo de container de `profile.cmd_container_exec` quando `profile.commands_run_on` é `container`), smoke tests via tinker, verificações de idempotência e saída esperada para cada comando. Cada passo traz rótulo **[READ-ONLY]** ou **[MUTABLE: o que escreve]** e cita o AC que valida. Estrutura segue `references/qa-guide-template.md`.

O segundo e último arquivo do skill é o **`STATE-<slug>.md`** (Step 6, escrito na aprovação): plano verbatim, status por fase, `## Finalize seed` (links externos, seeds de PR, plano de commits — o que o `cdv-finalize` lê) e, ao final, `## Verificação` com a tabela do verificador.

Resumo inline da abordagem (os comandos vivem no artefato, não aqui):
- Gates mecânicos (migrate, formatador, análise estática, testes — os `profile.cmd_*`): rodados pelo verificador (Step 6.5) e pelo finalize — sem script separado.
- Smoke tests manuais: ver `QA-<slug>.md` seções 3+.
- Idempotência e regressões: cobertas em `QA-<slug>.md` (quando aplicável).

### Acceptance Criteria
- **AC1** — <critério testável 1>
- **AC2** — <critério testável 2>

### Riscos e mitigações
- <risco 1> → <mitigação>.
- <risco 2> → <mitigação>.

### Próximo passo
Após aprovação inline, este skill executa as fases em ordem (Step 6): no tier pequeno tudo inline no checkout principal; no tier grande em worktree, com executores paralelos (sonnet) só quando as fases tocam código disjunto. Gates de teste/formatador/análise estática no fechamento de cada fase; verificador independente (Step 6.5, `model="opus"`, anunciado, disparado no mesmo turno em que a última fase fecha) nos dois tiers — perfil `light` ou `standard` conforme o Resumo. Ao final, invocar `cdv-finalize` para gerar o `<slug>-pr.md` efêmero e a árvore de commits atômicos.
```

## Notas de uso

- Renderize inline no chat, em PT-BR, com path:line refs onde fizer sentido.
- **ACs numerados são o fio de rastreabilidade do pipeline.** Todo critério nasce com ID (`AC1..ACn`) e é citado por ID em: fase 5 (mapa AC → teste), passos do QA guide (`[ACn]`), `## Verificação` do `STATE-<slug>.md`, e a avaliação de requirements do `cdv-pr-review`. Um AC sem fase que o implemente é erro de plano — resolva antes de apresentar. Quando a entrada vem de um `decisions.md` do `cdv-grilling`, cite a decisão de origem (`D3`) ao lado do AC em vez de reescrevê-la.
- Não pad as fases — funda quando uma fase tem 1 arquivo isolado, divide quando uma fase tem mais de 5-6 arquivos.
- Quando a Fase 3 tocar routes, siga `profile.frontend_routes` — não invente um comando de geração de rotas que o profile não nomeia.
- Inclua o nome da branch alvo no Resumo (deve bater com `git branch --show-current` após Step 0).
- Marque explicitamente quando uma decisão veio do ledger do `cdv-grilling` ("Vindo do cdv-grilling, D4: persistência em URL query string").
