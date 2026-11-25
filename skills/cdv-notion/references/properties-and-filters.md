# Properties in the short format, and the `--where` language

The client reads and writes properties in the short format the Notion MCP used, so the habits and the skill text carry over. The client looks up each property in the data source schema and converts to and from the API's typed values; the model never writes the typed JSON.

## Reading

`notion fetch <page>` prints a JSON object, one key per property:

| Type | Printed as |
|---|---|
| title, text | the text as it is, with each link as `[text](address)`; only text that would read as a link is escaped ([links in text](#links-in-text)) |
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
| title, text | the text (split in 2,000-character pieces); `[text](https://…)` becomes a link ([links in text](#links-in-text)) | `--set 'Notes=See [the runbook](https://example.com/runbook)'` |
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
- A text value that was read and written back keeps its text and its links ([links in text](#links-in-text)). Bold, italic, code and mentions inside a text property are read as plain text ([api-limits.md](api-limits.md)). The `title:` line of a fetch, and every condition, use the plain text.
- An unknown property or option exits `2` and lists the nearest names; nothing is written. The schema is re-read once before refusing, so an option created a minute ago is found.
- A person given by name or e-mail is looked up among the people the API lists and the people seen in rows read. Several matches exit `2` listing each one's name, e-mail and `user://` id, and nothing is sent: pass the id. An exact e-mail or a `user://` id is never ambiguous. The same holds for `has` in `--where`.
- A list replaces the whole value: to add a tag, write the current tags and the new one.
- Formula, rollup, unique id, created and edited time and by are computed by Notion: writing them exits `2`.
- `--pages-file` takes `[{"properties": {"Task name": "A", "Tags": ["Backend"], "Completed?": true}, "content": "<markdown>", "icon": "🧾"}, …]`: the same keys as `--set`, values as strings, lists, booleans or numbers.

### Links in text

A link in a title or text value (and in a comment, when it is printed) is `[text](address)`. What is printed and given back to `--set` stores the same text and the same links. What is escaped, and nothing else:

| Where | Written | Example |
|---|---|---|
| plain text that would read as a link | a backslash before its `[` | `\[text](https://example.com)` is the text `[text](https://example.com)`, not a link: write it this way to store the characters |
| backslashes right before that `[`, or right before a link | doubled | `C:\\[docs](https://example.com)` is the text `C:\` and a link |
| the text of a link: a `[` or `]` that is not one balanced pair, and then every `\` too | `\[` `\]` `\\` | `[a \[ b](https://example.com)`, `[C:\\dir](https://example.com)`; `[the [old] docs](https://example.com)` needs nothing |
| the address of a link: a space, a `\`, and a parenthesis that is not one balanced pair | a backslash before it | `[x](https://example.org/a\)b)`; `[x](https://example.org/wiki/Name_(thing))` needs nothing |
| an address that does not start with `http://`, `https://`, `mailto:` or `tel:` | between `<` and `>` | `[open](<notion://example/page>)`, `[site](<example.com>)` |

- Any other text is literal: `[draft]`, `[x] (y)`, `[z](relative)`, `[w](ftp://example.com)`, `a \[b\]` and a backslash anywhere else stay as they are, read and written.
- A link to a page inside Notion is stored as a path and printed in full, `[page](https://app.notion.com/<32 hex>)`; written back it is the path again. A path with a query (`/p/<32 hex>?pvs=…`) is returned by the API and refused when written, so it is written back as the full address of the same page.
- Notion stores `http`, `https`, `mailto:`, `tel:`, a bare domain or e-mail (`example.com`, `ana@example.com`), `notion:`, and most other schemes when what follows `://` is a domain (`sftp://example.com/a`, `linear://example.com/a`). It refuses (400, nothing changed) `ftp:`, `file:`, `javascript:`, `data:`, `sms:`, an app link with no domain (`slack://channel?id=…`) and any other path or anchor. It rewrites some addresses on its own: a capital scheme or host in lower case, `https://example.com` with a final `/`, a space as `%20`, a backslash as `/`.

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
| select, status | `=` `!=` `in (...)` | `equals`, `does_not_equal` |
| multi-select | `has`/`contains`/`=` `!=` `in (...)` | `contains`, `does_not_contain` |
| date, created, edited | `=` `>` `>=` `<` `<=` `in (...)`; dates as `2026-11-01` or `today`, `one_week_ago`… | `equals`, `after`, `on_or_after`, `before`, `on_or_before` |
| person, created by | `has`/`contains`/`=` `!=` `in (...)` with `me`, a name, an e-mail or `user://` | `contains`, `does_not_contain` with the user id |
| relation | `has`/`contains`/`=` `!=` `in (...)` with a page reference | `contains`, `does_not_contain` with the page id |
| checkbox | `=` `!=` with `__YES__`/`__NO__` | `equals`, `does_not_equal` |
| every type but checkbox, unique id, timestamps, place, button | `is empty`, `is not empty` | `is_empty`, `is_not_empty` |

- `Prop in (a, b, c)` becomes an `or` group of one single-value condition per value (`equals` for select, status, number, unique id, text and dates; `contains` for multi-select, person and relation), because those conditions take one value. On a type with no single-value equality (formula, rollup, files) it exits `2`.
- The API nests groups two levels deep at most: `(A OR B) AND C` works, a group inside a group inside a group exits `2` naming the group. An `in (...)` counts as a group: `(A AND Status in ('Done', 'Rollout')) OR C` is three levels deep.
- A date with no time is the whole day **in UTC**, for created and edited times and for date properties: `created = 2026-11-03` is from 00:00 to 24:00 UTC, so a card made at 22:00 on the 2nd in UTC-3 counts on the 3rd. `>` starts after the end of that day, `<=` includes all of it, and a date-time with no offset is UTC too. For a local day write the instants: `created >= 2026-11-03T00:00:00-03:00 AND created < 2026-11-04T00:00:00-03:00`. A date property that holds only a date counts as 00:00 UTC of that date, so an instant with an offset can leave that day's date-only rows out.
- An unknown property, an operator the type does not have, or a value of the wrong type exits `2` naming the part; nothing is sent.
- A status value that is not an option but is a status group name matches the whole group (Notion's rule).
- Formula and rollup properties are not filtered by the condition: use `notion api POST /v1/data_sources/<id>/query --data '<filter json>'`.

## Order, columns, counts

- `--order 'Prop desc'` (several with commas; `created desc` sorts by creation time). Without an order Notion guarantees none.
- `--select 'Status,Assignee'` prints only those columns, plus the url. It takes the special names of `--where` too (`created`, `edited`, `id`, `title`, with the same spelling and the same rule that a property of that name wins); `created` and `edited` print the page's own created and last edited time, under the column name `created_time` and `last_edited_time`, in the plain output and in `--json`.
- `--count` prints the number of matching rows; `--group-by Prop` prints one line per value with its count, largest first (a multi-select counts each option).
- At most 50 rows are printed unless `--limit N`, with a line saying how many more matched; paging stops at 2,000 rows (`--max-rows N`). Anything the condition cannot express is computed from `--json` in the shell.
- With `--json`, stdout is one JSON document and nothing else: the rows (a list), the number with `--count`, or an object of value to count with `--group-by`. The notes (more rows matched, paging stopped, no row matched) go to stderr.
