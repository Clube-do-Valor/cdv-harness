#!/usr/bin/env python3
"""card_contract.py - hold a Notion card to the card contract (references/card-contract.md).

  card_contract.py check <ref> [--body-replaced] [--json]
  card_contract.py accept-request <ref>
  card_contract.py skeleton task|task-small|form-closing|project

`check` reads the page through the cdv-notion client's `fetch` (never anything else, never a write),
works out what kind of card it is (task card, form ticket, project page, or not a card), which
moment its status puts it in, and prints one line per rule it breaks:
`<rule>: <what is wrong>. <what to write>`. Nothing is printed for a clean card, a page that is not
a card, a card created before the pattern's start day (`since`) or a card of someone else, unless
`--body-replaced` says the write just replaced its whole body.

A page whose body the client could not read whole (the read is marked `truncated`) has its properties
judged and nothing of its body judged, pinned or compared; one line on stderr says so, and it is not a
finding.

Exit codes: 0 clean (or not judged); 1 findings; 2 the command or the settings file is wrong;
3 no usable Notion token; 4 the page cannot be read (403, 404, Notion unreachable, no client).

The names of the workspace (sources, properties, statuses, toggles) are the map in
card-contract.json beside this script; a key of the same role under "card" in
~/.config/cdv-notion/config.json replaces a default, for example
{"card": {"status": {"pull_request_open": "Em revisão"}, "since": "2026-12-01"}}.

The request zone of a card (the text from `## Pedido` to `## Entrega`, or the content of a
project's request toggle) is pinned as a sha256 digest under the client's cache directory, never as
text; a later change is the finding `request-changed` until `accept-request` pins the new text.
"""

import argparse
import bisect
import contextlib
import copy
import datetime
import hashlib
import html
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
DATA = HERE / "card-contract.json"
CLIENT_PATH = HERE.parent.parent / "cdv-notion" / "scripts" / "notion"
KINDS = ("task", "task-small", "form-closing", "project")
CLEAN, FINDINGS, USAGE, NO_TOKEN, UNREADABLE = 0, 1, 2, 3, 4
BUDGET = 2000
QUOTE = 60

# The order of the moments a task's status can put it in; merged and deployed are one moment.
RANKS = {"in_progress": 1, "pull_request_open": 2, "merged": 3, "deployed": 3, "done": 4}
PROJECT_HEADINGS = [
    "🎯 Objetivo",
    "✅ O que será feito",
    "🚫 O que NÃO será feito",
    "🔗 Dependências",
    "🔎 Decisões",
    "🧾 Mudanças de escopo",
]
PROJECT_REQUIRED = PROJECT_HEADINGS[:3]
SCOPE_HEADING = PROJECT_HEADINGS[5]

_client = None


class Stop(Exception):
    def __init__(self, code, message=""):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------------------------
# The contract's data and the names map
# ---------------------------------------------------------------------------------------------


def data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def merge(defaults, override, path):
    """The defaults with the override's values; a key the defaults do not have is an error."""
    if not isinstance(override, dict):
        raise Stop(USAGE, f"{path} must be an object of roles")
    merged = copy.deepcopy(defaults)
    for key, value in override.items():
        where = f"{path}.{key}"
        if key not in defaults:
            known = ", ".join(sorted(defaults))
            raise Stop(USAGE, f"{where} is not a role of the card names map (known under {path}: {known})")
        if isinstance(defaults[key], dict):
            merged[key] = merge(defaults[key], value, where)
        elif isinstance(value, str) and value.strip():
            merged[key] = value.strip()
        else:
            raise Stop(USAGE, f"{where} must be a non-empty string")
    return merged


def names(settings=None):
    """The names map: the contract's defaults with the machine's `card` settings over them."""
    defaults = data()["names"]
    override = (settings or {}).get("card")
    if override is None:
        return defaults
    merged = merge(defaults, override, "card")
    try:
        datetime.date.fromisoformat(merged["since"])
    except ValueError:
        raise Stop(USAGE, f"card.since must be a date YYYY-MM-DD, got {merged['since']!r}")
    return merged


def limits():
    return data()["limits"]


# ---------------------------------------------------------------------------------------------
# Text: the two forms of the same words
# ---------------------------------------------------------------------------------------------

ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|<>$~])")
INLINE_TAG = re.compile(r"</?[A-Za-z][\w-]*(?:\s[^<>]*)?/?>")
BOLD_TAG = re.compile(r"</?(?:b|strong)>", re.I)
EMPTY_PARAGRAPH = re.compile(r"^<(?:p|empty-block)\s*/>$")


def plain(text):
    """The words of a markdown line with inline formatting dropped: `**x**`, `__x__`, every inline tag
    (`<b>x</b>`, `<strong>`, a coloured `<span color="blue">`), italics, inline code, backslash escapes
    and entity escapes all read as the bare text, so a card read back from Notion (bold as `<b>`, `_`
    as `\\_`, `&` as `&amp;`) compares equal to the form it was written in."""
    kept = []

    def hold(match):
        kept.append(match.group(1))
        return f"\x00{len(kept) - 1}\x00"

    text = ESCAPE.sub(hold, text)
    text = INLINE_TAG.sub("", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", text)
    text = html.unescape(text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
    return text.replace("️", "").strip()


def fold(text):
    return " ".join(unicodedata.normalize("NFC", plain(text)).casefold().split())


# A line of the request, read for its digest: an escaped character, a run of backquotes (inline code when
# a later run as long closes it), a tag, a bare address, and the brackets of a link or a picture with its
# address.
REQUEST_TOKEN = re.compile(
    ESCAPE.pattern.replace("(", "(?P<escaped>", 1)
    + r"|(?P<ticks>`+)"
    + r"|(?P<tag><(?P<closing>/?)(?P<name>[A-Za-z][\w-]*)"
      r"(?P<attributes>(?:\s+[\w:-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'<>=`]+))*)\s*/?>)"
    + r"|(?P<bare>https?://[^\s<>\[\]()\\*`]*[^\s<>\[\]()\\*`_~])"
    + r"|(?P<open>!?\[)"
    + r"|\]\((?P<address>(?:[^\s()\\]|\\.|\((?:[^\s()\\]|\\.)*\))*)(?P<rest>(?:\s+(?:\"[^\"]*\"|'[^']*'))?)\)"
    + r"|(?P<close>\])"
)
ATTRIBUTE = re.compile(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'<>=`]+))")
# Tags that only format the words inside them; tags that lay blocks out, read as a space; and tags that
# carry words of their own. Any other tag is text (notion-markdown.md: it is saved as literal text).
FORMAT_TAGS = {"b", "strong", "i", "em", "s", "del", "strike", "u", "ins", "span", "code"}
BLOCK_TAGS = {"p", "br", "empty-block", "callout", "toggle", "quote", "columns", "column", "table", "thead", "tbody",
              "colgroup", "col", "tr", "page", "database", "bookmark", "embed", "unknown", "file", "pdf", "audio",
              "video", "image", "img"}
FILE_TAGS, PLAYED_TAGS = {"file", "pdf", "image", "img"}, {"audio", "video"}
CELL_TAGS = {"td", "th"}
WORD_TAGS = {"a", "mention", "date"}
TARGET_ATTRIBUTES = {"url", "href", "source", "src"}
DATE_ATTRIBUTES = {"start", "end", "start-time", "end-time", "time-zone"}
CAPTION_ATTRIBUTES = {"alt", "caption"}
# The name a mention shows, up to its closing tag; a mention inside it means the first one never closes.
MENTION_NAME = re.compile(r"(?:\\.|(?!\\|</?mention[\s/>]).)*</mention\s*>", re.I)
# The marks of bold, strikethrough and italics: where each one opens and where it closes.
EMPHASIS = [tuple(map(re.compile, (f"{opens}|{closes}", opens, closes))) for opens, closes in (
    (r"\*\*(?=\S)", r"\*\*"), (r"(?<!\w)__(?=\S)", r"__(?!\w)"), (r"~~(?=\S)", r"~~"),
    (r"(?<!\*)\*(?=\S)", r"(?<=\S)\*(?!\*)"), (r"(?<!\w)_(?=\S)", r"(?<=\S)_(?!\w)"))]


def address_of(text):
    """The address a link or a tag holds, escapes undone."""
    return html.unescape(ESCAPE.sub(r"\1", text))


def unsigned(address):
    """The address of a picture or a file without its query string: the signed part changes at every read."""
    return re.sub(r"\?[^#]*", "", address, count=1)


def is_file(name, address):
    """True for the tag of a picture or a file; a video or an audio whose address names no file (a
    player's page) is a link, and its query string says which one it is."""
    return name in FILE_TAGS or (name in PLAYED_TAGS and re.search(r"\.\w{2,5}$", re.split(r"[?#]", address)[0]))


def tag_words(match):
    """What a tag adds to the request's words: nothing for formatting, its target, the days and hours of
    a date, its caption; a tag that is none of Notion's is text."""
    name = match.group("name").lower()
    if name in FORMAT_TAGS:
        return ""
    if name in CELL_TAGS:
        return " " if match.group("closing") else " | "
    if name not in BLOCK_TAGS and name not in WORD_TAGS:
        return match.group("tag")
    said = []
    for key, *values in ATTRIBUTE.findall(match.group("attributes")):
        key, value = key.lower().replace("_", "-"), address_of("".join(values))
        if key in TARGET_ATTRIBUTES:
            said.append(f"<{unsigned(value) if is_file(name, value) else value}>")
        elif key in CAPTION_ATTRIBUTES or (name == "date" and key in DATE_ATTRIBUTES):
            said.append(f"<{key}={value}>")
    space = " " if name in BLOCK_TAGS else ""
    return space + "".join(sorted(said)) + space


def mention_end(match, line):
    """Where the tag `match` ends on the line; of a mention that holds a target, where its closing tag
    does: the name it shows follows the page or the person it points at, so it is no word of the request."""
    end = match.end()
    if match.group("name").lower() != "mention" or match.group("tag").endswith("/>"):
        return end
    if not any(key.lower() in TARGET_ATTRIBUTES and "".join(value) for key, *value in ATTRIBUTE.findall(match.group("attributes"))):
        return end
    shown = MENTION_NAME.match(line, end)
    return shown.end() if shown else end


def without_pairs(text, mark, opens, closes):
    """The text without the marks of one kind that pair up around some text; a mark alone is text."""
    out, last, opened = [], 0, None
    for match in mark.finditer(text):
        if opened is None:
            opened = match if opens.match(text, match.start()) else None
        elif closes.match(text, match.start()) and match.start() > opened.end():
            out += [text[last : opened.start()], text[opened.end() : match.start()]]
            last, opened = match.end(), None
    return "".join(out) + text[last:]


def request_words(line):
    """The words of one line of the request with only their formatting dropped (bold, italics, colour,
    inline code marks, escapes): the target of every link and mention, the days and hours of a date and
    the text of inline code stay, and of a picture or a file its caption and its unsigned address; of a
    mention the name shown does not. `plain`, which labels and titles are compared with, drops every tag."""
    kept, out, last, brackets, runs = [], [], 0, [], {}
    for run in re.finditer("`+", line):  # where the runs of backquotes of each length start
        runs.setdefault(len(run.group(0)), []).append(run.start())

    def hold(text):
        kept.append(text)
        return f"\x00{len(kept) - 1}\x00"

    while match := REQUEST_TOKEN.search(line, last):  # from the end of the last one: a mention's name is not read
        out.append(line[last : match.start()])
        last = mention_end(match, line) if match.group("tag") else match.end()
        if match.group("escaped"):
            out.append(hold(match.group("escaped")))
        elif match.group("ticks"):
            length = len(match.group("ticks"))
            starts = runs.get(length, [])
            place = bisect.bisect_left(starts, last)
            if place < len(starts):
                out.append(hold(line[last : starts[place]]))
                last = starts[place] + length
            else:  # a run that nothing closes is text
                out.append(match.group("ticks"))
        elif match.group("tag"):
            said = tag_words(match)
            out.append(hold(said) if said.strip() else said)
        elif match.group("bare"):
            out.append(hold(address_of(match.group("bare"))))
        elif match.group("open"):
            brackets.append(match.group("open"))
            out.append(match.group("open"))
        else:
            opened = brackets.pop() if brackets else ""
            if match.group("close"):
                out.append("]")
                continue
            address = address_of(match.group("address"))
            out.append("]" + hold(f"({unsigned(address) if opened == '![' else address}){match.group('rest')}"))
    text = "".join(out) + line[last:]
    for mark, opens, closes in EMPHASIS:
        text = without_pairs(text, mark, opens, closes)
    text = html.unescape(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text).replace("️", "")


def digest(text):
    """The sha256 of the request's words: each line with its formatting dropped, and what a code fence
    holds as it is written (the fence's own marks and its language are formatting), whitespace collapsed."""
    lines = text.splitlines()
    words = []
    for line, state in zip(lines, fences(lines)):
        if state is None:
            words += "" if EMPTY_PARAGRAPH.match(line.strip()) else request_words(line).split()
        elif state == INSIDE:
            words += line.split()
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()


def quote(text):
    text = " ".join(text.split())
    return text if len(text) <= QUOTE else text[: QUOTE - 3] + "..."


# ---------------------------------------------------------------------------------------------
# The body
# ---------------------------------------------------------------------------------------------

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+\S")
BOLD_DATE = re.compile(
    r"^(?:[-*+]\s+)?(?:\*\*|__|<b>|<strong>)\s*\d{1,2}/\d{1,2}\s*(?:\*\*|__|</b>|</strong>)\s*·\s", re.I
)


FENCE_OPEN = re.compile(r"(`{3,})[^`]*$|(~{3,})")
MARK, INSIDE = "mark", "inside"


def fences(lines):
    """What each line is to a code fence: MARK (a line that opens or closes one), INSIDE, or None. A
    fence closes on a line of its own character alone, at least as long as the one that opened it."""
    out, opened = [], None
    for line in lines:
        bare = line.strip()
        if opened is None:
            match = FENCE_OPEN.match(bare)
            opened = (match.group(1) or match.group(2)) if match else None
            out.append(MARK if match else None)
        elif bare and set(bare) == {opened[0]} and len(bare) >= len(opened):
            opened = None
            out.append(MARK)
        else:
            out.append(INSIDE)
    return out


def body_lines(markdown):
    """The body's lines with fenced code blanked out, so nothing inside a fence is a heading, and an
    empty paragraph as a fetch returns it (`<p />`, `<p/>`, `<empty-block/>`) read as a blank line."""
    lines = (markdown or "").splitlines()
    return ["" if state or EMPTY_PARAGRAPH.match(line.strip()) else line for line, state in zip(lines, fences(lines))]


def heading(line, level=None):
    """(level, plain title) of a markdown heading line, or None."""
    match = HEADING.match(line.strip())
    if not match:
        return None
    if level is not None and len(match.group(1)) != level:
        return None
    return len(match.group(1)), plain(match.group(2).rstrip("#"))  # its closing marks dropped


def h2_index(lines, title):
    wanted = fold(title)
    for index, line in enumerate(lines):
        found = heading(line, 2)
        if found and fold(found[1]) == wanted:
            return index
    return None


def zone(lines, start):
    """The lines after the H2 at `start` up to the next H2."""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if heading(lines[index], 2):
            end = index
            break
    return lines[start + 1 : end]


def label_line(lines, label):
    """(index, text after the label) of the first line that is `label:` once formatting is dropped."""
    wanted = fold(label) + ":"
    for index, line in enumerate(lines):
        text = fold(line)
        if text.startswith(wanted):
            return index, plain(line).split(":", 1)[1].strip()
    return None


def items_after(lines, index):
    """The top-level list items of the list that follows line `index` (blank lines skipped)."""
    count, seen_list = 0, False
    for line in lines[index + 1 :]:
        if not line.strip():
            continue
        if LIST_ITEM.match(line):
            count += 1
            seen_list = True
        elif seen_list and line[:1] in (" ", "\t"):
            continue
        else:
            break
    return count


def top_items(lines):
    return sum(1 for line in lines if LIST_ITEM.match(line))


def request_span(lines):
    """(first, end) line indexes of the request zone: from `## Pedido` to `## Entrega` (or to
    `## Fechamento`, or the end), the heading included; None when there is no `## Pedido`."""
    start = h2_index(lines, "Pedido")
    if start is None:
        return None
    end = len(lines)
    for title in ("Entrega", "Fechamento"):
        index = h2_index(lines, title)
        if index is not None and index > start:
            end = min(end, index)
    return start, end


TOGGLE_OPEN = re.compile(r"^<toggle(?:\s[^>]*)?>$")


def toggles(lines):
    """[(title, child lines)] of the toggles at the top of the body."""
    return [(title, [lines[i] for i in children]) for title, children, _, _ in toggle_spans(lines)]


def toggle_spans(lines):
    """[(title, child lines' range, first, end)] of the toggles at the top of the body, with the line
    indexes the toggle runs over (its closing tag included)."""
    found, index = [], 0
    while index < len(lines):
        if not TOGGLE_OPEN.match(lines[index].strip()):
            index += 1
            continue
        depth, title, first_child, cursor = 1, None, None, index + 1
        while cursor < len(lines) and depth:
            stripped = lines[cursor].strip()
            if TOGGLE_OPEN.match(stripped):
                depth += 1
            elif stripped == "</toggle>":
                depth -= 1
                if not depth:
                    break
            if title is None and stripped:
                title = re.sub(r"^#{1,6}\s+", "", stripped)
                first_child = cursor + 1
            cursor += 1
        children = range(cursor if first_child is None else first_child, cursor)
        tagged, end, rest = (title or "").rpartition(">")  # past the last `>` no tag closes
        found.append((plain(re.sub(r"<[^>]+>", "", tagged + end) + rest), children, index, cursor + 1))
        index = cursor + 1
    return found


# ---------------------------------------------------------------------------------------------
# The page, through the client's fetch
# ---------------------------------------------------------------------------------------------


def client():
    global _client
    if _client is None:
        if not CLIENT_PATH.is_file():
            raise Stop(UNREADABLE, f"the cdv-notion client is not installed at {CLIENT_PATH}")
        loader = importlib.machinery.SourceFileLoader("cdv_notion_client_for_cards", str(CLIENT_PATH))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        _client = module
    return _client


def fetch(ref):
    """The client's `fetch <ref> --json`, parsed; its exit codes become this script's."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = client().main(["fetch", ref, "--json"])
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else USAGE
    message = err.getvalue().strip()
    if code == 0:
        if message:
            print(message, file=sys.stderr)
        return json.loads(out.getvalue())
    if code == NO_TOKEN:
        raise Stop(NO_TOKEN, message)
    if code == USAGE:
        raise Stop(USAGE, message)
    raise Stop(UNREADABLE, message or f"the page {ref} cannot be read")


def settings():
    try:
        return client().settings()
    except Exception as failure:  # the client's Fail on a settings file that is not JSON
        code = getattr(failure, "code", USAGE)
        raise Stop(code if code == USAGE else USAGE, getattr(failure, "message", str(failure)))


def rich(value):
    return "".join(part.get("plain_text") or (part.get("text") or {}).get("content", "") for part in value or [])


def prop(page, name):
    """The plain value of a property: text, a select name, a url, an e-mail, a list of people."""
    found = (page.get("properties") or {}).get(name)
    if not isinstance(found, dict):
        return None
    kind = found.get("type")
    value = found.get(kind)
    if kind in ("title", "rich_text"):
        return rich(value)
    if kind in ("select", "status"):
        return (value or {}).get("name")
    if kind in ("people", "relation", "multi_select"):
        return list(value or [])
    return value


def filled(value):
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


class Card:
    def __init__(self, ref, fetched, names_map):
        self.ref = ref
        self.page = fetched.get("page") or {}
        body = fetched.get("markdown") or {}
        self.markdown = body.get("markdown") or ""
        self.whole = not body.get("truncated")
        self.names = names_map
        self.lines = body_lines(self.markdown)
        self.kind = None

    @property
    def id(self):
        return self.page.get("id", "")

    @property
    def key(self):
        """The ticket key of the page (its unique id property), or an empty string."""
        for value in (self.page.get("properties") or {}).values():
            unique = value.get("unique_id") if isinstance(value, dict) and value.get("type") == "unique_id" else None
            if unique and unique.get("prefix") and unique.get("number") is not None:
                return f"{unique['prefix']}-{unique['number']}"
        return ""

    def named_by(self, ref):
        """True when a reference (a key, a url, an id), read as the client reads it, names this page."""
        try:
            found = client().parse_ref(ref)
        except Exception:  # the client's Fail: not a reference
            return False
        if found.kind == "key":
            return f"{found.prefix}-{found.number}".lower() == self.key.lower()
        return found.kind == "id" and found.value.lower() == self.id.lower()


def source_title(page):
    parent = page.get("parent") or {}
    source = parent.get("data_source_id")
    if parent.get("type") != "data_source_id" or not source:
        return None
    schema = fetch(source)
    if schema.get("object") != "data_source":
        return None
    return rich(schema.get("title"))


def classify(card):
    tasks, projects = card.names["tasks"], card.names["projects"]
    title = source_title(card.page)
    if title is None:
        return None
    if fold(title) == fold(tasks["source"]):
        email = prop(card.page, tasks["properties"]["email"])
        if filled(email) and h2_index(card.lines, "Pedido") is None:
            return "form"
        return "task"
    if fold(title) == fold(projects["source"]):
        return "project"
    return None


def before_since(card):
    created = card.page.get("created_time") or ""
    try:
        when = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is not None:
        when = when.astimezone(datetime.timezone.utc)
    return when.date() < datetime.date.fromisoformat(card.names["since"])


def me():
    """The person this machine acts for, as the client knows it: `me` in its settings, else git."""
    wanted = (settings().get("me") or "").strip()
    if not wanted:
        try:
            wanted = (client().git_email() or "").strip()
        except Exception:
            wanted = ""
    return wanted


def someone_elses(card):
    """True when the card names people and none of them is this machine's person, as far as can be
    told; an unknown person (no `me`, or a named person whose e-mail is not readable) is not."""
    role = card.names["projects"]["properties"]["executors"] if card.kind == "project" else \
        card.names["tasks"]["properties"]["assignee"]
    people = [p for p in (prop(card.page, role) or []) if isinstance(p, dict)]
    if not people:
        return False
    mine = me()
    if not mine:
        return False
    if mine.startswith("user://"):
        wanted = mine[len("user://"):].replace("-", "").lower()
        return not any(str(p.get("id", "")).replace("-", "").lower() == wanted for p in people)
    try:
        cached = client().Cache().get("people") or {}
    except Exception:
        cached = {}
    known = True
    for person in people:
        email = ((person.get("person") or {}).get("email")) or (cached.get(person.get("id"), {}) or {}).get("email")
        if not email:
            known = False
            continue
        if email.strip().casefold() == mine.casefold():
            return False
    return known


# ---------------------------------------------------------------------------------------------
# The request pin
# ---------------------------------------------------------------------------------------------


def pins_dir():
    return Path(client().cache_dir()) / "card-pins"


def pin_path(page_id):
    safe = re.sub(r"[^0-9A-Za-z-]", "", page_id)
    return pins_dir() / f"{safe}.json"


def read_pin(page_id):
    try:
        return json.loads(pin_path(page_id).read_text(encoding="utf-8")).get("digest")
    except (OSError, ValueError, AttributeError):
        return None


def write_pin(page_id, value):
    try:
        folder = pins_dir()
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = pin_path(page_id)
        scratch = folder / f".{target.name}.{os.getpid()}.tmp"
        scratch.write_text(json.dumps({"digest": value}), encoding="utf-8")
        os.replace(scratch, target)
    except OSError:
        pass  # a pin that cannot be stored only means the next check pins again


def card_request(kind, markdown, names_map):
    """The request zone's text of a card of this kind, or None when it has none. The zone is found on
    the lines with the fences blanked out, and its text is taken as the body holds it, fences included."""
    lines, children = body_lines(markdown), None
    if kind == "task":
        span = request_span(lines)
        children = span and range(span[0] + 1, span[1])
    elif kind == "project":
        wanted = fold(names_map["projects"]["toggles"]["request"])
        children = next((inside for title, inside, _, _ in toggle_spans(lines) if fold(title) == wanted), None)
    if children is None:
        return None
    whole = markdown.splitlines()
    return "\n".join(whole[index] for index in children)


def request_reaches_its_end(kind, lines, names_map):
    """True when the request zone ends at its end marker: `## Entrega` or `## Fechamento` after
    `## Pedido` on a task, the request toggle's closing tag on a project. A zone that runs to the end
    of the text may be a fetch output that was cut."""
    if kind == "task":
        span = request_span(lines)
        return span is not None and span[1] < len(lines)
    wanted = fold(names_map["projects"]["toggles"]["request"])
    return any(fold(title) == wanted and end <= len(lines) and lines[end - 1].strip() == "</toggle>"
               for title, _, _, end in toggle_spans(lines))


def pin_from_fetch_output(text):
    """Pin the request zone from the output of `notion fetch` (text or --json) with no call to
    Notion: used by the card-check hook after a fetch. Returns True when a new pin was stored. An
    output that may be cut pins nothing: the client's truncation marker, or a request zone that does
    not reach its end marker."""
    names_map = names(settings())
    text = text or ""
    page_id = kind = None
    body = None
    try:
        fetched = json.loads(text)
    except ValueError:
        fetched = None
    if isinstance(fetched, dict) and isinstance(fetched.get("page"), dict):
        page = fetched["page"]
        page_id = page.get("id")
        source = (page.get("parent") or {}).get("data_source_id")
        schema = client().Cache().get(f"schema-{source}") if source else None
        title = rich((schema or {}).get("title")) if schema else None
        if (fetched.get("markdown") or {}).get("truncated"):
            return False
        body = ((fetched.get("markdown") or {}).get("markdown")) if fetched.get("markdown") else None
    else:
        lines = text.splitlines()
        if any(line.startswith("(truncated: ") for line in lines):
            return False
        title = None
        for index, line in enumerate(lines):
            if line.startswith("id: ") and page_id is None:
                page_id = line[4:].strip()
            elif line.startswith("parent: data source ") and title is None:
                title = re.sub(r"\([^()]*\)\s*$", "", line[len("parent: data source "):]).strip()
            elif line == "body:":
                rest = lines[index + 1 :]
                while rest and not rest[-1].strip():
                    rest.pop()
                for cut in range(len(rest) - 1, -1, -1):
                    if rest[cut].startswith("discussions:"):
                        rest = rest[:cut]
                        break
                body = "\n".join(rest)
                if body.strip() == "(empty body)":
                    body = ""
                break
    if not page_id or body is None or not title:
        return False
    if fold(title) == fold(names_map["tasks"]["source"]):
        kind = "task"
    elif fold(title) == fold(names_map["projects"]["source"]):
        kind = "project"
    else:
        return False
    zone_text = card_request(kind, body, names_map)
    if zone_text is None or not request_reaches_its_end(kind, body_lines(body), names_map) \
            or read_pin(page_id) is not None:
        return False
    write_pin(page_id, digest(zone_text))
    return True


# ---------------------------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------------------------


class Findings:
    def __init__(self):
        self.items = []

    def add(self, rule, message, fix):
        self.items.append({"rule": rule, "message": message.rstrip("."), "fix": fix})


def request_lines(card):
    """The line indexes that hold the words of who asked, which no rule rewrites: the request zone of
    a task, the request toggle of a project, and on a form ticket the form's own sections (every
    line above `## Fechamento`, the whole body when there is none)."""
    if card.kind == "form":
        closing = h2_index(card.lines, "Fechamento")
        return range(len(card.lines) if closing is None else closing)
    if card.kind == "project":
        wanted = fold(card.names["projects"]["toggles"]["request"])
        spans = [range(first, end) for title, _, first, end in toggle_spans(card.lines) if fold(title) == wanted]
        return spans[0] if spans else range(0)
    span = request_span(card.lines)
    return range(*span) if span else range(0)


def status_rule(card, found):
    name = card.names["tasks"]["properties"]["status"]
    wanted = fold(name) + ":"
    theirs = request_lines(card)
    for index, line in enumerate(card.lines):
        if not line.strip() or heading(line) or index in theirs:
            continue
        if fold(line).startswith(wanted):
            found.add("status-in-body", f"the body states the status in the line '{quote(plain(line))}'",
                      f"Delete that line: the '{name}' property is where the status lives")
            return


def request_rule(card, found):
    text = card_request(card.kind, card.markdown, card.names)
    if text is None:
        return
    value = digest(text)
    pinned = read_pin(card.id)
    if pinned is None:
        write_pin(card.id, value)
    elif pinned != value:
        where = "the request toggle" if card.kind == "project" else "`## Pedido`"
        found.add("request-changed",
                  f"{where} no longer holds the text pinned when the card was first read; it holds the words "
                  "of who asked and is restored, not rewritten",
                  f"Put the request back as it was; when who asked changed it, run "
                  f"`card_contract.py accept-request {card.ref}`")


def rank_of(card):
    value = prop(card.page, card.names["tasks"]["properties"]["status"])
    if not value:
        return 0
    best = 0
    for role, rank in RANKS.items():
        if fold(card.names["status"][role]) == fold(value):
            best = max(best, rank)
    return best


def delivery_rules(card, found):
    lines = card.lines
    pedido, entrega = h2_index(lines, "Pedido"), h2_index(lines, "Entrega")
    if pedido is None:
        found.add("request-zone", "the card has no `## Pedido` zone",
                  "Put the request as it arrived, in the words of who asked, under `## Pedido` at the top")
    if entrega is None:
        found.add("delivery-zone", "the card has no `## Entrega` zone",
                  "Write `## Entrega` after `## Pedido` with the labels of `card_contract.py skeleton task`")
    elif pedido is not None and entrega < pedido:
        found.add("delivery-zone", "`## Entrega` is above `## Pedido`",
                  "Move `## Entrega` below the request: the card reads `## Pedido`, `## Entrega`, `## Fechamento`")
    delivery = zone(lines, entrega) if entrega is not None else []
    objective = label_line(delivery, "Objetivo")
    if objective is None or not objective[1]:
        found.add("objective", "`**Objetivo:**` is missing from `## Entrega` or has no text after it",
                  "Write `**Objetivo:** <one sentence>` as the first line of `## Entrega`")
    done_when = label_line(delivery, "Pronto quando")
    low, high = limits()["done_when"]
    if done_when is None:
        found.add("done-when", "`**Pronto quando:**` is missing from `## Entrega`",
                  f"Write `**Pronto quando:**` followed by {low} to {high} list items someone can observe")
    else:
        count = items_after(delivery, done_when[0])
        if not low <= count <= high:
            found.add("done-when", f"`**Pronto quando:**` has {count} list items, not {low} to {high}",
                      f"Keep {low} to {high} criteria someone can observe; a larger delivery is another card")


def people_rules(card, found):
    props = card.names["tasks"]["properties"]
    for role in ("assignee", "requester", "type"):
        if not filled(prop(card.page, props[role])):
            found.add("people" if role != "type" else "type", f"the property '{props[role]}' is empty",
                      f"Set it: `notion update {card.ref} --set '{props[role]}=<value>'`")


def pr_line(card):
    """(names a pull request?, the line) for the card's kind: `**PRs:**` on a task, `PR: #<n>` on a form."""
    if card.kind == "form":
        for line in card.lines:
            text = plain(line)
            if re.match(r"^PR:\s*\[?#\d+", text):
                return True, text
        return False, None
    found = label_line(card.lines, "PRs")
    if found is None:
        return False, None
    return bool(re.search(r"#\d+", found[1])), "PRs: " + found[1]


def summary_rule(card, found):
    name = card.names["tasks"]["properties"]["summary"]
    value = prop(card.page, name) or ""
    most = limits()["summary_characters"]
    if not value.strip():
        found.add("summary", f"the property '{name}' is empty",
                  f"Write one sentence of at most {most} characters: what changed for who asked")
    elif "\n" in value.strip():
        found.add("summary", f"the property '{name}' holds a line break ('{quote(value)}')",
                  f"Keep it one sentence on one line, at most {most} characters")
    elif len(value.strip()) > most:
        found.add("summary", f"the property '{name}' has {len(value.strip())} characters, more than {most}",
                  f"Shorten it to one sentence of at most {most} characters")


def pr_link_rule(card, found):
    name = card.names["tasks"]["properties"]["pull_request"]
    has_property = filled(prop(card.page, name))
    names_one, line = pr_line(card)
    form = card.kind == "form"
    shape = "`PR: #<n>`" if form else "`**PRs:** <repository> #<n>`"
    if names_one and not has_property:
        found.add("pr-link", f"the body names a pull request ('{quote(line)}') but '{name}' is empty",
                  f"Set '{name}' to the url of the first pull request")
    elif has_property and not names_one:
        found.add("pr-link", f"'{name}' is filled but the body names no pull request",
                  f"Add the line {shape} " + ("after `## Fechamento`" if form else "to `## Entrega`"))


def pull_request_properties(card, found, rank):
    name = card.names["tasks"]["properties"]["pull_request"]
    if rank == RANKS["pull_request_open"] and not filled(prop(card.page, name)):
        found.add("pr-property", f"the card is in the pull request open status and '{name}' is empty",
                  f"Set '{name}' to the url of the pull request")
    if rank >= RANKS["pull_request_open"]:
        summary_rule(card, found)


def closing_rule(card, found, rank):
    if rank >= RANKS["merged"] and filled(prop(card.page, card.names["tasks"]["properties"]["pull_request"])):
        start = h2_index(card.lines, "Fechamento")
        low, high = limits()["closing"]
        if start is None:
            found.add("closing", "the card has a pull request and no `## Fechamento`",
                      f"Write `## Fechamento` with {low} to {high} items: what changed for who asked, and "
                      "`Fora do código:` for what depends on someone outside the code")
        else:
            count = top_items(zone(card.lines, start))
            if not low <= count <= high:
                found.add("closing", f"`## Fechamento` has {count} list items, not {low} to {high}",
                          f"Keep {low} to {high} items: what changed for who asked, and `Fora do código:`")


def project_rules(card, found):
    titles = card.names["projects"]["toggles"]
    present = {fold(title): children for title, children in toggles(card.lines)}
    for role in ("request", "current"):
        if fold(titles[role]) not in present:
            found.add("project-toggle", f"the page has no toggle '{titles[role]}'",
                      "Keep the three toggles of the project template; "
                      + ("the request goes in it as it arrived" if role == "request"
                         else "the project as it stands goes in it, per `card_contract.py skeleton project`"))
    children = present.get(fold(titles["current"]))
    if not children or not any(line.strip() for line in children):
        return
    seen = []
    for index, line in enumerate(children):
        found_heading = heading(line)
        if found_heading:
            seen.append((fold(found_heading[1]), index))
    order = {fold(h): position for position, h in enumerate(PROJECT_HEADINGS)}
    keys = [key for key, _ in seen]
    for wanted in PROJECT_REQUIRED:
        if fold(wanted) not in keys:
            found.add("project-headings", f"'{titles['current']}' has no `### {wanted}`",
                      f"Write `### {wanted}` in '{titles['current']}', in the order of `card_contract.py skeleton project`")
    ranks = [order[key] for key in keys if key in order]
    if ranks != sorted(ranks):
        found.add("project-order", f"the sub-headings of '{titles['current']}' are out of order",
                  "Order them " + ", ".join(f"`{h}`" for h in PROJECT_HEADINGS))
    scope = next((index for key, index in seen if key == fold(SCOPE_HEADING)), None)
    if scope is None:
        return
    for line in children[scope + 1 :]:
        if heading(line):
            break
        bare = INLINE_TAG.sub(lambda m: m.group(0) if BOLD_TAG.match(m.group(0)) else "", line.strip())
        if line.strip() and not BOLD_DATE.match(ESCAPE.sub(r"\1", html.unescape(bare))):
            found.add("scope-log", f"the scope line '{quote(plain(line))}' does not start with a bold date",
                      "Write it as `- **dd/mm** · Entrou: <...>. Saiu: <...>. <who decided>. CES de <x> para <y>.`")


def judge(card):
    """The findings of a card. Of one whose body was not read whole, those of its properties only: a
    zone, a label or a toggle that is not in the part read may be in the rest."""
    found = Findings()
    if card.whole:
        status_rule(card, found)
        request_rule(card, found)
    if card.kind == "project":
        if card.whole:
            project_rules(card, found)
        return found.items
    rank = rank_of(card)
    if rank >= RANKS["in_progress"] and card.kind == "task":
        if card.whole:
            delivery_rules(card, found)
        people_rules(card, found)
    if rank >= RANKS["pull_request_open"]:
        if card.whole:
            pr_link_rule(card, found)
        pull_request_properties(card, found, rank)
        if card.whole:
            closing_rule(card, found, rank)
    return found.items


# ---------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------


def lines_of(items):
    """One line per finding, at most BUDGET characters in all; the rest is counted, not dropped silently."""
    out, used = [], 0
    for position, item in enumerate(items):
        line = f"{item['rule']}: {item['message']}. {item['fix']}"
        rest = len(items) - position - 1
        tail = len(f"more: {rest + 1} more findings; fix these and run the check again") + 1
        if used + len(line) + 1 + (tail if rest else 0) > BUDGET:
            out.append(f"more: {len(items) - position} more findings; fix these and run the check again")
            break
        out.append(line)
        used += len(line) + 1
    return out


def load_card(ref):
    names_map = names(settings())
    fetched = fetch(ref)
    if fetched.get("object") == "data_source" or not isinstance(fetched.get("page"), dict):
        return None
    card = Card(ref, fetched, names_map)
    card.kind = classify(card)
    return card


def say_not_whole(card):
    print(f"the body of {card.ref} was too long to read whole: only its properties are judged, and no request is "
          "pinned or compared", file=sys.stderr)


def cmd_check(args):
    card = load_card(args.ref)
    if args.page_id and card is not None and card.id:
        print(f"page: {card.id} {card.key}".rstrip())
    if card is None or card.kind is None:
        items = []
    elif not (args.body_replaced or any(card.named_by(ref) for ref in args.body_replaced_of)) \
            and (before_since(card) or someone_elses(card)):
        items = []
    else:
        if not card.whole:
            say_not_whole(card)
        items = judge(card)
    if args.json:
        kept = lines_of(items)
        print(json.dumps(items[: len([k for k in kept if not k.startswith("more: ")])], ensure_ascii=False, indent=2))
    else:
        for line in lines_of(items):
            print(line)
    return FINDINGS if items else CLEAN


def cmd_accept(args):
    card = load_card(args.ref)
    if card is not None and card.kind is not None and not card.whole:
        say_not_whole(card)
        print(f"{args.ref} was not read whole; nothing was pinned")
        return CLEAN
    text = None if card is None or card.kind is None else card_request(card.kind, card.markdown, card.names)
    if text is None:
        print(f"{args.ref} has no request zone; nothing was pinned")
        return CLEAN
    write_pin(card.id, digest(text))
    print(f"pinned the request zone of {args.ref} as it stands")
    return CLEAN


def cmd_skeleton(args):
    if args.kind not in KINDS:
        raise Stop(USAGE, f"unknown kind {args.kind!r}; the kinds are {', '.join(KINDS)}")
    sys.stdout.write(data()["skeletons"][args.kind]["text"])
    return CLEAN


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Stop(USAGE, f"{self.prog}: {message}")


def build_parser():
    parser = Parser(prog="card_contract.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="verb", required=True, parser_class=Parser)
    check = sub.add_parser("check", help="judge a card against the contract")
    check.add_argument("ref")
    check.add_argument("--body-replaced", action="store_true", help="the write replaced the whole body")
    check.add_argument("--json", action="store_true", help="the findings as a list of {rule, message, fix}")
    # for the card-check hook: the first line is the id and the key of the page read, so one page named
    # by its key, its url and its id is one page; and a page the call replaced, whichever page is read
    check.add_argument("--page-id", action="store_true", help=argparse.SUPPRESS)
    check.add_argument("--body-replaced-of", action="append", default=[], metavar="REF", help=argparse.SUPPRESS)
    check.set_defaults(func=cmd_check)
    accept = sub.add_parser("accept-request", help="pin the request zone as it now stands")
    accept.add_argument("ref")
    accept.set_defaults(func=cmd_accept)
    skeleton = sub.add_parser("skeleton", help="print the skeleton of a kind of card")
    skeleton.add_argument("kind", metavar="kind", help=" | ".join(KINDS))
    skeleton.set_defaults(func=cmd_skeleton)
    return parser


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except Stop as stop:
        if stop.message:
            print(stop.message, file=sys.stderr)
        return stop.code


if __name__ == "__main__":
    sys.exit(main())
