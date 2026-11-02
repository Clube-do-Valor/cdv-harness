# Comment Format Reference

Single source of truth for the inline-comment format used by `cdv-code-review`. Every comment file under the review directory (`<profile.pr_review_dir_prefix><TICKET>/`) must match this template exactly. The golden examples that show the template filled with real findings are listed by the repository's extension (`<profile.extension_dir>/cdv-code-review/examples/golden-B*.md`); the writing doctrine for the prose and the `🔬 Como reproduzir` section is [explain-findings.md](explain-findings.md).

## Anchor header (machine-readable, required on every per-finding file)

Every per-finding file MUST start with an HTML-comment line declaring the host's inline anchor:

```
<!-- ANCHOR: path/to/file.ext:LINE -->
```

Then a blank line, then the visible content begins with the category-emoji header. The HTML comment is invisible on the host but lets [scripts/verify-anchors.sh](../scripts/verify-anchors.sh) validate every anchor against `git diff origin/<profile.default_branch>...HEAD` before any file is shipped. `_summary.md`, `INDEX.md`, and `nitpicks.md` carry no anchor header — they are not inline.

## Canonical template

```
<!-- ANCHOR: path/to/file.ext:LINE -->

<category-emoji> **<Category>** | <severity-dot> **<Severity>**

**<Bold title — no file:line; the inline anchor handles it>**

<Prose body in profile.language_ui. Inline `code` and ```php / ```vue fenced snippets allowed.>

- bullets for sub-points when needed

Fix sugerido: <single recommendation woven inline, with refs to the instructions file, the matching .claude/rules/*.md, prior commits, or related PRs>

**🔬 Como reproduzir**

<Screen-only steps on a real case from the QA database (`profile.qa_env`): URL on profile.qa_url with real ids, literal labels, numbers to note before acting, the action, what changes vs what should change, a restore step by screen gesture, and a closing "Quando acontece em geral:" sentence. No REPL/console/SQL here. When the finding has no visual symptom, say so and name the condition under which the risk appears — never invent a symptom. Full rules in explain-findings.md.>

**🤖 Prompt for AI Agents**

​```
Verify each finding against the current code and only fix it if needed.

<English actionable prompt that names the exact file:line and the precise change required.>
​```
```

(The two `​` are zero-width joiners only to escape the nested fence in this reference doc — real files use bare triple backticks.)

## Field rules

- **Category emoji + label** — one of `⚠️ **Potential issue**` (bugs, security, blocking risks), `🛠️ **Refactor suggestion**` (structure or convention divergence), `🧹 **Nitpick**` (trivial polish). Both the emoji and the category label are bold.
- **Severity dot + label** — `🔴 **High**`, `🟠 **Medium**`, `🟡 **Low**`. Both the dot and the severity label are bold. Nitpicks omit the dot.
- **Title** — bold, single line, no `file:line`. The inline anchor handles the location.
- **Prose** — `profile.language_ui`, written for someone who knows the product but did not read the code: short sentences, a technical term explained in half a line the first time it appears, no undefined metaphor (see [explain-findings.md](explain-findings.md)). May include inline backticked code, ```php / ```vue / ```ts fenced snippets, bulleted sub-points, references to other files by `path:line`.
- **`Fix sugerido:`** — single recommendation, not a menu.
- **`🔬 Como reproduzir`** — mandatory on every 🔴/🟠 finding; on 🟡 when it has a visual symptom. Screen-only: URL + real ids from the local QA environment, literal labels, before/after numbers, restore step, "Quando acontece em geral". No REPL/console/SQL. A finding without a visual symptom says so instead of inventing one. Cite the instructions file, the matching `.claude/rules/*.md`, prior commits (by hash), or related PRs (by number) when they ground the recommendation.
- **Prompt for AI Agents** — always English, plain section (bold `**🤖 Prompt for AI Agents**` header, then a fenced code block — no `<details>`/`<summary>` wrapper). Starts with `Verify each finding against the current code and only fix it if needed.` Then names file:line and the precise change required.

## File kinds

`<review dir>` is `<profile.pr_review_dir_prefix><TICKET>/` at the repo root.

| File | Purpose | Where it lives |
|---|---|---|
| `_summary.md` | PR-level summary (risk + walkthrough + counts). Pasted as a *general* PR comment, not inline. | `<review dir>/_summary.md` |
| `B<n>-<slug>.md` | High-severity blocking finding (prevents merge). | `<review dir>/B<n>-<slug>.md` |
| `H<n>-/M<n>-/L<n>-<slug>.md` | High / medium / low severity finding, non-blocking. | `<review dir>/<X><n>-<slug>.md` |
| `nitpicks.md` | All `🧹 Nitpick` items grouped into a single comment (bulleted). Never inline; pasted as a general comment or attached to any safe diff line. | `<review dir>/nitpicks.md` |
| `INDEX.md` | Anchor table + paste guidance. Not pasted into the PR; reference doc for the human. | `<review dir>/INDEX.md` |

## Paste guidance (verbatim in INDEX.md)

The host's steps — where to click, how a general comment differs from an inline one, what to do when a paste renders raw — are in `vcs-<profile.vcs_host>.md` (this folder); copy its "Paste guidance" section into `INDEX.md`. The host-independent rules: one file per paste, never concatenate findings, and `_summary.md` goes as a *general* PR comment, not on a diff line.

## INDEX.md template

```
# Code review — <TICKET> — comentários para o PR

Cada arquivo desta pasta é um comentário inline (ou de PR no caso de _summary.md). Cole o conteúdo inteiro de um arquivo por vez na linha indicada do diff — não junte vários comentários num único paste (cai em code block e mostra o markdown cru).

| Arquivo | Âncora (arquivo:linha) | Categoria | Severidade |
|---|---|---|---|
| `_summary.md` | comentário geral do PR (não-inline) | — | Risco: <ALTO/MÉDIO/BAIXO> |
| ...           | ...                                  | ... | ... |

Dica de paste: <a dica de paste do vcs-<profile.vcs_host>.md>.
```

## _summary.md shape

```
**Resumo do Code Review** (Risco: <ALTO/MÉDIO/BAIXO>)

**Walkthrough**

<Parágrafo único (em profile.language_ui) resumindo o que a branch entrega, o que ficou bem feito, e onde estão os pontos fracos. Cita o cartão de área, o arquivo de instruções ou a rule do caminho quando relevante.>

**<Solicito alterações | Aprovado com ressalvas | Aprovado>** — <justificativa em uma frase>.

Findings: 🔴 High ×N · 🟠 Medium ×N · 🟡 Low ×N · 🧹 Nitpicks ×N
```

## Anti-patterns

- File:line in the bold title — the inline anchor already handles location; duplicate refs distract.
- Multi-section consolidated documents (multiple findings + `---` rules in one paste) — the editor collapses them into a code block.
- Any language other than English inside the Prompt for AI Agents body — prompts are English for downstream agent consumption.
- `Fix sugerido:` as a weighed choice ("opção A ou opção B") — pick one and recommend it; cite the rationale.
- Citing private/internal-only URLs in `Fix sugerido:` — match the cross-references policy of `cdv-finalize` (link the ticket, the record, the execution or issue it came from — not an internal chat thread).
- Echoing client PII in the prose — anonymize with placeholders or local-id refs.
- REPL/console/SQL inside `🔬 Como reproduzir` — that section is what the reader does in the browser; queries belong to the Prompt for AI Agents or to the skill's own verification.
- A "Como reproduzir" that describes a query result or a fabricated symptom — when there is nothing to see on screen, say so.
