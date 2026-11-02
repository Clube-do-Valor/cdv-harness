# Alignment Checklist

The review scans the diff in six passes. Each pass produces zero or more draft findings, which are then mapped to display labels per [severity-category-mapping.md](severity-category-mapping.md).

## 1. Repo hard rules

Sourced from the repository's instructions file (`profile.instructions_file`) and the path rules in [.claude/rules/](../../../rules/). Verified against them every run; do not memorize this list across sessions.

- **Thin controllers.** Controllers handle input, authorization, delegate to a service, and shape the Inertia response. Query builders, multi-step aggregations, and orchestration belong in the services layer. Inlined query/aggregation across multiple lines → `🛠️ Refactor suggestion | 🟠 Medium`.
- **Services concentrate business logic.** Logic that ends up in jobs, models, or controllers when it belongs in a service → flag.
- **Jobs delegate to services.** A job with non-trivial logic in its `handle()` that doesn't call a service → flag.
- **Models stay relationships + casts + simple scopes.** Business logic in a `Model` subclass → flag.
- **Enums over loose strings** for domain states.

The frontend rules are the severity mapping for review; their canonical definition lives in the `cdv-frontend` Hard Rules Registry (which in turn originates in the repository's frontend rule, `profile.frontend_rules`). Keep the two in sync — if a rule changes, update the Registry first. The extension lists the repository's frontend rules with the severity each one carries in a review (placement of new pages, component library, function style, charting library, permission helpers); apply them as written there.

## 2. PII scan

The product handles personal data of end users; the privacy law of the repository's country applies (the extension names it) — an organization-level guardrail. Flag the following:

- **PII in payloads sent to the front-end without need-basis.** Fields: e-mail, national id number, phone number, address, birth date, ID document, geolocation, plus the fields the extension lists. Over-fetch (field present in payload but never rendered) → `⚠️ Potential issue | 🟠 Medium`. Rendered PII without a justified use → same.
- **PII in logs.** `Log::info($record->toArray())` of a record that carries PII, dumping a request that contains PII fields, or `dd($record)` left behind → `⚠️ Potential issue | 🔴 High`.
- **Missing PII-guard test.** A new endpoint that handles end-user data without a test asserting the response excludes the PII fields it shouldn't expose → `⚠️ Potential issue | 🟠 Medium`.
- **Comment prose itself.** The reviewer (this skill) must never echo a real person's PII in its own findings — anonymize examples with placeholders or use the local DB id. An e-mail address used as a work identifier is the exception (house rule).

## 3. Tests-with-PR rule

**Every new behavior/wiring/validation/API surface ships with tests in the same PR. "Tests in follow-up" is a blocker.**

- New controller method without a Feature test → `⚠️ Potential issue | 🔴 High`.
- New service method with non-trivial logic without a Unit/Feature test → `⚠️ Potential issue | 🔴 High`.
- New job without a test asserting dispatch and side effects (`Bus::fake()`, `Queue::fake()`) → `⚠️ Potential issue | 🔴 High`.
- New permission/route without a 403/200 test → `⚠️ Potential issue | 🔴 High`.
- New validation rule without an assertion → `⚠️ Potential issue | 🟠 Medium`.
- A PR description that defers the tests to a follow-up PR → blocker, regardless of severity of the change.

## 4. Production-impact heuristics

**Production-affecting paths are faked in the suite + manual QA only. Smoke tests never touch production.**

- A new test that calls a real external endpoint (any system in `profile.production_writing_integrations`, or any other real third-party service) → `⚠️ Potential issue | 🔴 High`. The replacement is a `profile.backend_test_framework` test with fakes + manual QA covered by a `cdv-plan-feature` QA artifact.
- Production credentials referenced in a test setup → high.
- A migration that backfills against live data without a guard, a dry-run, or a `--force` confirmation → high.
- A new command that mutates production-shaped data without a `--dry-run` option → medium.

## 5. Layer drift heuristics

- **Fat controller.** `index`/`store` actions whose body exceeds roughly 30 lines of query/branching logic, or which inline multiple aggregations → `🛠️ Refactor suggestion | 🟠 Medium`.
- **Model with business logic.** Domain methods on `Model` subclasses beyond scopes, relationships, and accessors → medium.
- **Job with no service delegation.** A job whose `handle()` builds queries, calls API clients directly, or implements multi-step business logic without calling a service → medium.
- **Missing enum.** A new column or domain state stored as a free-string with no PHP enum → medium.
- **Card/code mismatch.** An area card line the diff makes false with no edit to the card, or new code that contradicts an invariant a card states → low (unless the contradiction is dangerous, then medium).

## 6. Naming language

Canonical rule: [naming-language.md](../../cdv-plan-feature/references/naming-language.md), stated in the instructions file under "Language" (code in `profile.language_code`, user-facing copy in `profile.language_ui`). Scan only names the diff **introduces** — pre-existing identifiers in the other language in untouched lines are not findings.

- **Mixed-language identifier.** One name carrying both languages → `🛠️ Refactor suggestion | 🔴 High`. It is unguessable for `grep` and for the next reader.
- **New symbol in the UI language.** A new class, enum case name, method, variable, property, column, index, component, prop or type named in `profile.language_ui` instead of `profile.language_code` → high when it duplicates a concept already named in `profile.language_code` elsewhere, medium otherwise.
- **External field name adopted as our own symbol.** A variable named after an external contract key (`$field = $properties['field']`) → medium. Quoting the external key is required; naming our variable after it is not.
- **New route path in the UI language.** A net-new route segment in `profile.language_ui` → medium (existing published paths are exempt — renaming them breaks links).
- **UI language outside the four allowed cases.** Anything not user-facing copy, an already-published URL path, an external contract field inside a string literal, or an already-persisted data value → medium.
- **Not a finding:** UI-language text in translation files (values, labels, placeholders and validation messages); UI-language text in the PR description and QA steps; a UI-language enum *backing value* whose case name is in `profile.language_code`.

## Stop conditions

- A finding the user explicitly says is intentional and out of scope → drop, do not re-flag.
- A finding that depends on code outside the diff → demote to nitpick if at all, never blocking.
- More than 25 inline findings → trim to the most impactful 25 and mention the overflow in `_summary.md` (matches the inline-comment cap convention of the review tooling).
