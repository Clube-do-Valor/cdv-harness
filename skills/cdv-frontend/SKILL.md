---
name: cdv-frontend
description: >
  Activate when starting any frontend task: creating Vue components, new pages,
  modifying Inertia page props, adding UI-kit components, or implementing
  forms and interactive UI. Use BEFORE writing any Vue component or Inertia
  page — it keeps new UI consistent with the app's existing screens and
  components. Triggers on "cria essa tela", "novo componente", "monta a
  tabela/painel", or any plan-feature frontend phase. Skip for pure backend
  changes (migrations, controllers, services) with no frontend impact.
metadata:
  version: 0.1.0
  owner: leonardoburtet-clube
---

# cdv-frontend

Orchestrating skill for frontend work in the repository. Loads sub-skills in the correct order, enforces the repository's hard rules, and mandates tests for every deliverable.

---

## Before anything — Load the profile and the extension
1. Read `.claude/harness/profile.yaml` and, when present, `.claude/harness/profile.local.yaml` (its keys win). If `profile.yaml` is missing, stop and say so: this skill needs the repository's cdv-harness profile, and it never guesses the values.
2. Read `<profile.extension_dir>/cdv-frontend.md` when it exists. The extension only adds or restricts; where it and this skill differ, the extension wins for this repository.
Below, `profile.<key>` is a value from the profile. A key that is missing or `none` means the repository does not have that thing: skip the step that needs it.

---

## Sub-skill Activation Order

Load these skills sequentially — each one informs the next step:

| Step | Skill                  | Purpose                                                        |
| ---- | ---------------------- | -------------------------------------------------------------- |
| 0    | `profile.design_skill` | Design criteria the screen must satisfy — load before any code |

---

## Hard Rules Registry (canonical)

This is the canonical registry of frontend hard rules. The repository's own rules originate in `profile.instructions_file` and `profile.frontend_rules`; the extension's registry operationalizes them for UI implementation (file placement, UI kit, tokens, tooltip, toast, tabs, charts, permissions, code style). Other skills MUST cite this section rather than maintaining their own copy of the list.

These override any generic recommendation from the sub-skills above. Read `profile.frontend_rules` and the extension's registry before writing code, and place new pages and components in the feature layout under `profile.frontend_root`.

### Visual reference (lightweight)

The extension names the standing reference screens (one for visual identity, one for tables and listings) — do **not** ask which screen to follow when the work fits one of them. A reference is the best current example, not a frozen spec: read the actual component before mirroring it, and treat a local detail there as a starting point rather than a rule.

For anything that fits no standing reference (a new kind of surface, a screen with no precedent), ask once during planning: *"Alguma tela existente serve de referência visual?"*. If the user names one, mirror its layout and reuse what it composes; if not, follow the app's general conventions and move on — no grammar extraction, no mandatory side-by-side ceremony.

Two rules hold regardless of reference:

- **Reuse existing shared components** (selectors, pagination, tooltip, copy-to-clipboard, sibling-feature components…) — never re-invent an equivalent that already exists in the shared components folder or a sibling feature.
- **Mockup offer (opt-in).** For screens with meaningful visual change, offer to render a Claude Artifact mockup of the changed view — in the app's real current style (tokens, shared components' look) — before writing any code. Iterating on a mockup is cheaper than iterating on code. Skip silently for trivial changes (a new column, a badge, a filter).

### Shared chrome (navbar, sidebar, sticky bars)

The global action bar, the sidebars, the section layouts and any sticky command bar are shared chrome (the extension names the files): **one line changed there lands on every screen at once**. Two rules, both from the design skill's section on order in shared chrome (`profile.design_skill`):

- **Read the whole file, never edit by local anchor.** "Insert before the notification bell" produces a local diff and a non-local result. Write out the resulting sequence (`[A] [B] 🔔` → `[A] [B] [C] │ 🔔`) and review *that* before touching the file.
- **Group by the control's nature**, not by spacing. A state indicator (bell with badge, counter, sync status) never sits between action triggers; give the groups a vertical separator when they share a row. Uniform `gap` across mixed natures is what erases the grouping, not what proves it.

Both rows matter: a chrome file may carry a desktop row and an icon-only mobile row, and they have to tell the same story.

### Table minimum-viable rule

New tables ship with the minimum affordances the use case names — nothing speculative:

- **No** select-all checkboxes, bulk actions, per-row three-dots menus, or "view details" modals unless the user explicitly asked for them.
- A row action exists only with a named use case (e.g. "reenviar" for a failed integration row) and is disabled-with-tooltip rather than hidden when unavailable.
- Empty state, loading state, and pagination follow the table reference the extension names, or the screen the user named when they named one.

### Language

Canonical rule: [naming-language.md](../cdv-plan-feature/references/naming-language.md). Frontend specifics:

- Product-facing **text**: `profile.language_ui` — labels, placeholders, empty states, error messages, tooltips, and the values in the translation files. The translation **keys** are in `profile.language_code`.
- Everything an engineer types: `profile.language_code` — component filenames, props, emits, composables, types, functions, variables, test names, Inertia prop names.
- **No mixed-language identifiers.** An identifier that blends the two languages (`betragTotal`, `useBetrag()` in a repository whose code language is English) is prohibited; use the single-language name (`totalAmount`, `useAmount()`).
- **Route paths:** new routes use `profile.language_code` segments with a `profile.language_ui` menu label. Paths already published stay as they are — renaming breaks existing links.
- **External payload keys** arriving in another language from an external system stay verbatim in the type definition (they describe someone else's contract); the local variable that reads them is in `profile.language_code`.
- **Copy conventions**: [references/copy-conventions.md](references/copy-conventions.md) — load when writing any product-facing text (labels, empty states, docs pages, API guides).

---

## Workflow

### 0 — Load design criteria

Invoke `profile.design_skill`. Identify, before writing any code:

- Which 🔴 criteria apply to this screen (states, primary action, tokens, accessibility)
- Which shared components already cover what you need — reuse beats recreate

### 1 — Resolve the visual reference, then plan the architecture

First resolve the **visual reference** (see rule above): ask whether an existing screen should inspire the design, offer the Artifact mockup when the visual change is meaningful, and list the shared components to reuse. Then decide:

- Which Inertia props the page/component receives, and the form and navigation choices
- Single component or split into sub-components (trigger: 3+ UI sections, repeatable template)

### 2 — Implement

Write the component(s) following the hard rules above and the extension's registry. Verify as you go:

- The extension's code-style, UI-kit and token rules
- Shared chrome edited as a whole file, with the resulting sequence written out
- The repository's permission gate where access gates are needed
- Product copy in `profile.language_ui`

### 3 — Write tests (mandatory)

For every new component or composable, create `[ComponentName].spec.ts` in the **same folder as the file it tests** — never in a `__tests__/` subfolder. Run them with `profile.cmd_test_frontend`.

**Test utilities:**

- **Composables:** pure Vitest — sem wrapper de componente, a menos que usem lifecycle hooks ou `inject`
- Mock Inertia router com `vi.mock('@inertiajs/vue3')` quando necessário

### 4 — Finalize

Run `profile.cmd_lint_frontend` and check LSP diagnostics. Fix all errors before marking the task complete.

---

## Checklist (before marking done)

- [ ] The design skill's checklist (`profile.design_skill`) has no 🔴 pending
- [ ] File placed in the feature layout under `profile.frontend_root` or in the shared components, as the extension's registry says
- [ ] Visual-reference question asked (and mockup offered when the change warranted it); shared components reused instead of re-invented
- [ ] Tables carry only the affordances the use case named (no speculative CRUD)
- [ ] Shared-chrome change (navbar/sidebar/sticky bar): resulting sequence written out and grouped by nature, both desktop and mobile rows
- [ ] Every item of the extension's checklist (UI kit, tokens, messages, code style, permissions)
- [ ] Product copy in `profile.language_ui`, per [references/copy-conventions.md](references/copy-conventions.md)
- [ ] `.spec.ts` file exists and tests pass
