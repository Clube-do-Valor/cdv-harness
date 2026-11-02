# Report Template

Exact shape of the final report produced at the end of Step 7. Load this only when ready to compose the report. The section names are PT-BR; render them in `profile.language_ui`.

## Sections (in order)

1. **Diagnóstico** (1 line) — `Causa raiz: <one sentence>.` Pin the failure mechanism, not the symptom.
2. **Hipóteses consideradas** — one line per candidate cause from the Step 3 block: `confirmada / descartada / inconclusiva — <evidência que decidiu>`. A report with a single hypothesis and no discarded rivals is a smell.
3. **Evidência** — bullets or a small table with verified facts. One row per record/entity. Always include the field that proves the hypothesis (e.g., `external system: 404`, `status=COMPLETED`, `duplicate external_id`). **PII masked** (`<masked>`, see the PII rule in SKILL.md) — ids + first names + e-mail (e-mail is a work identifier, shown in clear — house rule).
4. **Refs de código** — every code citation as a markdown link in `path:line` format, e.g. `[OrderService.php:972](app/Services/OrderService.php#L972)`. Never bare paths.
5. **PRs / commits relacionados** — git hashes (short) and PR numbers, with merge date when relevant for the timeline. For regressions: the commit/PR that introduced the bug (`git log -S`/blame) and since when.
6. **Quem é afetado** — roles/permissions/users atingidos, contagem quando derivável, e a tradução da causa técnica para o sintoma visível na tela.
7. **Próximos passos** — split into:
   - **Mitigação imediata** — single concrete action the reporter can take now.
   - **Follow-ups técnicos** (optional bullets) — code hardening, audit commands to run, related tickets to open.

## Formatting rules

- Tables use 3 columns max for the "Antes/Depois" shape, otherwise 4-5 columns for evidence (`record_id | created_at | external_id | external state`).
- Keep the whole report under one screen when possible. If the broadening (Step 6) yields many records, summarize counts and list only the first 5 with "+N similar".
- Never include the full Laravel stack trace in the report. Cite the throw site and the two upstream callers; the user already has the log.

## Example skeleton

> **Diagnóstico** — Causa raiz: <uma frase com o mecanismo, ex.: registro local referencia um objeto externo deletado; a chamada de atualização propaga o 404 como exceção genérica>.
> **Hipóteses consideradas** — <candidata> — confirmada/descartada/inconclusiva — <evidência que decidiu>.
> **Evidência** — tabela pequena, uma linha por registro, sempre com o campo que prova a hipótese.
> **Refs de código** — [OrderService.php:972](app/Services/OrderService.php#L972) — <meia linha>.
> **PRs / commits relacionados** — PR #NNN (merge YYYY-MM-DD) — <relação com o caso>.
> **Próximos passos** — Mitigação imediata: <ação única concreta>. Follow-ups técnicos: <bullets opcionais>.

## Checklist before delivering

- [ ] Causa raiz é uma frase concreta, não um sintoma.
- [ ] Toda linha da evidência foi confirmada por leitura/tinker/API/git — nenhum fato citado de cabeça.
- [ ] Refs em `path:line` clicáveis.
- [ ] Próximos passos tem pelo menos um item de "mitigação imediata".
