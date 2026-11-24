# The card contract

What a Notion card holds, in which order, within which limits, and which moment writes each part.
Every skill that writes a card writes it from here; `scripts/card_contract.py` holds a card to it,
and the `card-check` hook runs that check after every card write. The hook takes the pages from the
lines the client prints and, on a call that ended well, from the `notion update` calls it can read in
the command: a write whose output is hidden inside any other shape than a list, a pipeline, a
redirection, `bash -c`, a wrapper (`env`, `timeout`, `nice`, `nohup`, `time`, `exec`, `command`,
`sudo`), the body of `if`, `for`, `while` or `until`, a command substitution or an interpreter in
front of the client (a script, `eval` or `xargs`, for example) is not seen. The card is read by the business
in pt-BR, so the zone titles and labels are pt-BR and fixed; the text inside them follows the card.

The names of the workspace (data sources, properties, statuses, toggles) are the names map in
`scripts/card-contract.json`; this file calls them by role (the summary property, the pull request
open status). A machine replaces a default with a key of the same role under `card` in
`~/.config/cdv-notion/config.json`, for example `{"card": {"status": {"pull_request_open": "Em revisão"}}}`.
The map's `since` is the day the pattern starts: a card created before it is never judged, unless a
write replaces its whole body.

## The three kinds of card

| Kind | What tells it | Zones, in order |
| --- | --- | --- |
| Task card | a page of the tasks source that is not a form ticket | `## Pedido`, `## Entrega`, `## Fechamento` |
| Form ticket | a page of the tasks source whose form e-mail property is filled and whose body has no `## Pedido` | the form's own sections, as the form wrote them, then `## Fechamento` |
| Project page | a page of the projects source | the request toggle, the current toggle, the checklist toggle |

Any other page (a plan page under a task, a sprint, a page of another source) is not a card.

### Task card

- `## Pedido` holds the request as it arrived, in the words of who asked. It is never rewritten: a
  body someone else wrote goes under `## Pedido` without changing a word.
- `## Entrega` holds the labels `**Objetivo:**`, `**Pronto quando:**`, `**Fora desta entrega:**`,
  `**Onde:**`, `**Plano:**` and `**PRs:**`, in that order. `**Objetivo:**` is one sentence.
  `**Pronto quando:**` is followed by 1 to 5 list items someone can observe. `**Plano:**` mentions the
  child page that holds the approved plan; a card with no plan has no `**Plano:**` line.
  `**PRs:**` lists every pull request as `<repository> #<n>`, separated by ` · `.
- `## Fechamento` holds 1 to 3 list items: what changed for who asked, and `Fora do código:` for what
  was done or is pending outside the code.

### Form ticket

The form's sections stay as the form wrote them. At closing the ticket gains `## Fechamento` with 1
to 3 list items and the line `PR: #<n>` linked to the pull request; a ticket closed with no code
change gets the summary property only. A form ticket kept in a merge of requests has its own sections
moved once, unchanged, under a new `## Pedido`, and is a task card from then on.

### Project page

- The request toggle holds the briefing as it arrived; no skill writes in it.
- The current toggle holds the project as it stands, under these sub-headings, in this order:
  `### 🎯 Objetivo`, `### ✅ O que será feito`, `### 🚫 O que NÃO será feito`, `### 🔗 Dependências`,
  `### 🔎 Decisões`, `### 🧾 Mudanças de escopo`. The first three are owed as soon as the toggle
  holds text.
- Each line under `### 🧾 Mudanças de escopo` starts with a bold `dd/mm` date followed by ` · `.
- The checklist toggle holds the effort score table; the score property holds its total.

## Limits

- `**Pronto quando:**` holds 1 to 5 list items.
- `## Fechamento` holds 1 to 3 list items.
- An item that is still a placeholder of a skeleton (`- <what changed for who asked>`) is not an item.
- A card holds one `## Fechamento`: a second one is a finding from the merged status on.
- The summary property holds one sentence of at most 200 characters on one line: what changed for
  who asked. It is the first sentence of the pull request's TL;DR, copied unchanged.
- No status in the body: a line that starts with the status property's name and a colon is a finding,
  except inside the words of who asked (the request zone of a task, the request toggle of a project,
  a form ticket's own sections above `## Fechamento`), which no rule asks to rewrite.

## The five moments of a task

| Moment | What it writes | Status role |
| --- | --- | --- |
| Request arrives | properties only: the requester, the type and, when someone else asked or it is a bug, the request tag | not started |
| Plan approved, or work starts on a track with no plan | `## Entrega` and the plan page (a child page of the card, `Plano técnico: <card title>`), plus the assignee, the type and the current sprint | in progress |
| Pull request open | the `**PRs:**` line, the pull request property and the summary property | pull request open |
| Merged or deployed | `## Fechamento` | merged or deployed |
| Validated by who asked | nothing in the body | done |

A card whose request another card absorbed gets the archived status and, as the first line of its
body, `Pedido atendido em <key of the kept card>.`

## Skeletons

`card_contract.py skeleton <kind>` prints each of these, ready to paste. Text between `<` and `>` is
filled per card; the titles, the labels and their order are fixed. Blank lines are not part of the
contract, and neither is the way Notion writes inline formatting back (bold reads back as
`<b>...</b>`, an underscore as `\_`, an ampersand as `&amp;`, a coloured label inside a `<span>`):
the checker compares titles, labels and dates as plain text, with every inline tag dropped and
backslash and entity escapes undone. An empty paragraph, which a fetch returns as a line holding
only `<p />` or `<empty-block/>`, is a blank line.

Task card, with a plan (`skeleton task`):

```markdown
## Pedido

<the request as it arrived, in the words of who asked; never rewritten>

## Entrega

**Objetivo:** <one sentence>

**Pronto quando:**

- <1 to 5 criteria someone can observe>

**Fora desta entrega:** <what does not enter, and where it goes>

**Onde:** <repository>, <repository>

**Plano:** <mention of the child page>

**PRs:** <repository> #<n> · <repository> #<n>

## Fechamento

- <what changed for who asked>
- Fora do código: <what was done or is pending outside the code>
```

Task card without a plan (`skeleton task-small`):

```markdown
## Pedido

<the request as it arrived, in the words of who asked; never rewritten>

## Entrega

**Objetivo:** <one sentence>

**Pronto quando:**

- <1 to 5 criteria someone can observe>

**Fora desta entrega:** <what does not enter, and where it goes>

**Onde:** <repository>, <repository>

**PRs:** <repository> #<n> · <repository> #<n>

## Fechamento

- <what changed for who asked>
- Fora do código: <what was done or is pending outside the code>
```

Form ticket at closing (`skeleton form-closing`), appended after the form's own sections:

```markdown
## Fechamento

- <what changed for who asked>
- Fora do código: <what was done or is pending outside the code>

PR: #<n>
```

Project page (`skeleton project`), what goes inside the current toggle:

```markdown
### 🎯 Objetivo

<one paragraph, present tense>

### ✅ O que será feito

- <...>

### 🚫 O que NÃO será feito

- <...>

### 🔗 Dependências

- <...>

### 🔎 Decisões

<pointer to the decisions and, per slice, to the task that holds its plan>

### 🧾 Mudanças de escopo

- **<dd/mm>** · Entrou: <...>. Saiu: <...>. <who decided, or where it came from>. CES de <x> para <y>.
```

A scope line with no change of score ends `CES sem mudança.`; `Entrou:` or `Saiu:` is left out when
nothing entered or left.

## The check

`card_contract.py check <ref> [--body-replaced] [--json]` reads the card through the `cdv-notion`
client's `notion fetch` and never writes to Notion. It prints one line per finding,
`<rule>: <what is wrong>. <what to write>`, at most 2,000 characters in all; `--json` prints the same
findings as a list of objects with `rule`, `message` and `fix`.

| Exit | Meaning |
| --- | --- |
| `0` | the card is clean, is not a card, was created before `since`, or names people none of whom is this machine's person (unless `--body-replaced`) |
| `1` | findings |
| `2` | the command, or the settings file, is wrong |
| `3` | no usable Notion token (`notion auth login`) |
| `4` | the page cannot be read (403, 404, Notion unreachable) |

What a task owes grows with its status: not started, archived and a status the map does not name
owe nothing of the body; in progress owes `## Pedido`, `## Entrega` with `**Objetivo:**` and
`**Pronto quando:**`, the assignee, the requester and the type; pull request open owes the pull
request property and the summary, and the `**PRs:**` line (on a form ticket `PR: #<n>`) and the
property agree from then on (such a line in the words of who asked is theirs, not the card's); merged, deployed and done owe the summary, and `## Fechamento` when the
card has a pull request. A form ticket never owes `## Pedido` nor `## Entrega`.

The first check of a card pins its request zone (the text from `## Pedido` to `## Entrega`, or the
request toggle of a project) as a digest under the client's cache directory, never as text. A later
change is the finding `request-changed`: the zone is restored, not rewritten, unless who asked
changed it, and then `card_contract.py accept-request <ref>` pins the new text. The digest is taken
over the words of the request, with only their formatting dropped (bold, italics, colour): the text
inside a code fence, the target of every link and mention and the day of a date are kept. Of a mention
the name shown is not kept: it follows the page or the person the mention points at. Of a picture
or a file it keeps the caption and the address without its query string, whose signed part changes at
every read.

Of a page whose body the client could not read whole (the read is marked as truncated), the
properties are judged and nothing of the body is: no zone, label or toggle, and no request is pinned
or compared. One line on stderr says the body was too long to read whole; it is not a finding.
