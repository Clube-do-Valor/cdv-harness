# Copy conventions — product-facing text (`profile.language_ui`)

Rules the user has had to re-teach case by case; they are general. Apply to every label, tooltip, empty state, docs page, API guide and error message.

## Hard rules

1. **HTTP status codes carry their reason phrase.** `429 Too Many Requests`, `404 Not Found`, `422 Unprocessable Entity` — never the bare number in user-facing text.
2. **Example e-mails use the domain the extension names**, never invented corporate domains.
3. **No sentences that reaffirm expected behavior.** "Sem duplicar itens já enviados", "os dados são salvos automaticamente ao salvar" — if it is how any correct system behaves, it is noise; cut it. Copy earns its place by telling the user something they could get wrong.
4. **Audience-gate technical artifacts.** Pages read by non-technical users don't expose OpenAPI specs, payload dumps or class names as primary content; prefer an action (a copy button, a download link) over inline technical material. Jargon only where the audience is developers.
5. **Vocabulary from the product, not coined.** Use the terms that already exist in screens, menus and area cards (the extension lists the product's terms); a term the product does not use yet must be explicitly proposed, never silently introduced (a coined term can collide with a name the product already uses for something else).
6. **Numbers presented to users state their basis** when they are projections or partial ("estimativa com base em X", "últimos 30 dias") — a bare number reads as a measured fact.

## Tone

- Direct, verb-first for actions ("Reenviar convite", not "Clique aqui para reenviar").
- Empty states say what would fill them ("Nenhum convite enviado ainda — crie o primeiro em …"), not just "Nenhum registro".
- Error messages say what to do next, without stack/jargon.
