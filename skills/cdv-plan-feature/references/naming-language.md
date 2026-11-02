# Naming Language — One Language In Code

Behavioral rule, not a style preference. Read before naming any file, symbol, column or route.

**One concept, one name, one language.** Mixed-language identifiers are always prohibited — there is no threshold, no "established term" exception, no per-module dialect.

---

## The rule

`profile.language_code` is the default for everything an engineer types. `profile.language_ui` is allowed in exactly the four places listed under "UI language allowed". Anything not on that list is in `profile.language_code`, including terms the business says in the UI language every day.

The reason is not purity: a codebase where a term in the UI language and its translation both name the same concept has no ubiquitous language, so `grep` misses half the call sites and every new contributor has to learn which half of the domain is translated.

The examples below use German as a stand-in for `profile.language_ui` and English as `profile.language_code`; the extension carries the repository's own.

---

## Always in `profile.language_code` (no exceptions)

| Layer | Applies to |
|---|---|
| Backend | classes, interfaces, traits, enums, **enum case names**, methods, properties, parameters, local variables |
| Database | tables, columns, indexes, foreign keys, migration filenames |
| Frontend | component filenames, props, emits, composables, types, functions, variables |
| Tests | test method names, fixture and factory variable names |
| Runtime config | env vars, config keys, queue names, job class names, cache keys, feature flags |
| Repo artifacts | commits, branches, ADRs, area cards, code comments |

---

## UI language allowed (exhaustive — nothing else qualifies)

1. **User-facing copy.** Translation files, labels, placeholders, empty states, validation messages, notification bodies. The *keys* stay in `profile.language_code`; the *text* is in `profile.language_ui`.
2. **URL path segments already published.** A published path stays — bookmarks and shared links would break. New routes get paths in `profile.language_code` with a menu label in the UI language.
3. **Verbatim identifiers from an external contract**, as string literals only: a CRM's property names, a warehouse's columns, a workflow's payload fields. Never translate them, never let one become the name of one of our own symbols.
4. **Data values already persisted in the UI language.** The stored string stays; the symbol that names it is in `profile.language_code`.

---

## Examples

### Enum case names

```php
// ❌ WRONG — ten English cases, then one in the UI language
case Draft = 'draft';
case Rechnung = 'rechnung';

// ✅ RIGHT — case name in the code language, backing value untouched because rows already hold it
case Draft = 'draft';
case Invoice = 'rechnung';
```

Why: the value is data (rule 4), the case name is code. Renaming the value would need a migration and would break whatever external flow writes it.

### Local variables

```php
// ❌ WRONG
$rechnung = $this->invoiceService->getTotals($customer);

// ✅ RIGHT
$invoice = $this->invoiceService->getTotals($customer);
```

Why: the class and the service already speak the code language. `$rechnung` is a third name for the same thing, inside a method that already speaks it.

### One concept, two names

```
❌ WRONG — app/Services/Invoicing/
   InvoiceConcludeService.php
   CrmInvoiceIngestionService.php
   RechnungCrmTaskSync.php              ← same concept, other language

✅ RIGHT
   InvoiceCrmTaskSync.php
```

Why: `invoice` is already the code-language name of this domain concept in three sibling files. Keep the UI-language word only where it is the literal external value or copy on screen.

### External contract fields

```php
// ✅ RIGHT — the external key is verbatim, our symbol is in the code language
$monthlyAmount = $properties['monatsbetrag'] ?? null;

// ❌ WRONG — the external name leaked into our code
$monatsbetrag = $properties['monatsbetrag'] ?? null;
```

Why: `monatsbetrag` is the external system's name, not ours. Quoting it is required; adopting it is not.

### Half-translated identifiers (the worst case)

```
❌ monthly_betrag        ❌ betragValue         ❌ getRechnungTotal()
✅ monthly_amount        ✅ amountValue         ✅ getInvoiceTotal()
```

Why: a reader cannot guess which half of any given name was translated, so they cannot guess what to grep for.

### Routes

```php
// ✅ RIGHT — existing published path stays, new sibling is in the code language
Route::get('rechnungen/zusammenfassung', ...)        // already public, do not rename
Route::get('invoices/summary', ...)                  // new route
```

---

## Red flags

- ❌ An identifier that mixes languages in one name.
- ❌ Two names for one concept in the same folder or feature.
- ❌ An external field name used as the name of one of our variables, properties or columns.
- ❌ "The business calls it this way" as the reason for a symbol in the UI language — that is what UI copy is for.
- ❌ A name in the UI language introduced because a neighbouring legacy file already has one.

---

## Renaming existing names in the UI language

Rename when you are already editing that file for another reason, in a dedicated `refac:` commit separate from the behavior change. Never as a drive-by sweep across untouched files, and never for a persisted value or a published URL — those are rules 2 and 4.

---

## Checklist

- [ ] Every new symbol, column and file name is in `profile.language_code`.
- [ ] No identifier mixes the two languages.
- [ ] Every string in the UI language in the diff falls under one of the four allowed cases.
- [ ] External field names appear only inside string literals.
- [ ] The concept is not already named in the code language elsewhere in the codebase.
