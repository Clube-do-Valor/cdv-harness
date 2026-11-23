# Properties in the short format, and the `--where` language

The client reads and writes properties in the short format the Notion MCP used, so the habits and the skill text carry over. The client looks up each property in the data source schema and converts to and from the API's typed values; the model never writes the typed JSON.

## Reading

`notion fetch <page>` prints a JSON object, one key per property:

| Type | Printed as |
|---|---|
| title, text | the plain text |
| number | the number |
| select, status | the option name, or `null` |
| multi-select | `["A", "B"]` |
| date | three keys: `date:<Property>:start`, `date:<Property>:end`, `date:<Property>:is_datetime` (`0` or `1`) |
| person | `["user://<uuid> (Name)"]` |
| relation | `["https://app.notion.com/p/<id>"]`, every related page (more than 25 are read through the paged property endpoint) |
| checkbox | `__YES__` or `__NO__` |
| unique id | `<PREFIX>-<n>` |
| created / edited time, by | the timestamp; `user://<uuid> (Name)` |
| formula, rollup | the computed value (read-only) |
| files | the file names |

A property named `id` or `url` (any case) is printed as `userDefined:<name>`, and may be written either way.

## Writing: `--set 'Prop=value'`

| Type | Write | Example |
|---|---|---|
| title, text | the text (split in 2,000-character pieces) | `--set 'Task name=Export invoices'` |
| number | a number; empty clears | `--set 'Estimate=3'` |
| select, status | an existing option, any case; empty clears | `--set 'Status=Done'` |
| multi-select | `a,b` or a JSON array; existing options only | `--set 'Tags=Backend,Helpdesk'` |
| date | `date:<Property>:start`, `:end`; `Prop=<date>` is the start | `--set 'date:Done at:start=2026-11-22'` |
| person | `user://<uuid>`, a name or e-mail that matches one person, `me`; several with commas | `--set 'Assignee=me'` |
| relation | page references (url, id, key); several with commas | `--set 'Project=https://app.notion.com/p/<id>'` |
| checkbox | `__YES__` / `__NO__` (also true/false) | `--set 'Completed?=__YES__'` |
| url, e-mail, phone | the text; empty clears | `--set 'Pull Request=https://…/pull/7'` |
| files | `file-upload://<id>` from `notion upload`, or a public url | `--set 'Files=file-upload://<id>'` |
| page title (page parent) | `title` | `--set 'title=Approved plan'` |

- `title` (or `name`) also names a data source's title property, whatever it is called.
- An unknown property or option exits `2` and lists the nearest names; nothing is written. The schema is re-read once before refusing, so an option created a minute ago is found.
- A person given by name or e-mail is looked up among the people the API lists and the people seen in rows read. Several matches exit `2` listing each one's name, e-mail and `user://` id, and nothing is sent: pass the id. An exact e-mail or a `user://` id is never ambiguous. The same holds for `has` in `--where`.
- A list replaces the whole value: to add a tag, write the current tags and the new one.
- Formula, rollup, unique id, created and edited time and by are computed by Notion: writing them exits `2`.
- `--pages-file` takes `[{"properties": {"Task name": "A", "Tags": ["Backend"], "Completed?": true}, "content": "<markdown>", "icon": "🧾"}, …]`: the same keys as `--set`, values as strings, lists, booleans or numbers.

## The `--where` language

A condition is one or more comparisons joined by `AND` and `OR` (`AND` binds first), with parentheses for groups. The client compiles it into the API's filter, so the filtering happens in Notion and only matching rows travel.

```
Status = 'Done' AND Tags has 'Helpdesk' AND created >= 2026-11-01
Project has https://app.notion.com/p/<project id>
"Task name" contains 'invoice'
id in (120, 121)
Assignee has me
"Done at" is empty
(Status = 'Rollout' OR Status = 'Done') AND Assignee has me
```

- A property name with a space or a symbol is quoted with `"` or `` ` ``; a value is quoted with `'` (numbers, dates, urls, keys and `me` can go bare).
- Special names, when the data source has no property by that name: `created` and `edited` (the page timestamps), `id` (the unique id property), `title` (the title property).
- Operators: `=`, `!=`, `has`, `contains`, `>`, `>=`, `<`, `<=`, `is empty`, `is not empty`, `in (a, b, c)`.

| Type | Operators | Becomes |
|---|---|---|
| title, text, url, e-mail, phone | `=` `!=` `contains`/`has` `in (...)` | `equals`, `does_not_equal`, `contains` |
| number | `=` `!=` `>` `>=` `<` `<=` `in (...)` | `equals`, `greater_than`, `greater_than_or_equal_to`… |
| unique id | the number operators; the value may be the key (`id = <PREFIX>-<n>`) | `unique_id` with the number |
| select, status | `=` `!=` `in (...)` | `equals` (a list for `in`), `does_not_equal` |
| multi-select | `has`/`contains`/`=` `!=` `in (...)` | `contains`, `does_not_contain` |
| date, created, edited | `=` `>` `>=` `<` `<=`; dates as `2026-11-01` or `today`, `one_week_ago`… | `equals`, `after`, `on_or_after`, `before`, `on_or_before` |
| person, created by | `has`/`contains`/`=` `!=` with `me`, a name, an e-mail or `user://` | `contains`, `does_not_contain` with the user id |
| relation | `has`/`contains`/`=` `!=` with a page reference | `contains`, `does_not_contain` with the page id |
| checkbox | `=` `!=` with `__YES__`/`__NO__` | `equals`, `does_not_equal` |
| every type but checkbox, unique id, timestamps | `is empty`, `is not empty` | `is_empty`, `is_not_empty` |

- The API nests groups two levels deep at most: `(A OR B) AND C` works, a group inside a group inside a group exits `2`.
- An unknown property, an operator the type does not have, or a value of the wrong type exits `2` naming the part; nothing is sent.
- A status value that is not an option but is a status group name matches the whole group (Notion's rule).
- Formula and rollup properties are not filtered by the condition: use `notion api POST /v1/data_sources/<id>/query --data '<filter json>'`.

## Order, columns, counts

- `--order 'Prop desc'` (several with commas; `created desc` sorts by creation time). Without an order Notion guarantees none.
- `--select 'Status,Assignee'` prints only those columns, plus the url.
- `--count` prints the number of matching rows; `--group-by Prop` prints one line per value with its count, largest first (a multi-select counts each option).
- At most 50 rows are printed unless `--limit N`, with a line saying how many more matched; paging stops at 2,000 rows (`--max-rows N`). Anything the condition cannot express is computed from `--json` in the shell.
