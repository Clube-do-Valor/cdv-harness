# Explain Findings — the three-layer format

Shared by `cdv-code-review`, `cdv-apply-review`, `cdv-debug` and the verifier of `cdv-plan-feature`. One format for every place a finding is shown to the user: first the plain explanation, then how to see it on the screen, then the technical detail for an agent. The technical detail never disappears; it moves below the explanation.

Why this exists: readers without the code ask for a high-level version; a finding that carries all three layers answers that up front.

**Golden examples — read at least two before writing a finding.** They describe the repository's own screens and domain, so they live in its extension: `<profile.extension_dir>/cdv-code-review/examples/` (the `golden-B*.md` files — real, praised findings with all three layers, each showing a different kind of finding: a frontend input bug with a contrast step, a symptom on a *different* element than the one edited, backend logic with a measured number and a screen consequence, a performance finding observed on screen with no code in the repro). Their URLs and ids are those of the QA data they were written against. When the repository has no extension, follow the template in [comment-format.md](comment-format.md) and this reference alone.

## The three layers

### 1. Narrative

What is wrong, why it matters, since when. Written for someone who knows the product but did not read the code.

- Short sentences, one idea each. Active voice. PT-BR.
- The first time a technical term appears, explain it in half a line ("o hook do model, o trecho que roda antes de gravar").
- No metaphor unless defined right there. Banned as-is: "foto", "balde", "horizonte", "régua", "espelho" (say "cópia local da tabela"), "trilha".
- Name the concrete gesture that triggers the problem ("o usuário corrige a categoria pelo seletor da linha"), not the abstract condition.
- Close with **Fix sugerido:** one recommendation, with its in-repo precedent when one exists (a component, a sibling screen, an ADR). Never a menu.

### 2. 🔬 Como reproduzir

Screen only. The reader opens a URL and looks.

- A real case from the current local QA environment (`profile.qa_env`): URL on `profile.qa_url` with the real ids, the row or card to look at, the literal labels from the `.vue`.
- Numbers to write down **before** acting, then the action, then what changes and what should have changed.
- A restore step, also by screen gesture (re-select the previous value, retype the previous amount).
- **Quando acontece em geral:** one sentence on the condition, so the reader knows it is not that one row.
- When useful, a contrast step that isolates the cause ("repita com `20` e veja gravar certo").
- **No REPL, no console command, no SQL in this section.** If the only way to see the problem is a query, the finding has no visual symptom — say so plainly: "Não tem sintoma de tela. Aparece quando …, e o efeito seria …". Never invent a symptom.
- Host and ids are the local environment's; say so in one line so a reader on another dump adjusts.

### 3. 🤖 Prompt for AI Agents

Unchanged from `comment-format.md`: English, `file:line`, exact change, the test to add. This is where precision lives; the narrative does not repeat it.

## Presentation in chat

One block per finding, most severe first, nitpicks grouped in one bullet list at the end, then a summary table `ID | severidade | arquivo:linha | uma linha`. Close with one sentence naming the gates run and their result, and any gate not run and why.

Do not paste the comment files into the chat. The chat gets layers 1 and 2 in condensed form (three short paragraphs: **O problema**, **Como ver na tela**, **Recomendação**); the files carry all three in full.

Never pad: a branch with two real findings gets two blocks. Two honest findings beat ten inflated ones.

## Per skill

| Skill | Where the format applies | What stays as it was |
|---|---|---|
| `cdv-code-review` | Every per-finding file (three layers, per `comment-format.md`) and the Step 10 chat presentation | `_summary.md`, `INDEX.md`, anchors, severity mapping |
| `cdv-apply-review` | The Step 3 triage: each finding is presented as **O problema / Como ver na tela / Recomendação** before the verdict and the "aplico?" question | One commit per finding, the verdict table |
| `cdv-debug` | A **Resumo para quem abriu o chamado** block at the top of the Step 7 report: problema, como ver na tela, desde quando, o que fazer agora, correção recomendada — ten lines, no jargon | The technical report below it; the Notion Análise técnica block |
| `cdv-plan-feature` verifier (Step 6.5) | Opens with one line naming itself ("Verificação independente do Step 6.5: leio os ACs do STATE e não escrevi o código"), then each uncovered or partial AC in prose (what is missing, what would break if it stays missing, the test that would cover it) | The five-column AC table below the prose |

## Worked example (condensed chat form)

The condensed chat form of one finding is in the extension (`<profile.extension_dir>/cdv-code-review/examples/worked-example-chat-form.md`): the same finding as it had been written before this reference existed and as it reads in the three-paragraph form — same facts, no invented symptom. The shape is always **O problema**, **Como ver na tela**, **Recomendação**.

## Anti-patterns

- Metaphor in place of the mechanism ("o dado ficou mais velho que a foto").
- A REPL query (`profile.cmd_tinker`) inside "Como reproduzir".
- "Como ver" that describes a query result instead of a screen.
- Repeating the comment files verbatim in the chat.
- A recommendation with two options.
- A verifier report that is only the table.
