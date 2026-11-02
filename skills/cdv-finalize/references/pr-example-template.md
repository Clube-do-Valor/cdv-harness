<!--
Contrato de concisão (fonte de verdade: PR_GUIDELINES.md nesta pasta).
Alvo: 40-80 linhas, teto 100. A descrição é para o reviewer; o diff mostra os
arquivos — aqui vai o que exige julgamento. Sem árvore de arquitetura, sem
bullets por-arquivo, sem seções "Sem dependências novas".

Este arquivo é EFÊMERO: nasce na raiz do repo como <slug>-pr.md, vai para o
host pela API (cdv-open-pr) e é apagado. Nunca é commitado.

Delete todos os placeholders <...> antes de gravar.
-->

## ⚡ TL;DR

<3-4 frases, ≤80 palavras, para gestores, zero jargão — regras por seção no "Formato padrão" do PR_GUIDELINES.md>

## 🔍 O que muda e por quê

<UM parágrafo: pedido/problema, estado anterior, escopo fechado.>

- <3-6 bullets de mudanças comportamentais. Nunca por-arquivo.>

## 🎯 Decisões para o reviewer validar

- <2-4 bullets de julgamento: trade-off + por quê + o que quebra se errado. Escreva esta seção primeiro.>

## 🧪 Como testar

Executado nesta entrega:
```bash
<comando de teste exato — copia-cola, executável de {app_dir}>
```
Resultado: **<N> passed (<M> assertions)**.

Roteiro de QA:
- **Passo 1**: <ação> — *Esperado*: <resultado mensurável>.

<Máximo 5 passos. Marque [PRODUCTION-AFFECTING] os que escrevem em um sistema de profile.production_writing_integrations.>

## ⚠️ Riscos e impactos

- <Só riscos reais; sem nenhum: "Nenhum risco identificado além do escopo descrito.">

<!-- Inclua a seção abaixo APENAS se o diff toca migration/config/comando/fila. -->

## 🚀 Pós-deploy

1. `<comando exato com parâmetros reais>`

<!-- Inclua a seção abaixo APENAS se a branch carrega commits out-of-band. -->

## 🛠️ Extras (out-of-band)

- `<mensagem exata do commit>` — <meia linha: por que pegou carona nesta branch>.

## 🏷️ Ticket

[<CHAVE> — <nome do ticket>](<url do ticket>)
