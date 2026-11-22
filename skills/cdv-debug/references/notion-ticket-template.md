# Notion Ticket — "Análise técnica" Template

Used in Step 8 when the user wants the analysis on a Notion card. The block is rendered paste-ready; when the `cdv-notion` client has a token and the user confirms the draft, it is appended to the card with that client (`.claude/skills/cdv-notion/scripts/notion`, written `notion` below), otherwise the user appends it manually. The syntax is the Notion-flavored Markdown of `.claude/skills/cdv-notion/references/notion-markdown.md` (in the core, `skills/cdv-notion/references/notion-markdown.md`).

## Operating rules

- **The block appends, never replaces.** Write it to be pasted **below** the original ticket description, leaving the existing text intact.
- **Always open with `## Análise técnica` as an H2** separating the existing text from the new block — mirrors the H2 style of the ticket's existing description (the extension names the headings of the repository's ticket template).
- **TL;DR exists for managers and stakeholders**, not for engineers. If a director who never read the code can summarize the ticket after reading only the TL;DR, it is correct. Detailed technical content lives in Diagnóstico/Solução aplicada — see the dedicated TL;DR rules section below.
- **Never restate the card's title, status or properties** inside the block.
- **Cross-references in "Outras referências":** for a PR, build the hyperlink directly from the host's PR URL and `profile.vcs_repo` (`<host>/<profile.vcs_repo>/pull-requests/<N>` on Bitbucket, `<host>/<profile.vcs_repo>/pull/<N>` on GitHub). For a ticket key (`profile.ticket_key_pattern`), link it when the user supplies (or the conversation contains) the card URL; otherwise leave the plain key — never invent a URL.

## TL;DR rules (hard rule — manager-facing copy)

The `**TL;DR**` block sits between the metadata line (`Tipo \| Prioridade \| Ambiente`) and the `**Problema**` section. It is the only chunk of the Análise técnica that non-engineers read. Strict rules:

**Audience:** managers, stakeholders, area leads without code context. Target reading time: ≤15 seconds.

**Length:** 3-4 short sentences, ≤80 words total. If you need more, you are writing Diagnóstico, not TL;DR.

**Shape:** sentence 1 describes what was broken in operational terms; sentence 2 describes what changes in practice after the fix; sentence 3 confirms whether there is any visible impact on user screens, processes, or configuration (usually `Sem mudanças em telas/processo/configuração`).

**Forbidden in TL;DR** (move to Diagnóstico / Solução aplicada):

- Column names (`status`, `external_id`, etc.).
- Method/hook names (`static::updated`, `forceFill`, `wasChanged`).
- Workflow-automation node names.
- File paths (`app/Models/Order.php`).
- Time thresholds with technical context (`90 min`, `30s backoff`).
- Lists of numbered guards/steps.
- Code snippets, SQL queries.
- Unexplained acronyms or pipeline jargon (the extension lists the terms already caught in past tickets).
- Cross-ticket links (those go in **Outras referências**).

**Allowed in TL;DR:** business names of operations (the product's own words for them), user-visible outcomes (what the user can no longer see or do), and the high-level mechanism in plain Portuguese.

**Self-check before submitting:** read your TL;DR aloud as if explaining to a Director of Operations who has never opened the code. If you say any forbidden term, rewrite.

## Block shape

The convention adopted in this project (the extension lists past analyses to mirror) is:

```
## Análise técnica
**\[<Module>\] <Concise title in problem-action style>**

---

**Tipo:** Bug | Melhoria \| **Prioridade:** Baixa/Média/Alta \| **Ambiente:** <where it happens>

---

**TL;DR**

<3-4 short sentences for managers. Plain Portuguese. No SQL columns, hook names, file paths, workflow node names, pipeline jargon. See "TL;DR rules" above.>

---

**Problema**

<2-4 sentences. Concrete user-visible failure. Cite the symptom from the original ticket text when possible.>

**Caso reportado** — DD/MM/YYYY, cliente `user@example.com`, identificador interno (record id, external id, etc.).

---

**Diagnóstico**

<Walk through the failure mechanism, citing path:line and stack frames. Numbered list when there are sequential steps in the failure.>

Casos análogos detectados na auditoria (quando aplicável):
- `user@example.com` — id local <id>, <detalhe>.
- ...

---

**Causa raiz**

<1-2 paragraphs. Pin the why, not the what.>

---

**Solução aplicada**

<What was actually done. If only mitigation (record cleanup) and no code change, say so explicitly. Reference the read-only audit command when used.>

---

**Resultado**

<table header-row="true">
<tr><td>Item</td><td>Antes</td><td>Depois</td></tr>
<tr><td>...</td><td>...</td><td>...</td></tr>
</table>

---

**Prevenção**

<Rules that consolidate from this entry + related entries. Cross-reference past tickets with same pattern. Optional bullets for "Pontos técnicos para próximas iterações".>

`tag1` `tag2` `tag3`

---

**Outras referências**

- **[<TICKET-KEY>](<ticket card URL>)** — `<title>`: <one-line explanation of the link>.
- **[PR #N](<PR URL>)** — `<branch-name>`: <one-line explanation>.
- Comando de auditoria: `php artisan <command-name> --options`.
```

## Anchoring the append

`notion fetch <card>` first. The existing description of a ticket usually ends with a last section (`## <last heading>`) followed by the reporter's text, so the block goes at the end:

```
notion update <card> --append-file analise-<slug>.md
```

When the description has something after the reporter's text that must stay last, anchor the block instead: copy the last heading and the reporter's exact last line from the fetched body, and replace them with themselves plus the block:

```
notion update <card> --edit "$(cat anchor.md)" "$(cat anchor.md analise-<slug>.md)"
```

`anchor.md` holds `## <last heading>` and the reporter's exact last line; it must match one place in the body. If the reporter's text repeats earlier in the description (e.g., copied between two sections), keep the last section's `##` header in the anchor to disambiguate. An anchor that matches nothing exits `1` and changes nothing: fetch again and copy the text as it is now.

## Markdown gotchas (Notion-flavored Markdown)

- Escape square brackets in titles: `**\[Module\] ...**`, not `**[Module] ...**`.
- Pipes inside metadata line escape with `\|`: `Tipo: Bug \| Prioridade: ...`.
- Tables use `<table header-row="true">` with `<tr><td>…</td></tr>` rows, never mixed with pipe-table markdown in the same table.
- A collapsible section is `<toggle>` with its title on the next line, a blank line, the content, then `</toggle>` (for a long audit list under Diagnóstico, for instance).
- Horizontal rules are `---` on their own line, with blank lines around.
- Code-style references for emails/ids: backticks (`` `user@example.com` ``).
- Never use multiline YAML operators in any value (Notion's parser drops them).

## Delivery message back to the user

After rendering the block, surface one line like:

> Bloco pronto pra colar abaixo do texto original do ticket — cross-links pra <related tickets/PRs>.

If the user later asks to tweak (remove items, add headings, etc.), re-render the full block — the paste replaces the previous version of the block only, never the ticket text.
