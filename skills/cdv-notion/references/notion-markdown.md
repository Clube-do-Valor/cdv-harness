# Notion-flavored Markdown — what a body file holds

The client reads and writes page bodies with `markdown_version: "v2"` of the markdown endpoints (`GET` and `PATCH /v1/pages/{id}/markdown`, `markdown` on `POST /v1/pages`). That syntax is Notion-flavored Markdown; the official reference is https://developers.notion.com/guides/data-apis/notion-flavored-markdown.md, and it is the same specification the Notion MCP server gave the model, so bodies written for the MCP keep working. This page is the short version the skills write in.

## Base

- CommonMark plus GFM tables, task lists (`- [ ]`, `- [x]`) and strikethrough.
- Headings `#` to `####` (a `#####` becomes `####`). A plain heading has no children; for a collapsible heading use `<toggle heading="h2">`. In a body file for `notion create`, start at `##`: when the only `#` heading is the first line, Notion takes it for a title and leaves it out of the page.
- Divider: `---` on its own line, with a blank line around it.
- Code: always fenced, never indented; the fence is longer than the longest backtick run inside. The language comes back in its short form (` ```python ` reads as ` ```py `).
- Hard line break: a trailing `\` (it reads back as `<br />`). Empty paragraph: `<p />`.
- Every block starts on a new line after a blank line.
- Inline math `$x$`; display math between two lines that hold only `$$`.
- Any HTML tag not listed here loses its tag and keeps its text (`<div>`, `<sup>`), is converted (`<mark>` to a yellow background, `<details>` to a toggle) or, when Notion does not know it at all, is saved as literal text. `notion update` prints a `warning` line for each; `notion create` prints none, because the API returns none. Escape a literal tag in text as `\<tag>`; escape `[`, `]`, `|`, `$`, `*` where they would be read as syntax (`\[Module\]`, `R\$ 10`).

## Inline

- `<b>`, `<i>`, `<s>`, `<u>` (the only underline); use the tag form when the styled text has a space at either end.
- Colour: `<span color="red">word</span>`; colours `gray brown orange yellow green blue purple pink red`, and the `_bg` forms (`blue_bg`) for backgrounds of whole blocks.
- Mentions: `<mention url="user://<uuid>">Name</mention>` for a person, `<mention url="https://app.notion.com/p/<id>">Title</mention>` for a page. Never a bare `@Name`: it does not notify and does not link.
- Date: `<date start="2026-11-22" />`, with `end`, `start-time="09:00"`, `time-zone="Europe/Lisbon"` when needed.
- Links: `[text](url)`.

## Blocks with a tag

Every container has one shape: the opening tag, the title text on the next line, a blank line, the children as plain markdown, the closing tag. No blank line right after the opening tag or right before the closing one.

Callout:

```markdown
<callout icon="⚡" color="blue_bg">
<b>TL;DR:</b> What changes, in one or two sentences.
</callout>
```

Toggle:

```markdown
<toggle>
Details of the investigation

- first finding
- second finding
</toggle>
```

Quote with colour: `<quote color="gray_bg">` … `</quote>`. Columns: `<columns><column>…</column><column>…</column></columns>`.

## Tables

A plain table is a pipe table (`| a | b |`, `| --- | --- |`, a `|` inside a cell escaped as `\|`). A styled table — a header row, a fitted width, coloured cells — uses the tag form, never mixed with pipes. Cells hold inline text only; `<br />` breaks a line inside a cell.

```markdown
<table fit-page-width="true" header-row="true">
<tr><td></td><td>Before</td><td>After</td></tr>
<tr><td><b>Export</b></td><td>by hand</td><td>one click</td></tr>
</table>
```

`<table header-row="true">` without `fit-page-width` is the same table at its natural width, stored with its header row; it reads back as a pipe table, because a header row is all a pipe table has. A `<table>` with no header row, a header column, a fitted width or colours reads back in the tag form, with each `<td>` on lines of its own. Other tags: `header-column="true"`, `<tr color="blue_bg">`, `<td color="red_bg">`.

## Media, files and child pages

- Image: `![caption](url)` on its own line. File, PDF, audio, video, bookmark, embed: `<file source="url">caption</file>`, `<pdf source="url">…</pdf>`, `<bookmark source="url" />`, `<embed source="url" />`.
- Uploaded file: the line `notion upload` prints, `![name](file-upload://<id>)` or `<file source="file-upload://<id>">name</file>` (also `<pdf>`, `<audio>`, `<video>`), on its own line. The API's markdown does not know that address and would store an empty block, so the client writes the body and then gives each block its file; a body written another way (`notion api`) needs that second step: `notion api PATCH /v1/blocks/<block> --data '{"image": {"file_upload": {"id": "<id>"}}}'`.
- A hosted file reads back as `<image source="https://…signed…#notion_record=block.<id>…">caption</image>` (or `<file …>`). Keep that address as it is in a rewrite: Notion recognises it and keeps the file. `notion download '<that url>'` (quoted) or the block id saves it.
- Child page: `<page url="https://app.notion.com/p/<id>">Title</page>`. Child database: `<database url="…">Title</database>`. Keep these tags when rewriting a body: a rewrite without one deletes the child, and the client refuses it unless `--allow-deleting-content` is passed.
- `<unknown url="…" alt="…" />` marks a block the API could not render (truncated page, block not shared, unsupported type): leave it as it is.

## What comes back

A read gives the body in this same syntax, with signed file urls that expire after about an hour. The form is not always the one written: bold, italic, strike and inline code come back as `<b>`, `<i>`, `<s>` and `<code>` whatever form they were written in, a table with only a header row as a pipe table, a hard line break as `<br />`, a coloured quote or a styled table in the tag form. The blocks are the same. So copy the `OLD` of an `--edit` from a `notion fetch` of the page, never from the file that wrote it. An empty page reads back as an empty body. A write that used a tag the parser does not know still runs and returns a `warning` line: report it.
