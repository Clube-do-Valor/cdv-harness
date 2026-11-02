# README template of a research round

The format below. Copy the block below into the round's `README.md`, fill the placeholders, and add one table row per file as it lands. Prose in `profile.language_ui` (pt-BR in the template below); file names as written on disk.

```markdown
# <Título da rodada>

Pesquisa iniciada em <AAAA-MM-DD> sobre <o que se quer saber, em uma ou duas frases: o problema,
a pergunta e para quem>. <Por que agora.> <O que fica fora.>

Tarefa: <task key> · Pasta: `<caminho absoluto da pasta>`

## Conteúdo

| Arquivo | Conteúdo |
|---|---|
| `research/01-<tema>.md` | <uma linha: o que o arquivo responde> |
| `research/NN-sintese.md` | Síntese e proposta |
| `decisions.md` | Ledger do grilling de <DD/MM>: <n> decisões, suposições, fora de escopo e perguntas em aberto |
| `scripts/` | Scripts de extração e saídas agregadas |
```

Lines that only appear when they apply:

- `Tarefa: nenhuma — <motivo>` when the task tracker was missing or refused.
- `Fica fora do repositório (<motivo>).` right after the context paragraph, for the external-folder exception.
- `Página publicada: <url> — para <leitor>` under the `Tarefa` line, only when a named external reader asked for a page; its source lives in `artifact/` and gets its own table row.
