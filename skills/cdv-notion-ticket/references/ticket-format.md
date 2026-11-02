# Formato da nota de entrega (fonte de verdade)

A nota é o corpo do card do Notion (o banco `profile.ticket_database`), lido em menos de um minuto por gestores e pela área que pediu. É o layout das notas de entrega (o extension pode listar os cards-modelo): TL;DR num callout, a tabela Antes/Agora, como usar e próximos passos.

## Ordem fixa

1. Callout azul `⚡` com `**TL;DR:**`
2. `---`
3. `## O que mudou` — tabela Antes/Agora
4. `## Como usar` — só quando alguém precisa fazer algo diferente
5. `## Próximos passos` — checklist
6. Linha de tags em `code`

Ícone do card: o que a extensão define. O card já tem título, status, responsável e o link do PR nas propriedades; o corpo não repete nada disso.

## Regras por bloco

### TL;DR
Até três frases, ≤70 palavras, português claro, com os termos-chave em negrito. Frase 1: o problema ou o pedido em termos operacionais. Frase 2: o que passa a acontecer. Frase 3: o impacto visível, ou "sem mudança visível para o usuário" numa entrega de fundação. Sem nomes de tabela/coluna/método, paths ou trechos de código.

### O que mudou
Tabela de 3 colunas (vazia, `Antes`, `Agora`), uma linha por comportamento que a área sente, rótulo da linha em negrito. 3 a 6 linhas.

### Como usar
Bullets curtos com o que a pessoa faz para usar: o pedido, a tela, o passo único de configuração. Omita quando nada muda para quem usa.

### Próximos passos
Checklist (`- [x]` / `- [ ]`). O primeiro item é o PR com o link (`[x]` quando aberto); depois revisão/merge e o que fica com outras pessoas.

### Tags
Uma linha final com 3 a 5 termos em `code`, minúsculos, separados por espaço: o sistema e o tema (`<sistema>` `<tema>` `<tema>`; o extension pode trazer exemplos).

## Regras de voz

- pt-BR, público gestor/stakeholder.
- Lê como especificação da entrega: sem "agora corrigido", "executado durante o rollout", "encontrado no QA".
- Sem status no corpo ("em revisão", "em produção") — a propriedade Status diz isso; o checklist de próximos passos é ação, não status.
- Honestidade sobre o tipo de entrega: não invente impacto de tela numa entrega de fundação.

## Esqueleto (Notion-flavored Markdown)

```markdown
<callout icon="⚡" color="blue_bg">
<b>TL;DR:</b> <Problema em termos operacionais.> <O que passa a acontecer, com o termo-chave em <b>negrito</b>.> <Impacto visível.>
</callout>

---

## O que mudou

<table fit-page-width="true" header-row="true">
<tr><td></td><td>Antes</td><td>Agora</td></tr>
<tr><td><b>Comportamento 1</b></td><td>…</td><td>…</td></tr>
</table>

## Como usar

- <o que a pessoa faz>

## Próximos passos

- [x] Abrir o PR [#<N>](<url do PR>)
- [ ] Revisar e mergear o PR

<p />

`<sistema>` `<tema>` `<tema>`
```
