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
import contextlib
import copy
import datetime
import hashlib
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
FORMAT_TAGS = re.compile(r"</?(?:b|strong|i|em|u|s|code)>", re.I)


def plain(text):
    """The words of a markdown line with inline formatting dropped: `**x**`, `__x__`, `<b>x</b>`,
    `<strong>`, italics, inline code and backslash escapes all read as the bare text, so a card read
    back from Notion (bold as `<b>`, `_` as `\\_`) compares equal to the form it was written in."""
    kept = []

    def hold(match):
        kept.append(match.group(1))
        return f"\x00{len(kept) - 1}\x00"

    text = ESCAPE.sub(hold, text)
    text = FORMAT_TAGS.sub("", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)
    return text.replace("️", "").strip()


def fold(text):
    return " ".join(unicodedata.normalize("NFC", plain(text)).casefold().split())


def digest(text):
    words = " ".join(plain(line) for line in text.splitlines()).split()
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()


def quote(text):
    text = " ".join(text.split())
    return text if len(text) <= QUOTE else text[: QUOTE - 3] + "..."


# ---------------------------------------------------------------------------------------------
# The body
# ---------------------------------------------------------------------------------------------

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_ITEM = re.compile(r"^(?:[-*+]|\d+[.)])\s+\S")
BOLD_DATE = re.compile(
    r"^(?:[-*+]\s+)?(?:\*\*|__|<b>|<strong>)\s*\d{1,2}/\d{1,2}\s*(?:\*\*|__|</b>|</strong>)\s*·\s", re.I
)


def body_lines(markdown):
    """The body's lines with fenced code blanked out, so nothing inside a fence is a heading."""
    out, fence = [], None
    for line in (markdown or "").splitlines():
        marker = line.lstrip()[:3]
        if marker in ("```", "~~~"):
            fence = None if fence == marker else (fence or marker)
            out.append("")
            continue
        out.append("" if fence else line)
    return out


def heading(line, level=None):
    """(level, plain title) of a markdown heading line, or None."""
    match = HEADING.match(line.strip())
    if not match:
        return None
    if level is not None and len(match.group(1)) != level:
        return None
    return len(match.group(1)), plain(match.group(2))


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


def request_zone(lines):
    """The text from `## Pedido` to `## Entrega` (or to `## Fechamento`, or the end), or None."""
    start = h2_index(lines, "Pedido")
    if start is None:
        return None
    end = len(lines)
    for title in ("Entrega", "Fechamento"):
        index = h2_index(lines, title)
        if index is not None and index > start:
            end = min(end, index)
    return "\n".join(lines[start + 1 : end])


TOGGLE_OPEN = re.compile(r"^<toggle(?:\s[^>]*)?>$")


def toggles(lines):
    """[(title, child lines)] of the toggles at the top of the body."""
    found, index = [], 0
    while index < len(lines):
        if not TOGGLE_OPEN.match(lines[index].strip()):
            index += 1
            continue
        depth, title, children, cursor = 1, None, [], index + 1
        while cursor < len(lines) and depth:
            line = lines[cursor]
            stripped = line.strip()
            if TOGGLE_OPEN.match(stripped):
                depth += 1
            elif stripped == "</toggle>":
                depth -= 1
                if not depth:
                    break
            if title is None and stripped:
                title = re.sub(r"^#{1,6}\s+", "", stripped)
            elif title is not None:
                children.append(line)
            cursor += 1
        found.append((plain(re.sub(r"<[^>]+>", "", title or "")), children))
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
        self.markdown = ((fetched.get("markdown") or {}).get("markdown")) or ""
        self.names = names_map
        self.lines = body_lines(self.markdown)
        self.kind = None

    @property
    def id(self):
        return self.page.get("id", "")


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


def card_request(kind, lines, names_map):
    """The request zone's text of a card of this kind, or None when it has none."""
    if kind == "task":
        return request_zone(lines)
    if kind == "project":
        wanted = fold(names_map["projects"]["toggles"]["request"])
        for title, children in toggles(lines):
            if fold(title) == wanted:
                return "\n".join(children)
    return None


def pin_from_fetch_output(text):
    """Pin the request zone from the output of `notion fetch` (text or --json) with no call to
    Notion: used by the card-check hook after a fetch. Returns True when a new pin was stored."""
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
        body = ((fetched.get("markdown") or {}).get("markdown")) if fetched.get("markdown") else None
    else:
        lines = text.splitlines()
        title = None
        for index, line in enumerate(lines):
            if line.startswith("id: ") and page_id is None:
                page_id = line[4:].strip()
            elif line.startswith("parent: data source ") and title is None:
                title = re.sub(r"\s*\([^()]*\)\s*$", "", line[len("parent: data source "):]).strip()
            elif line == "body:":
                rest = lines[index + 1 :]
                while rest and (rest[-1].startswith("(truncated: ") or not rest[-1].strip()):
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
    zone_text = card_request(kind, body_lines(body), names_map)
    if zone_text is None or read_pin(page_id) is not None:
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


def status_rule(card, found):
    name = card.names["tasks"]["properties"]["status"]
    wanted = fold(name) + ":"
    for line in card.lines:
        if not line.strip() or heading(line):
            continue
        if fold(line).startswith(wanted):
            found.add("status-in-body", f"the body states the status in the line '{quote(plain(line))}'",
                      f"Delete that line: the '{name}' property is where the status lives")
            return


def request_rule(card, found):
    text = card_request(card.kind, card.lines, card.names)
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
    props = card.names["tasks"]["properties"]
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


def pull_request_rules(card, found, rank):
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
    if rank == RANKS["pull_request_open"] and not has_property:
        found.add("pr-property", f"the card is in the pull request open status and '{name}' is empty",
                  f"Set '{name}' to the url of the pull request")
    if rank >= RANKS["pull_request_open"]:
        summary_rule(card, found)
    if rank >= RANKS["merged"] and has_property:
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
        if line.strip() and not BOLD_DATE.match(ESCAPE.sub(r"\1", line.strip())):
            found.add("scope-log", f"the scope line '{quote(plain(line))}' does not start with a bold date",
                      "Write it as `- **dd/mm** · Entrou: <...>. Saiu: <...>. <who decided>. CES de <x> para <y>.`")


def judge(card):
    found = Findings()
    status_rule(card, found)
    request_rule(card, found)
    if card.kind == "project":
        project_rules(card, found)
        return found.items
    rank = rank_of(card)
    if rank >= RANKS["in_progress"] and card.kind == "task":
        delivery_rules(card, found)
    if rank >= RANKS["pull_request_open"]:
        pull_request_rules(card, found, rank)
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


def cmd_check(args):
    card = load_card(args.ref)
    if card is None or card.kind is None:
        items = []
    elif not args.body_replaced and (before_since(card) or someone_elses(card)):
        items = []
    else:
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
    text = None if card is None or card.kind is None else card_request(card.kind, card.lines, card.names)
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
