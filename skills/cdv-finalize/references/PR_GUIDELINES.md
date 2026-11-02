# PR Guidelines

Este documento define o formato padrão para descrições de Pull Request neste repositório (o idioma do texto é `profile.language_ui`; os títulos de seção abaixo são o contrato que o `scripts/lint-pr-description.sh` verifica). A descrição existe para o reviewer — não é um arquivo histórico. O diff mostra *o quê* mudou arquivo a arquivo; a descrição diz *por quê*, *o que exige julgamento humano* e *como provar que funciona*. Tudo que duplica o diff é ruído.

Alvo: **40–80 linhas**. Teto rígido: 100. Se passar, corte — não existe anexo para onde mover.

---

## Formato padrão

```markdown
## ⚡ TL;DR

<3-4 frases curtas para gestores e stakeholders, ≤80 palavras, português claro. Sem nomes de colunas, métodos/hooks/eventos, paths de arquivo, nós de ferramenta de workflow, jargão de pipeline ou links de tickets. Ver "Regra do TL;DR" abaixo.>

## 🔍 O que muda e por quê

<UM parágrafo curto: o pedido/problema, o estado anterior e o escopo fechado.>

<3-6 bullets de mudanças COMPORTAMENTAIS — o que o sistema faz de diferente
depois deste PR. Nunca por-arquivo (o diff mostra os arquivos):>
- <O sistema agora faz X quando Y.>
- <O fluxo Z passa a exigir W.>

## 🎯 Decisões para o reviewer validar

<2-4 bullets. As escolhas de julgamento que o diff NÃO explica sozinho:
trade-offs aceitos, matching/regras de negócio não-óbvias, efeitos colaterais
deliberados, dívidas assumidas. É a seção que dirige a leitura do diff.>
- <Decisão + por quê + o que pode dar errado se estiver errada.>

## 🧪 Como testar

Executado nesta entrega:
```bash
<comando de teste exato — copia-cola>
```
Resultado: **<N> passed (<M> assertions)**. <formatador/análise estática/testes de frontend em meia linha se aplicável.>

Roteiro de QA (≤5 passos, cada um com *Esperado* mensurável):
- **Passo 1**: <ação ou comando>
  *Esperado*: <resultado mensurável>.

<Marque [PRODUCTION-AFFECTING] os passos que escrevem em um sistema de
`profile.production_writing_integrations` (ou disparam jobs que escrevem); o
revisor os executa manualmente. Leitura de dados reais não é production-affecting.>

## ⚠️ Riscos e impactos

<Bullets APENAS de riscos reais: migrations (com nota de reversão), mudança de
contrato para consumidores externos (os que a extensão lista), efeito retroativo em dados,
janela de deploy. Quando não houver: "Nenhum risco identificado além do escopo
descrito." em uma linha. Cross-refs de tickets irmãos entram aqui, nunca acima.>

## 🚀 Pós-deploy (opcional)

<APENAS quando o diff toca migrations, config, comandos de console, schedules
ou filas: os comandos exatos a rodar em produção após o deploy, em ordem, com
parâmetros reais já preenchidos (nunca `<opções>`) — migrations, config:clear/
restart de worker quando aplicável, comando de backfill com flags. Quando nada
manual é necessário, omita a seção inteira.>

## 🛠️ Extras (opcional)

<APENAS quando a branch carrega commits de manutenção/infra/skills fora do
escopo da feature. Um bullet por commit: mensagem exata + meia linha de
justificativa de piggyback. Trabalho de feature real NUNCA mora aqui. Quando
ausente, omita a seção inteira.>

## 🏷️ Ticket

[<CHAVE> — <nome do ticket>](<url do ticket>)
```

---

## Regras

1. **Conteúdo em português** — seções em PT-BR, mesmo que headers em inglês. Sem emojis no corpo (apenas nos títulos de seção).
2. **TL;DR obrigatório e primeiro** — ver "Regra do TL;DR" abaixo.
3. **Nada de inventário de arquivos** — sem árvore de arquitetura, sem bullets por-arquivo, sem lista de dependências/env "sem novidades". Se uma env var ou dependência nova existe, ela aparece em "Como testar" (setup) ou "Riscos e impactos" (operação) — onde tem consequência.
4. **"Decisões para o reviewer validar" é a seção de maior sinal** — se ficar vazia, o PR provavelmente não precisou de julgamento (raro) ou a seção foi negligenciada (comum). Escreva-a antes das outras.
5. **Comandos exatos** — tudo em "Como testar" deve ser reproduzível com copy-paste; contagem de testes e assertions sempre presente.
6. **Disciplina de escopo** — "O que muda e por quê" cobre EXCLUSIVAMENTE o diff DESTA PR. Tickets irmãos e preocupações relacionadas vão para "Riscos e impactos" (quando afetam consumidores) ou não entram. Commits fora de escopo vão para "Extras".
7. **Riscos explícitos** — a seção existe mesmo quando a resposta é "nenhum".
8. **Pelo menos um link externo público no corpo** — ticket, registro do CRM, execução de workflow, issue do monitor de erros — inline em "O que muda e por quê" ou "Riscos e impactos", nunca no TL;DR. Sem link para workspaces internos privados; quando o contexto só existe em thread interna, parafraseie sem link.
9. **Pós-deploy executável** — quando o diff toca migration/config/comando/fila, a seção "Pós-deploy" lista os comandos de produção em ordem com parâmetros reais preenchidos. "O que rodar em produção depois do deploy" nunca pode ser uma pergunta que o autor precise responder depois.

10. **Ticket por último** — a seção `## 🏷️ Ticket` (quando `profile.ticket_system` não é `none`) fecha a descrição com o ticket em hyperlink (`[<CHAVE> — nome](url)`, a chave segue `profile.ticket_key_pattern`), nunca o placeholder do template do host.

---

## Regra do TL;DR (copy voltada a gestores)

A seção `## ⚡ TL;DR` é a primeira do PR e a única que não-engenheiros leem. Regras rígidas:

- **Público:** gestores, stakeholders e líderes de área sem contexto de código. Tempo de leitura alvo: ≤15 segundos.
- **Tamanho:** 3-4 frases curtas, ≤80 palavras no total.
- **Forma:** frase 1 descreve o que estava quebrado/faltando em termos operacionais; frase 2 descreve o que muda na prática depois deste PR; frase 3 confirma se há impacto visível em telas, processo ou configuração (em geral `Sem mudanças em telas, processos ou configuração`).
- **Proibido:** nomes de colunas, métodos/hooks/eventos, nós de ferramenta de workflow, paths de arquivo, thresholds técnicos, listas de guardas numeradas, trechos de código/SQL, jargão de pipeline (`batch window`, `dedupe key`) e links de tickets.
- **Permitido:** nomes de operação de negócio (`sincronização`, `importação`, `notificação`), resultados visíveis ao usuário e o mecanismo em alto nível em português claro.
- **Autoteste:** leia o TL;DR em voz alta como se explicasse para um Diretor de Operações que nunca abriu o código. Se disser qualquer termo proibido, reescreva.

Exemplo canônico (um relatório que saía em branco; o extension do repositório pode trazer exemplos reais):

> O relatório mensal saía em branco quando o período terminava num fim de semana, porque a consulta parava no último dia útil. A partir deste PR, o relatório usa o último dia do período, e os meses que fecham num sábado ou domingo voltam a mostrar os números completos sem correção manual.

---

## Ciclo de vida da descrição

A descrição é gerada pela skill `cdv-finalize` como arquivo efêmero na raiz do repositório (`<slug>-pr.md`), enviada ao host pela API (`cdv-open-pr`, que acrescenta a seção `## 🏷️ Ticket` quando ela ainda falta) e apagada assim que o PR a carrega — `<profile.pr_cli> pr view <N>` a lê de volta. Ela nunca é commitada. Título do PR: Conventional Commits em inglês, com ` (<CHAVE>)` no fim quando há ticket.
