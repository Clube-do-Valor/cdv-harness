"""The cdv-notion client (skills/cdv-notion/scripts/notion) against a fake Notion, and the skill text.

The client is loaded as a module and its HTTP transport is replaced by FakeNotion, which answers
from synthetic objects written from the shapes of the official API reference. Nothing here is
copied from a real workspace: ids are made up, people are "Ana Lima" and "Bruno Costa", and ticket
keys and data source references are built at runtime so the public scan never sees one."""

import collections
import contextlib
import datetime
import http.client
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import random
import re
import shlex
import shutil
import socket
import ssl
import stat
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from helpers import REPO_ROOT

CLIENT = REPO_ROOT / "skills" / "cdv-notion" / "scripts" / "notion"
SKILL_DIR = REPO_ROOT / "skills" / "cdv-notion"

PREFIX = "ABC"
COLLECTION = "collec" + "tion://"
TOKEN = "ntn_" + "Synthetic0Token1Value2" * 2
API = "https://api.notion.com"


def uid(n):
    return f"{n:08x}-0000-4000-8000-{n:012x}"


def hex32(identifier):
    return identifier.replace("-", "")


def key(number, prefix=PREFIX):
    return prefix + "-" + str(number)


def page_url(identifier):
    return "https://app.notion.com/p/" + hex32(identifier)


BOT = uid(0xB07)
ANA, BRUNO, JOANA = uid(0xA1), uid(0xA2), uid(0xA3)
DB_TASKS, DS_TASKS = uid(0xD1), uid(0xD51)
DB_PROJECTS, DS_PROJECTS = uid(0xD2), uid(0xD52)
PAGE = uid(0x120)
PROJECT = uid(0x9001)
WIKI = uid(0x7001)


def text(value):
    return [{"type": "text", "text": {"content": value}, "plain_text": value, "annotations": {}, "href": None}]


def run(value, url=None, kind="text", **annotations):
    """One rich text run as the API reads it back: the link in text.link and in href, its formatting beside it."""
    marks = dict({"bold": False, "italic": False, "strikethrough": False, "underline": False, "code": False,
                  "color": "default"}, **annotations)
    if kind != "text":
        return {"type": kind, kind: {"type": "page", "page": {"id": uid(0x9001)}}, "annotations": marks,
                "plain_text": value, "href": url}
    return {"type": "text", "text": {"content": value, "link": {"url": url} if url else None},
            "annotations": marks, "plain_text": value, "href": url}


def comment_runs(markdown):
    """A comment's markdown as the API stores it: each [text](address) a linked run, the rest plain runs."""
    runs, at = [], 0
    for found in re.finditer(r"\[([^\[\]]+)\]\((https?://[^\s()]+)\)", markdown):
        runs += text(markdown[at:found.start()]) if found.start() > at else []
        runs.append(run(found.group(1), found.group(2)))
        at = found.end()
    return runs + (text(markdown[at:]) if at < len(markdown) else []) or text(markdown)


def person(identifier, name, email=None):
    found = {"object": "user", "id": identifier, "type": "person", "name": name, "avatar_url": None}
    if email:
        found["person"] = {"email": email}
    return found


USERS = {
    ANA: person(ANA, "Ana Lima", "ana@example.com"),
    BRUNO: person(BRUNO, "Bruno Costa", "bruno@example.com"),
}
GUEST = person(JOANA, "Joana Araújo")


def option(name, n):
    return {"id": f"o{n}", "name": name, "color": "default"}


def tasks_schema():
    return {
        "Task name": {"id": "title", "name": "Task name", "type": "title", "title": {}},
        "Task ID": {"id": "tid", "name": "Task ID", "type": "unique_id", "unique_id": {"prefix": PREFIX}},
        "Status": {
            "id": "st",
            "name": "Status",
            "type": "status",
            "status": {
                "options": [option(n, i) for i, n in enumerate(["Not started", "In progress", "Rollout", "Done"])],
                "groups": [],
            },
        },
        "Tags": {
            "id": "tg",
            "name": "Tags",
            "type": "multi_select",
            "multi_select": {"options": [option(n, i) for i, n in enumerate(["Backend", "Helpdesk", "Frontend"])]},
        },
        "Done at": {"id": "da", "name": "Done at", "type": "date", "date": {}},
        "Assignee": {"id": "as", "name": "Assignee", "type": "people", "people": {}},
        "Project": {
            "id": "pj",
            "name": "Project",
            "type": "relation",
            "relation": {"data_source_id": DS_PROJECTS, "type": "single_property", "single_property": {}},
        },
        "Completed?": {"id": "cp", "name": "Completed?", "type": "checkbox", "checkbox": {}},
        "Notes": {"id": "nt", "name": "Notes", "type": "rich_text", "rich_text": {}},
        "Pull Request": {"id": "pr", "name": "Pull Request", "type": "url", "url": {}},
        "Estimate": {"id": "es", "name": "Estimate", "type": "number", "number": {"format": "number"}},
        "Created time": {"id": "ct", "name": "Created time", "type": "created_time", "created_time": {}},
    }


def projects_schema():
    return {
        "Project name": {"id": "title", "name": "Project name", "type": "title", "title": {}},
        "Project ID": {"id": "pid", "name": "Project ID", "type": "unique_id", "unique_id": {"prefix": "PRJ"}},
    }


def data_source(identifier, title, properties, database):
    return {
        "object": "data_source",
        "id": identifier,
        "title": text(title),
        "parent": {"type": "database_id", "database_id": database},
        "properties": properties,
        "in_trash": False,
    }


def task_page(identifier, number, name, status="Done", tags=(), assignee=(), project=(), done_at=None,
              completed=False, notes="", created_by=BOT, created_time="2026-11-20T10:00:00.000Z"):
    properties = {
        "Task name": {"id": "title", "type": "title", "title": text(name)},
        "Task ID": {"id": "tid", "type": "unique_id", "unique_id": {"prefix": PREFIX, "number": number}},
        "Status": {"id": "st", "type": "status", "status": {"id": "s", "name": status, "color": "default"} if status else None},
        "Tags": {"id": "tg", "type": "multi_select", "multi_select": [{"id": "t", "name": t, "color": "default"} for t in tags]},
        "Done at": {"id": "da", "type": "date", "date": {"start": done_at, "end": None, "time_zone": None} if done_at else None},
        "Assignee": {"id": "as", "type": "people", "people": list(assignee)},
        "Project": {"id": "pj", "type": "relation", "relation": [{"id": p} for p in project], "has_more": False},
        "Completed?": {"id": "cp", "type": "checkbox", "checkbox": completed},
        "Notes": {"id": "nt", "type": "rich_text", "rich_text": text(notes) if notes else []},
        "Pull Request": {"id": "pr", "type": "url", "url": None},
        "Estimate": {"id": "es", "type": "number", "number": None},
        "Created time": {"id": "ct", "type": "created_time", "created_time": created_time},
    }
    return {
        "object": "page",
        "id": identifier,
        "url": "https://www.notion.so/" + name.replace(" ", "-") + "-" + hex32(identifier),
        "parent": {"type": "data_source_id", "data_source_id": DS_TASKS, "database_id": DB_TASKS},
        "in_trash": False,
        "icon": None,
        "created_time": created_time,
        "created_by": {"object": "user", "id": created_by},
        "properties": properties,
    }


def child_page(identifier, title, parent):
    return {
        "object": "page",
        "id": identifier,
        "url": "https://www.notion.so/" + title.replace(" ", "-") + "-" + hex32(identifier),
        "parent": {"type": "page_id", "page_id": parent},
        "in_trash": False,
        "icon": None,
        "created_time": "2026-11-20T10:00:00.000Z",
        "created_by": {"object": "user", "id": BOT},
        "properties": {"title": {"id": "title", "type": "title", "title": text(title)}},
    }


def error(status, code, message):
    return status, {"object": "error", "status": status, "code": code, "message": message}


class Request:
    def __init__(self, method, url, headers, body):
        parts = urlsplit(url)
        self.method = method
        self.url = url
        self.host = parts.netloc
        self.path = parts.path
        self.query = parse_qs(parts.query)
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.raw = body or b""
        self.json = None
        if body and self.headers.get("content-type", "").startswith("application/json"):
            self.json = json.loads(body)


class FakeNotion:
    """A small stateful Notion: pages, markdown bodies, data sources, users, comments, uploads."""

    def __init__(self):
        self.calls = []
        self.overrides = []
        self.me = {"object": "user", "id": BOT, "type": "bot", "name": "Card bot",
                   "bot": {"owner": {"type": "workspace", "workspace": True}, "workspace_name": "Example"}}
        self.users = dict(USERS)
        self.users_status = 200
        self.data_sources = {
            DS_TASKS: data_source(DS_TASKS, "Tasks", tasks_schema(), DB_TASKS),
            DS_PROJECTS: data_source(DS_PROJECTS, "Projects", projects_schema(), DB_PROJECTS),
        }
        self.databases = {
            DB_TASKS: {"object": "database", "id": DB_TASKS, "title": text("Tasks"), "data_sources": [{"id": DS_TASKS, "name": "Tasks"}]},
            DB_PROJECTS: {"object": "database", "id": DB_PROJECTS, "title": text("Projects"), "data_sources": [{"id": DS_PROJECTS, "name": "Projects"}]},
        }
        self.pages = {}
        self.markdown = {}
        self.comments = {}
        self.property_items = {}
        self.blocks = {}
        self.children = {}  # page or block id -> the blocks under it, as the block endpoints give them
        self.page_of = {}  # block id -> the page it was stored on
        self.files = {}
        self.next_number = 200
        self.next_id = 0x5000
        self.now = "2026-11-22T09:30:00.000Z"  # created_time of new pages, to the minute as Notion stores it

    # -- plumbing -------------------------------------------------------------------------

    def on(self, method, pattern, handler):
        self.overrides.insert(0, (method, re.compile(pattern), handler))

    def __call__(self, method, url, headers, body=None, timeout=None):
        request = Request(method, url, headers, body)
        self.calls.append(request)
        for wanted, pattern, handler in self.overrides:
            if wanted == method and pattern.fullmatch(request.path):
                answer = handler(request)
                if answer is not None:
                    return self.encode(answer)
        return self.encode(self.route(request))

    @staticmethod
    def encode(answer):
        status, payload = answer[0], answer[1]
        headers = answer[2] if len(answer) > 2 else {}
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return status, headers, data

    def sent(self, method, pattern):
        regex = re.compile(pattern)
        return [c for c in self.calls if c.method == method and regex.fullmatch(c.path)]

    def add_page(self, page, markdown=""):
        self.pages[page["id"]] = page
        self.markdown[page["id"]] = markdown
        return page

    def new_id(self):
        self.next_id += 1
        return uid(self.next_id)

    # -- the routes -----------------------------------------------------------------------

    def route(self, r):
        if r.host != "api.notion.com":
            if r.url in self.files:
                return 200, self.files[r.url]
            return 404, b"not found"
        p, m = r.path, r.method
        if m == "GET" and p == "/v1/users/me":
            return 200, self.me
        if m == "GET" and p == "/v1/users":
            if self.users_status != 200:
                return error(self.users_status, "restricted_resource", "Insufficient permissions for this endpoint.")
            return 200, {"object": "list", "results": list(self.users.values()), "has_more": False, "next_cursor": None}
        if m == "GET" and re.fullmatch(r"/v1/users/[^/]+", p):
            found = self.users.get(p.rsplit("/", 1)[1])
            return (200, found) if found else error(404, "object_not_found", "Could not find user.")
        if m == "POST" and p == "/v1/search":
            return 200, self.search(r.json or {})
        match = re.fullmatch(r"/v1/pages/([^/]+)", p)
        if match and m == "GET":
            found = self.pages.get(match.group(1))
            return (200, found) if found else error(404, "object_not_found", f"Could not find page with ID: {match.group(1)}.")
        if match and m == "PATCH":
            return self.patch_page(match.group(1), r.json or {})
        match = re.fullmatch(r"/v1/pages/([^/]+)/markdown", p)
        if match and m == "GET":
            if match.group(1) not in self.pages:
                return error(404, "object_not_found", "Could not find page.")
            return 200, self.page_markdown(match.group(1))
        if match and m == "PATCH":
            return self.patch_markdown(match.group(1), r.json or {})
        match = re.fullmatch(r"/v1/pages/([^/]+)/properties/([^/]+)", p)
        if match and m == "GET":
            return self.property_item(match.group(1), match.group(2), r)
        if m == "POST" and p == "/v1/pages":
            return self.create_page(r.json or {})
        match = re.fullmatch(r"/v1/data_sources/([^/]+)", p)
        if match and m == "GET":
            found = self.data_sources.get(match.group(1))
            return (200, found) if found else error(404, "object_not_found", "Could not find data source.")
        match = re.fullmatch(r"/v1/data_sources/([^/]+)/query", p)
        if match and m == "POST":
            if match.group(1) not in self.data_sources:
                return error(404, "object_not_found", "Could not find data source.")
            return 200, self.query(match.group(1), r.json or {})
        match = re.fullmatch(r"/v1/databases/([^/]+)", p)
        if match and m == "GET":
            found = self.databases.get(match.group(1))
            return (200, found) if found else error(404, "object_not_found", "Could not find database.")
        if m == "GET" and p == "/v1/comments":
            block = r.query.get("block_id", [""])[0]
            return 200, {"object": "list", "results": self.comments.get(block, []), "has_more": False, "next_cursor": None}
        match = re.fullmatch(r"/v1/comments/([^/]+)", p)
        if match and m == "GET":
            for thread in self.comments.values():
                for comment in thread:
                    if comment["id"] == match.group(1):
                        return 200, comment
            return error(404, "object_not_found", "Could not find comment.")
        if match and m == "PATCH":
            for thread in self.comments.values():
                for comment in thread:
                    if comment["id"] == match.group(1):
                        if comment["created_by"]["id"] != BOT:
                            return error(404, "object_not_found", "Could not find comment.")
                        comment["rich_text"] = comment_runs((r.json or {}).get("markdown", ""))
                        return 200, comment
            return error(404, "object_not_found", "Could not find comment.")
        if m == "POST" and p == "/v1/comments":
            return self.create_comment(r.json or {})
        if m == "POST" and p == "/v1/file_uploads":
            upload = self.new_id()
            return 200, {"object": "file_upload", "id": upload, "status": "pending",
                         "upload_url": f"{API}/v1/file_uploads/{upload}/send",
                         "filename": (r.json or {}).get("filename")}
        match = re.fullmatch(r"/v1/file_uploads/([^/]+)/send", p)
        if match and m == "POST":
            return 200, {"object": "file_upload", "id": match.group(1), "status": "uploaded"}
        match = re.fullmatch(r"/v1/blocks/([^/]+)/children", p)
        if match and m == "GET":
            return 200, {"object": "list", "results": self.children.get(match.group(1), []), "next_cursor": None,
                         "has_more": False, "type": "block", "block": {}}
        match = re.fullmatch(r"/v1/blocks/([^/]+)", p)
        if match and m == "PATCH":
            return self.patch_block(match.group(1), r.json or {})
        if match and m == "GET":
            found = self.blocks.get(match.group(1))
            return (200, found) if found else error(404, "object_not_found", "Could not find block.")
        return error(404, "object_not_found", f"fake: no route for {m} {p}")

    def search(self, body):
        wanted = (body.get("filter") or {}).get("value")
        if wanted == "data_source":
            results = [dict(ds) for ds in self.data_sources.values()]
        else:
            words = (body.get("query") or "").lower()
            results = [pg for pg in self.pages.values() if words in self.title_of(pg).lower() and not pg["in_trash"]]
        return {"object": "list", "results": results, "has_more": False, "next_cursor": None}

    @staticmethod
    def title_of(page):
        for value in page["properties"].values():
            if value["type"] == "title":
                return "".join(t["plain_text"] for t in value["title"])
        return ""

    def query(self, ds, body):
        rows = [pg for pg in self.pages.values()
                if pg["parent"].get("data_source_id") == ds and not pg["in_trash"]]
        rows = [pg for pg in rows if self.matches(pg, body.get("filter"))]
        start = int(body.get("start_cursor") or 0)
        size = int(body.get("page_size") or 100)
        chunk = rows[start:start + size]
        more = start + size < len(rows)
        return {"object": "list", "results": chunk, "has_more": more, "next_cursor": str(start + size) if more else None}

    def matches(self, page, condition):
        """Only what key lookups and duplicate checks need; any other condition matches every row."""
        if not condition:
            return True
        if "and" in condition:
            return all(self.matches(page, c) for c in condition["and"])
        if "or" in condition:
            return any(self.matches(page, c) for c in condition["or"])
        if "unique_id" in condition:
            value = page["properties"].get(condition["property"], {}).get("unique_id") or {}
            return value.get("number") == condition["unique_id"].get("equals")
        if "title" in condition and "equals" in condition["title"]:
            return self.title_of(page) == condition["title"]["equals"]
        return True

    def page_markdown(self, identifier):
        """A body as the markdown endpoint gives it back: a table whose only style is its header row comes back
        as a pipe table, whatever form it was written in."""
        def pipes(match):
            rows = [re.findall(r"<td>(.*?)</td>", row) for row in re.findall(r"<tr>(.*?)</tr>", match.group(1), re.S)]
            lines = ["| " + " | ".join(row) + " |" for row in rows]
            return "\n".join(lines[:1] + ["| " + " | ".join("---" for _ in rows[0]) + " |"] + lines[1:])
        body = re.sub(r'<table header-row="true">(.*?)</table>', pipes, self.markdown.get(identifier, ""), flags=re.S)
        return {"object": "page_markdown", "id": identifier, "markdown": body,
                "truncated": False, "unknown_block_ids": []}

    def block(self, kind, content, children=()):
        made = {"object": "block", "id": self.new_id(), "has_children": bool(children), "in_trash": False,
                "type": kind, kind: content}
        self.blocks[made["id"]] = made
        self.children[made["id"]] = list(children)
        return made

    def patch_block(self, identifier, body):
        """A media block given an uploaded file: it becomes a hosted file with a signed url, in the body too."""
        block = self.blocks[identifier]
        upload = body[block["type"]]["file_upload"]["id"]
        hosted = f"https://files.example.com/{upload}?X-Amz-Expires=3600"
        before = block[block["type"]].get("external", {}).get("url")
        block[block["type"]] = {"caption": block[block["type"]]["caption"], "type": "file",
                                "file": {"url": hosted, "expiry_time": "2026-11-22T10:30:00.000Z"}}
        page = self.page_of.get(identifier)
        if before and page:
            self.markdown[page] = self.markdown[page].replace(before, hosted, 1)
        return 200, block

    class Refused(Exception):
        """A body the markdown endpoints answer 400 to, as seen on the real API."""

    def store_blocks(self, identifier, markdown):
        """The blocks Notion stores for the constructs the tests write: callout, table, toggle, columns, quote, code,
        media, text. As the real API: a media address that is not http(s) is stored empty; an image that is not
        alone on its line and an attribute in single quotes are refused; a media tag in a sentence or a cell is text."""
        def paragraph(value):
            return self.block("paragraph", {"rich_text": text(value), "color": "default"})

        def plain_line(value):
            shown = re.sub(r"`[^`]*`", "", value)
            if re.search(r"(?<!\\)!\[[^\]]*\]\(", shown):
                raise self.Refused("Images must be standalone blocks and cannot be mixed with paragraph text or other images.")
            if re.search(r"^<\w+ [^>]*=\s*'", shown):
                raise self.Refused("Malformed attribute. Attribute values must use double quotes.")
            return value

        def line_of(value):
            value = value.strip()
            found = re.fullmatch(r"!\[((?:[^\[\]\\]|\\.|\[[^\]]*\])*)\]\(\s*<?([^\s<>]*)>?(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)", value)
            kind, caption, url = ("image", found.group(1), found.group(2)) if found else (None, "", "")
            tag = re.fullmatch(r'<(image|file|pdf|audio|video|bookmark|embed)\s(?:[^<>]*?\s)?(?:source|src)\s*=\s*"([^"]*)"[^<>]*?'
                               r"(?:/>|>([^<]*)</\1>)", value)
            if tag:
                kind, url, caption = tag.groups()
            if kind in ("bookmark", "embed"):
                return self.block(kind, {"caption": [], "url": url})
            if not kind:
                return paragraph(plain_line(value))
            if url.startswith("https://files.example.com/"):
                return self.block(kind, {"caption": text(caption or ""), "type": "file", "file": {"url": url}})
            return self.block(kind, {"caption": text(caption or ""), "type": "external",
                                     "external": {"url": url if url.startswith("http") else ""}})

        def inside(lines, at, tag):
            """(the lines between an opening tag's line and its closing one, the place after it)."""
            depth, inner = 1, []
            for place in range(at + 1, len(lines)):
                depth += bool(re.match(rf"\s*<{tag}[ >]", lines[place])) - lines[place].count(f"</{tag}>")
                if depth == 0:
                    return inner, place + 1
                inner.append(lines[place])
            raise self.Refused(f"Trailing unclosed tags were auto-closed: <{tag}>.")

        def blocks_of(lines):
            made, at = [], 0
            while at < len(lines):
                line = lines[at].strip()
                fence = re.match(r"(`{3,})[^`]*$|(~{3,})", line)
                if not line:
                    at += 1
                elif fence:
                    mark, code = fence.group(1) or fence.group(2), []
                    at += 1
                    while at < len(lines) and not (set(lines[at].strip()) == {mark[0]} and len(lines[at].strip()) >= len(mark)):
                        code.append(lines[at])
                        at += 1
                    at += 1
                    made.append(self.block("code", {"rich_text": text("\n".join(code)), "language": "plain text"}))
                elif line.startswith(">"):
                    quoted = []
                    while at < len(lines) and lines[at].strip().startswith(">"):
                        quoted.append(re.sub(r"^\s*> ?", "", lines[at]))
                        at += 1
                    made.append(self.block("quote", {"rich_text": [], "color": "default"}, blocks_of(quoted)))
                elif line.startswith("<table"):
                    inner, after = inside(lines, at, "table")
                    cells = [re.findall(r"<td>(.*?)</td>", row, re.S) for row in re.findall(r"<tr>(.*?)</tr>", "\n".join(inner), re.S)]
                    if any(re.search(r"!\[[^\]]*\]\(", cell) for row in cells for cell in row):
                        raise self.Refused("Inline image Markdown is not supported in rich text.")
                    rows = [self.block("table_row", {"cells": [text(c) for c in row]}) for row in cells]
                    made.append(self.block("table", {"table_width": len(cells[0]), "has_column_header": 'header-row="true"' in line,
                                                     "has_row_header": False}, rows))
                    at = after
                elif re.match(r"<(callout|toggle|columns|column)\b", line):
                    kind = re.match(r"<(\w+)", line).group(1)
                    inner, after = inside(lines, at, kind)
                    if kind in ("callout", "toggle"):
                        content = {"rich_text": text(inner[0] if inner else ""), "color": "default"}
                        if kind == "callout":
                            content.update(icon={"type": "emoji", "emoji": re.search(r'icon="([^"]+)"', line).group(1)}, color="gray_background")
                        made.append(self.block(kind, content, blocks_of(inner[1:])))
                    else:
                        made.append(self.block({"columns": "column_list"}.get(kind, kind), {}, blocks_of(inner)))
                    at = after
                else:
                    made.append(line_of(lines[at]))
                    at += 1
            return made

        def placed_on(blocks):
            for block in blocks:
                self.page_of[block["id"]] = identifier
                placed_on(self.children[block["id"]])

        stored = blocks_of(markdown.split("\n"))
        placed_on(stored)
        self.children[identifier] = stored

    def patch_markdown(self, identifier, body):
        if identifier not in self.pages:
            return error(404, "object_not_found", "Could not find page.")
        current = self.markdown.get(identifier, "")
        warnings = []
        kind = body.get("type")
        if kind == "update_content":
            matched = 0
            for pair in body["update_content"]["content_updates"]:
                if current.count(pair["old_str"]) == 1:
                    current = current.replace(pair["old_str"], pair["new_str"])
                    matched += 1
                else:
                    warnings.append({"code": "no_match", "message": "old_str did not match"})
            if not matched:
                return error(400, "validation_error", "No update_content edit matched.")
        elif kind == "replace_content":
            current = body["replace_content"]["new_str"]
        elif kind == "insert_content":
            content = body["insert_content"]["content"]
            position = (body["insert_content"].get("position") or {}).get("type", "end")
            current = content + "\n\n" + current if position == "start" else current + "\n\n" + content
        try:
            self.store_blocks(identifier, current)
        except self.Refused as refused:
            return error(400, "validation_error", f"Markdown errors blocked parsing:\n{refused}")
        self.markdown[identifier] = current
        answer = self.page_markdown(identifier)
        if warnings:
            answer["warnings"] = warnings
        return 200, answer

    def property_item(self, identifier, prop, r):
        items = self.property_items.get((identifier, prop))
        if items is None:
            return error(404, "object_not_found", "Could not find property.")
        start = int(r.query.get("start_cursor", ["0"])[0])
        size = 20
        chunk = items[start:start + size]
        more = start + size < len(items)
        return 200, {"object": "list", "type": "property_item",
                     "results": [{"object": "property_item", "id": prop, "type": "relation", "relation": {"id": i}} for i in chunk],
                     "has_more": more, "next_cursor": str(start + size) if more else None,
                     "property_item": {"id": prop, "type": "relation", "relation": {}, "next_url": None}}

    def stored(self, schema_type, written):
        """The read shape Notion answers with, for a write shape the client sent."""
        if schema_type in ("title", "rich_text"):
            return [run(part["text"]["content"], (part["text"].get("link") or {}).get("url")) for part in written[schema_type]]
        if schema_type in ("status", "select"):
            value = written[schema_type]
            return None if value is None else {"id": "x", "name": value["name"], "color": "default"}
        if schema_type == "multi_select":
            return [{"id": "x", "name": o["name"], "color": "default"} for o in written["multi_select"]]
        if schema_type == "date":
            value = written["date"]
            return None if value is None else {"start": value["start"], "end": value.get("end"), "time_zone": None}
        if schema_type == "people":
            return [self.users.get(u["id"], {"object": "user", "id": u["id"]}) for u in written["people"]]
        if schema_type == "relation":
            return [{"id": rel["id"]} for rel in written["relation"]]
        return written[schema_type]

    def schema_of(self, page):
        ds = page["parent"].get("data_source_id")
        return self.data_sources[ds]["properties"] if ds else {"title": {"id": "title", "type": "title"}}

    def patch_page(self, identifier, body):
        page = self.pages.get(identifier)
        if not page:
            return error(404, "object_not_found", f"Could not find page with ID: {identifier}.")
        schema = self.schema_of(page)
        for name, written in (body.get("properties") or {}).items():
            kind = schema[name]["type"]
            value = page["properties"].setdefault(name, {"id": schema[name]["id"], "type": kind})
            value[kind] = self.stored(kind, written)
            if kind == "relation":
                value["has_more"] = False
        if "in_trash" in body:
            page["in_trash"] = body["in_trash"]
        if "icon" in body:
            page["icon"] = body["icon"]
        return 200, page

    def create_page(self, body):
        parent = body["parent"]
        identifier = self.new_id()
        if "data_source_id" in parent:
            ds = parent["data_source_id"]
            schema = self.data_sources[ds]["properties"]
            page = task_page(identifier, self.next_number, "", status=None, created_time=self.now)
            page["parent"] = {"type": "data_source_id", "data_source_id": ds, "database_id": DB_TASKS}
            self.next_number += 1
            for name, written in (body.get("properties") or {}).items():
                kind = schema[name]["type"]
                page["properties"][name] = {"id": schema[name]["id"], "type": kind, kind: self.stored(kind, written)}
            title = self.title_of(page)
            page["url"] = "https://www.notion.so/" + title.replace(" ", "-") + "-" + hex32(identifier)
        else:
            title = "".join(t["text"]["content"] for t in body["properties"]["title"]["title"])
            page = child_page(identifier, title, parent["page_id"])
            page["created_time"] = self.now
        if body.get("icon"):
            page["icon"] = body["icon"]
        if body.get("markdown"):
            try:
                self.store_blocks(identifier, body["markdown"])
            except self.Refused as refused:
                return error(400, "validation_error", f"Markdown errors blocked parsing:\n{refused}")
        self.add_page(page, body.get("markdown", ""))
        return 200, page

    def create_comment(self, body):
        comment = {
            "object": "comment",
            "id": self.new_id(),
            "discussion_id": body.get("discussion_id") or self.new_id(),
            "parent": body.get("parent") or {"type": "page_id", "page_id": PAGE},
            "created_by": {"object": "user", "id": BOT},
            "rich_text": comment_runs(body.get("markdown", "")),
        }
        if body.get("display_name"):
            comment["display_name"] = {"type": body["display_name"]["type"],
                                       "resolved_name": (body["display_name"].get("custom") or {}).get("name", "Card bot")}
        target = (body.get("parent") or {}).get("page_id") or PAGE
        self.comments.setdefault(target, []).append(comment)
        return 200, comment


def load_client():
    loader = importlib.machinery.SourceFileLoader("cdv_notion_client", str(CLIENT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    writes = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # no __pycache__ beside the shipped client
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


class ClientTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="notion-test-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.home), "NOTION_API_TOKEN": TOKEN})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.n = load_client()
        self.fake = FakeNotion()
        self.n.TRANSPORT = self.fake
        self.sleeps = []
        self.n.SLEEP = self.sleeps.append
        self.n.NOW = lambda: datetime.datetime(2026, 11, 22, 9, 30, 15, tzinfo=datetime.timezone.utc)
        self.keyring_calls = []
        self.keyring = None  # None: no keyring on this machine; a string: the stored token
        self.n.secret_tool = self.fake_secret_tool
        self.n.git_email = lambda: ""
        self.page = self.fake.add_page(
            task_page(PAGE, 120, "Export invoices", status="Done", tags=["Backend"],
                      assignee=[USERS[ANA]], project=[PROJECT], done_at="2026-11-22", completed=True,
                      notes="Monthly export"),
            "## Context\n\nThe finance team exports invoices by hand.\n",
        )
        self.fake.add_page(child_page(PROJECT, "Billing revamp", WIKI))

    def fake_secret_tool(self, *args, stdin=None):
        self.keyring_calls.append((args, stdin))
        if self.keyring is None:
            return None
        if args[0] == "lookup":
            return mock.Mock(returncode=0 if self.keyring else 1, stdout=self.keyring or "")
        return mock.Mock(returncode=0, stdout="")

    def settings(self, **values):
        path = self.home / ".config" / "cdv-notion" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values))

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.n.main([str(a) for a in args])
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else 2
        return code, out.getvalue(), err.getvalue()

    def writes(self):
        return [c for c in self.fake.calls if c.method in ("POST", "PATCH", "DELETE")
                and c.path not in ("/v1/search",) and not c.path.endswith("/query")]

    def props_of(self, output):
        start = output.index("{")
        depth = 0
        for i, ch in enumerate(output[start:], start):
            depth += {"{": 1, "}": -1}.get(ch, 0)
            if depth == 0:
                return json.loads(output[start:i + 1])
        raise AssertionError("no properties object in output")


class FetchTest(ClientTestCase):
    def test_fetch_prints_page_for_every_reference_form(self):
        forms = [
            page_url(PAGE),
            hex32(PAGE),
            PAGE,
            "https://www.notion.so/example-team/Export-invoices-" + hex32(PAGE) + "?source=copy_link",
        ]
        outputs = []
        for form in forms:
            with self.subTest(form=form):
                code, out, err = self.run_cli("fetch", form)
                self.assertEqual(code, 0, err)
                self.assertIn("title: Export invoices", out)
                self.assertIn("url: " + self.page["url"], out)
                self.assertIn("parent: data source Tasks (" + COLLECTION + DS_TASKS + ")", out)
                props = self.props_of(out)
                self.assertEqual(props["Status"], "Done")
                self.assertEqual(props["Tags"], ["Backend"])
                self.assertEqual(props["Notes"], "Monthly export")
                self.assertIn("The finance team exports invoices by hand.", out)
                self.assertLess(out.index("properties:"), out.index("## Context"))
                outputs.append(out)
        self.assertEqual(len(set(outputs)), 1)

    def test_fetch_by_ticket_key_resolves_through_prefix(self):
        code, out, err = self.run_cli("fetch", key(120))
        self.assertEqual(code, 0, err)
        self.assertIn("title: Export invoices", out)
        self.assertIn("key: " + key(120), out)
        queries = self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")
        self.assertEqual(queries[-1].json["filter"], {"property": "Task ID", "unique_id": {"equals": 120}})
        self.assertEqual(self.fake.sent("POST", rf"/v1/data_sources/{DS_PROJECTS}/query"), [])

    def test_fetch_unknown_key_number_exits_1(self):
        code, out, err = self.run_cli("fetch", key(999999))
        self.assertEqual(code, 1)
        self.assertIn("no page with key " + key(999999), err)

    def test_fetch_unknown_prefix_exits_2_naming_prefixes(self):
        code, out, err = self.run_cli("fetch", "XYZ-1")
        self.assertEqual(code, 2)
        self.assertIn(PREFIX, err)
        self.assertIn("PRJ", err)

    def test_fetch_data_source_prints_short_schema(self):
        for form in (COLLECTION + DS_TASKS, DS_TASKS, hex32(DS_TASKS), "Tasks"):
            with self.subTest(form=form):
                code, out, err = self.run_cli("fetch", form)
                self.assertEqual(code, 0, err)
                self.assertIn("data source: Tasks", out)
                self.assertIn("key prefix: " + PREFIX, out)
                lines = {line.split(":", 1)[0].lstrip("- "): line for line in out.splitlines() if line.startswith("- ")}
                self.assertEqual(len(lines), 12)
                self.assertIn("status", lines["Status"])
                for name in ("Not started", "In progress", "Rollout", "Done"):
                    self.assertIn(name, lines["Status"])
                for name in ("Backend", "Helpdesk", "Frontend"):
                    self.assertIn(name, lines["Tags"])
                self.assertIn("multi_select", lines["Tags"])
                self.assertIn("relation", lines["Project"])
                self.assertIn("title", lines["Task name"])

    def test_fetch_48_property_schema_fits_6000_chars(self):
        properties = tasks_schema()
        properties["Tools"] = {"id": "tl", "name": "Tools", "type": "multi_select",
                               "multi_select": {"options": [option(f"Tool option {i:02d}", i) for i in range(59)]}}
        properties["Areas"] = {"id": "ar", "name": "Areas", "type": "multi_select",
                               "multi_select": {"options": [option(f"Area option {i:02d}", i) for i in range(41)]}}
        properties["Kind"] = {"id": "kd", "name": "Kind", "type": "select",
                              "select": {"options": [option(f"Kind {i}", i) for i in range(9)]}}
        n = 0
        while len(properties) < 48:
            n += 1
            properties[f"Extra field {n}"] = {"id": f"x{n}", "name": f"Extra field {n}", "type": "rich_text", "rich_text": {}}
        self.fake.data_sources[DS_TASKS]["properties"] = properties
        code, out, err = self.run_cli("fetch", COLLECTION + DS_TASKS)
        self.assertEqual(code, 0, err)
        self.assertLessEqual(len(out), 6000)
        for name in properties:
            self.assertIn("- " + name + ":", out)
        for name in ("Not started", "In progress", "Rollout", "Done"):
            self.assertIn(name, out)

    def test_fetch_database_id_prints_its_data_source(self):
        code, out, err = self.run_cli("fetch", page_url(DB_TASKS))
        self.assertEqual(code, 0, err)
        self.assertIn("data source: Tasks", out)
        self.assertIn(COLLECTION + DS_TASKS, out)

    def test_fetch_discussions_prints_id_author_and_text(self):
        discussion = uid(0xC0)
        self.fake.comments[PAGE] = [
            {"object": "comment", "id": uid(0xC1), "discussion_id": discussion, "created_by": {"object": "user", "id": ANA},
             "rich_text": text("Can we ship on Friday?")},
            {"object": "comment", "id": uid(0xC2), "discussion_id": discussion, "created_by": {"object": "user", "id": BOT},
             "rich_text": text("Yes, after the review."), "display_name": {"type": "custom", "resolved_name": "Bruno Costa"}},
        ]
        code, out, err = self.run_cli("fetch", page_url(PAGE), "--discussions")
        self.assertEqual(code, 0, err)
        after = out[out.index("The finance team exports"):]
        self.assertIn(discussion, after)
        self.assertRegex(after, r"Ana Lima: Can we ship on Friday\?")
        self.assertRegex(after, r"Bruno Costa: Yes, after the review\.")

    def test_fetch_403_and_404_exit_1_naming_the_id(self):
        missing = uid(0xDEAD)
        code, out, err = self.run_cli("fetch", hex32(missing))
        self.assertEqual(code, 1)
        self.assertIn(missing, err)
        self.assertIn("not connected", err)
        self.fake.on("GET", rf"/v1/pages/{PAGE}", lambda r: error(403, "restricted_resource", "Insufficient permissions."))
        code, out, err = self.run_cli("fetch", PAGE)
        self.assertEqual(code, 1)
        self.assertIn(PAGE, err)
        self.assertIn("not connected", err)

    def test_fetch_property_short_format(self):
        code, out, err = self.run_cli("fetch", PAGE, "--props-only")
        self.assertEqual(code, 0, err)
        props = self.props_of(out)
        self.assertEqual(props["date:Done at:start"], "2026-11-22")
        self.assertIsNone(props["date:Done at:end"])
        self.assertEqual(props["date:Done at:is_datetime"], 0)
        self.assertEqual(props["Assignee"], ["user://" + ANA + " (Ana Lima)"])
        self.assertEqual(props["Project"], [page_url(PROJECT)])
        self.assertEqual(props["Task ID"], key(120))
        self.assertEqual(props["Completed?"], "__YES__")
        self.assertNotIn("The finance team exports", out)

    def test_fetch_relation_over_25_reads_paged_endpoint(self):
        related = [uid(0x8000 + i) for i in range(30)]
        self.page["properties"]["Project"] = {"id": "pj", "type": "relation",
                                              "relation": [{"id": r} for r in related[:25]], "has_more": True}
        self.fake.property_items[(PAGE, "pj")] = related
        code, out, err = self.run_cli("fetch", PAGE)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.props_of(out)["Project"], [page_url(r) for r in related])
        self.assertTrue(self.fake.sent("GET", rf"/v1/pages/{PAGE}/properties/pj"))


class UpdateTest(ClientTestCase):
    def test_update_set_sends_each_type(self):
        self.settings(me="ana@example.com")
        self.page["properties"]["Assignee"]["people"] = []
        code, out, err = self.run_cli(
            "update", page_url(PAGE),
            "--set", "Status=Done",
            "--set", "Tags=Backend,Helpdesk",
            "--set", "date:Done at:start=2026-11-22",
            "--set", "Assignee=me",
            "--set", "Project=" + page_url(PROJECT),
            "--set", "Completed?=__YES__",
        )
        self.assertEqual(code, 0, err)
        patch = self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"]
        self.assertEqual(patch["Status"], {"status": {"name": "Done"}})
        self.assertEqual(patch["Tags"], {"multi_select": [{"name": "Backend"}, {"name": "Helpdesk"}]})
        self.assertEqual(patch["Done at"], {"date": {"start": "2026-11-22"}})
        self.assertEqual(patch["Assignee"], {"people": [{"id": ANA}]})
        self.assertEqual(patch["Project"], {"relation": [{"id": PROJECT}]})
        self.assertEqual(patch["Completed?"], {"checkbox": True})

    def test_update_date_start_keeps_the_end_of_a_range_and_an_empty_end_clears_it(self):
        self.page["properties"]["Done at"]["date"] = {"start": "2026-11-17", "end": "2026-11-28", "time_zone": None}
        code, out, err = self.run_cli("update", PAGE, "--set", "date:Done at:start=2026-11-24")
        self.assertEqual(code, 0, err)
        patch = self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"]
        self.assertEqual(patch["Done at"], {"date": {"start": "2026-11-24", "end": "2026-11-28"}})
        code, out, err = self.run_cli("update", PAGE, "--set", "date:Done at:end=")
        self.assertEqual(code, 0, err)
        patch = self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"]
        self.assertEqual(patch["Done at"], {"date": {"start": "2026-11-24"}})
        self.page["properties"]["Done at"]["date"] = {"start": "2026-11-17", "end": "2026-11-28", "time_zone": None}
        code, out, err = self.run_cli("update", PAGE, "--set", "date:Done at:start=2026-11-24",
                                      "--set", "date:Done at:end=")
        self.assertEqual(code, 0, err)
        patch = self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"]
        self.assertEqual(patch["Done at"], {"date": {"start": "2026-11-24"}})

    def test_update_prints_properties_as_stored(self):
        code, out, err = self.run_cli("update", PAGE, "--set", "Status=rollout", "--set", "Notes=Weekly export")
        self.assertEqual(code, 0, err)
        patch = self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"]
        self.assertEqual(patch["Status"], {"status": {"name": "Rollout"}})
        props = self.props_of(out)
        self.assertEqual(props, {"Status": "Rollout", "Notes": "Weekly export"})

    def test_update_unknown_property_sends_nothing_and_suggests(self):
        code, out, err = self.run_cli("update", PAGE, "--set", "Projects=" + page_url(PROJECT))
        self.assertEqual(code, 2)
        self.assertIn("did you mean Project", err)
        self.assertEqual(self.writes(), [])

    def test_update_unknown_option_lists_options(self):
        code, out, err = self.run_cli("update", PAGE, "--set", "Status=Finished")
        self.assertEqual(code, 2)
        for name in ("Not started", "In progress", "Rollout", "Done"):
            self.assertIn(name, err)
        code, out, err = self.run_cli("update", PAGE, "--set", "Tags=Backend,Mobile")
        self.assertEqual(code, 2)
        self.assertIn("Mobile", err)
        self.assertEqual(self.writes(), [])

    def test_update_edits_partial_match_exits_4(self):
        code, out, err = self.run_cli(
            "update", PAGE,
            "--edit", "exports invoices by hand", "exports invoices with one click",
            "--edit", "a sentence that is not there", "anything",
        )
        self.assertEqual(code, 4, err)
        sent = self.fake.sent("PATCH", rf"/v1/pages/{PAGE}/markdown")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].json["type"], "update_content")
        self.assertEqual(sent[0].json["markdown_version"], "v2")
        self.assertEqual(sent[0].json["update_content"]["content_updates"],
                         [{"old_str": "exports invoices by hand", "new_str": "exports invoices with one click"}])
        self.assertIn("edit 1: matched", out)
        self.assertIn("edit 2: no match", out)
        self.assertIn("a sentence that is not there", err)
        self.assertIn("one click", self.fake.markdown[PAGE])

    def test_update_no_edit_matches_exits_1_and_sends_nothing(self):
        code, out, err = self.run_cli("update", PAGE, "--edit", "nothing like this", "x", "--edit", "nor this", "y")
        self.assertEqual(code, 1)
        self.assertEqual(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}/markdown"), [])
        self.assertIn("nothing like this", err)

    def test_update_all_edits_match_exits_0(self):
        code, out, err = self.run_cli("update", PAGE, "--edit", "## Context", "## Why", "--edit", "by hand", "manually")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.markdown[PAGE], "## Why\n\nThe finance team exports invoices manually.\n")

    def test_update_replace_append_prepend_files(self):
        body = self.tmp / "body.md"
        body.write_text("<callout icon=\"⚡\" color=\"blue_bg\">\nNew note\n</callout>\n")
        for flag, kind, position in (("--replace-file", "replace_content", None),
                                     ("--append-file", "insert_content", "end"),
                                     ("--prepend-file", "insert_content", "start")):
            with self.subTest(flag=flag):
                code, out, err = self.run_cli("update", PAGE, flag, body)
                self.assertEqual(code, 0, err)
                sent = self.fake.sent("PATCH", rf"/v1/pages/{PAGE}/markdown")[-1].json
                self.assertEqual(sent["type"], kind)
                self.assertEqual(sent["markdown_version"], "v2")
                if kind == "replace_content":
                    self.assertEqual(sent["replace_content"]["new_str"], body.read_text())
                else:
                    self.assertEqual(sent["insert_content"]["content"], body.read_text())
                    self.assertEqual(sent["insert_content"]["position"], {"type": position})

    def test_update_replace_refuses_deleting_child_pages(self):
        child = uid(0x6001)
        self.fake.markdown[PAGE] = f"## Plan\n\n<page url=\"{page_url(child)}\">Rollout checklist</page>\n"
        body = self.tmp / "body.md"
        body.write_text("## Plan\n\nRewritten.\n")
        code, out, err = self.run_cli("update", PAGE, "--replace-file", body)
        self.assertEqual(code, 2)
        self.assertIn("Rollout checklist", err)
        self.assertIn("--allow-deleting-content", err)
        self.assertEqual(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}/markdown"), [])
        code, out, err = self.run_cli("update", PAGE, "--replace-file", body, "--allow-deleting-content")
        self.assertEqual(code, 0, err)
        sent = self.fake.sent("PATCH", rf"/v1/pages/{PAGE}/markdown")[-1].json
        self.assertTrue(sent["replace_content"]["allow_deleting_content"])

    def test_update_says_updated_only_after_a_write_landed(self):
        note = self.tmp / "note.md"
        note.write_text("Shipped.\n")
        before = self.fake.markdown[PAGE]
        self.fake.on("PATCH", rf"/v1/pages/{PAGE}/markdown", lambda r: error(400, "validation_error", "Bad markdown."))
        for args in (("--append-file", note), ("--edit", "by hand", "manually")):
            with self.subTest(args=args[0]):
                code, out, err = self.run_cli("update", PAGE, *args)
                self.assertEqual(code, 2, err)
                self.assertNotIn("updated", out)
                self.assertEqual(self.fake.markdown[PAGE], before)
        self.fake.overrides.clear()
        for args in (("--append-file", note), ("--edit", "by hand", "manually")):
            with self.subTest(args=args[0], answer=200):
                code, out, err = self.run_cli("update", PAGE, *args)
                self.assertEqual(code, 0, err)
                self.assertIn("updated " + self.page["url"], out.splitlines())

    def test_trash_needs_confirm(self):
        code, out, err = self.run_cli("trash", PAGE)
        self.assertEqual(code, 2)
        self.assertEqual(self.fake.calls, [])
        code, out, err = self.run_cli("trash", PAGE, "--confirm")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json, {"in_trash": True})
        self.assertIn("trashed", out)
        self.assertTrue(self.page["in_trash"])


class TextLinksTest(ClientTestCase):
    """Links inside a title or text property, as the short format reads and writes them."""

    def test_a_linked_run_is_printed_as_markdown_and_everything_else_is_literal(self):
        runs = [run("See "), run("the docs", "https://example.com/docs"), run(" and [draft] a_b *c* "),
                run("a ", "https://example.com/x"), run("bold", "https://example.com/x", bold=True), run(" word"),
                run(" mail "), run("ana@example.com", "mailto:ana@example.com"), run(" in "),
                run("Glossary", "/p/" + hex32(WIKI) + "?pvs=25"), run(" about "), run("Billing revamp", page_url(PROJECT), kind="mention"),
                run(" by "), run("wiki", "https://example.com/A_(b) c"), run("plain bold", bold=True)]
        shown = ("See [the docs](https://example.com/docs) and [draft] a_b *c* [a bold](https://example.com/x) word mail "
                 "[ana@example.com](mailto:ana@example.com) in [Glossary](" + page_url(WIKI) + "?pvs=25) about Billing revamp by "
                 "[wiki](https://example.com/A_(b)\\ c)plain bold")
        self.page["properties"]["Notes"]["rich_text"] = runs
        self.page["properties"]["Task name"]["title"] = [run("Export ["), run("invoices", "https://example.com/i"), run("]")]
        title = "Export [[invoices](https://example.com/i)]"
        code, out, err = self.run_cli("fetch", PAGE)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.props_of(out)["Notes"], shown)
        self.assertEqual(self.props_of(out)["Task name"], title)
        self.assertEqual(out.splitlines()[0], "title: Export [invoices]")
        code, out, err = self.run_cli("query", "Tasks", "--select", "Task name,Notes")
        self.assertEqual(out.splitlines()[1], title + " | " + shown + " | " + self.page["url"])
        code, out, err = self.run_cli("query", "Tasks", "--json")
        row = json.loads(out)[0]["properties"]
        self.assertEqual((row["Task name"], row["Notes"]), (title, shown))

    def test_a_value_read_and_written_back_keeps_its_links(self):
        runs = [run("See "), run("the [old] docs", "https://example.com/docs?a=1&b=(2)"), run(", "),
                run("ana@example.com", "mailto:ana@example.com"), run(" [draft] (x) "), run("Glossary", "/p/" + hex32(WIKI))]
        self.page["properties"]["Notes"]["rich_text"] = runs
        code, out, err = self.run_cli("fetch", PAGE, "--props-only")
        value = self.props_of(out)["Notes"]
        code, out, err = self.run_cli("update", PAGE, "--set", "Notes=" + value)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.props_of(out)["Notes"], value)
        stored = self.page["properties"]["Notes"]["rich_text"]
        self.assertEqual([(r["plain_text"], r["href"]) for r in stored],
                         [("See ", None), ("the [old] docs", "https://example.com/docs?a=1&b=(2)"), (", ", None),
                          ("ana@example.com", "mailto:ana@example.com"), (" [draft] (x) ", None), ("Glossary", page_url(WIKI))])

    def test_any_runs_printed_and_written_back_store_the_same_runs(self):
        u, v = "https://example.com/a", "https://example.com/b"
        wiki, mail = "https://example.org/wiki/Name_(thing)", "mailto:ana@example.com"
        table = [  # (the runs as (text, address), how they are printed)
            ("a lone [ in a link's text", [("see ", None), ("a [ b", u)], r"see [a \[ b](" + u + ")"),
            ("a lone ] in a link's text", [("a ] b", u)], r"[a \] b](" + u + ")"),
            ("] then [ in a link's text", [("x][y", u)], r"[x\]\[y](" + u + ")"),
            ("brackets nested in a link's text", [("[[x]]", u)], r"[\[\[x\]\]](" + u + ")"),
            ("balanced brackets stay as they are", [("the [old] docs", u)], "[the [old] docs](" + u + ")"),
            ("a backslash in a link's text", [("C:\\dir", u)], r"[C:\\dir](" + u + ")"),
            ("a backslash ending a link's text", [("a\\", u)], r"[a\\](" + u + ")"),
            ("a backslash before a bracket", [("a\\[b\\]", u)], r"[a\\\[b\\\]](" + u + ")"),
            ("link syntax in a link's text", [("a](" + v + ")", u)], r"[a\](" + v + r")](" + u + ")"),
            ("an address with balanced parentheses", [("Name", wiki)], "[Name](" + wiki + ")"),
            ("an address with an unbalanced )", [("x", "https://example.org/a)b")], r"[x](https://example.org/a\)b)"),
            ("an address with an unbalanced (", [("x", "https://example.org/a(b")], r"[x](https://example.org/a\(b)"),
            ("balanced and unbalanced parentheses", [("x", "https://example.org/a_(b)_c)")], r"[x](https://example.org/a_(b)_c\))"),
            ("a backslash and a space in an address", [("x", "https://example.org/a\\b c")], r"[x](https://example.org/a\\b\ c)"),
            ("brackets in an address", [("x", "https://example.org/a[1]")], "[x](https://example.org/a[1])"),
            ("a mailto address", [("write", mail)], "[write](" + mail + ")"),
            ("two links side by side", [("a", u), ("b", v)], "[a](" + u + ")[b](" + v + ")"),
            ("a link at the start", [("a", u), (" tail", None)], "[a](" + u + ") tail"),
            ("a link at the end", [("head ", None), ("a", u)], "head [a](" + u + ")"),
            ("a link alone", [("a", u)], "[a](" + u + ")"),
            ("plain text stays literal", [("a\\b [x] ] [ \\ ", None), ("l", u), (" ] \\[ (y) ", None)],
             "a\\b [x] ] [ \\ [l](" + u + ") ] \\[ (y) "),
            ("text that only looks like a link", [("[z](relative) [x] (y) [w](ftp://example.com/w)", None)],
             "[z](relative) [x] (y) [w](ftp://example.com/w)"),
            ("plain text that reads as a link", [("[x](" + u + ")", None)], r"\[x](" + u + ")"),
            ("plain text that reads as a link, after a backslash", [("\\[x](" + u + ")", None)], r"\\\[x](" + u + ")"),
            ("plain text that reads as a link, after two backslashes", [("a\\\\[x](" + u + ") b", None)], "a" + "\\" * 5 + "[x](" + u + ") b"),
            ("plain text that reads as a link to a mail, a telephone", [("[x](mailto:a@example.com) [y](tel:+1)", None)],
             r"\[x](mailto:a@example.com) \[y](tel:+1)"),
            ("plain text that reads as a link between < and >", [("[x](<anything>)", None)], r"\[x](<anything>)"),
            ("a bracket and a backslash right before a link", [("folder [x\\", None), ("a", u)], "folder [x\\\\[a](" + u + ")"),
            ("two backslashes right before a link", [("x\\\\", None), ("a", u)], "x" + "\\" * 4 + "[a](" + u + ")"),
            ("a backslash alone before a link", [("\\", None), ("a", u), ("\\", None), ("b", v), ("\\", None)],
             "\\\\[a](" + u + ")\\\\[b](" + v + ")\\"),
            ("a bracket that the text after a link would close", [("[x ", None), ("a", u), (" y](" + v + ")", None)],
             r"\[x [a](" + u + ") y](" + v + ")"),
            ("a bracket that the address of a link would close", [("[x ", None), ("a", "https://e.com/](https://z)"), (" b", None)],
             r"\[x [a](https://e.com/](https://z)) b"),
            ("plain text around a link reads as an address", [("[x](https://e.com/", None), ("a", u), (")", None)],
             r"\[x](https://e.com/[a](" + u + "))"),
            ("plain text around a link reads as an address between < and >", [("[x](<", None), ("a", u), (">)", None)],
             r"\[x](<[a](" + u + ")>)"),
            ("nested brackets that read as a link", [("[[x]](" + u + ") [a [b] c](" + v + ")", None)],
             r"\[[x]](" + u + r") \[a [b] c](" + v + ")"),
            ("two links in a row, both plain", [("[x](" + u + ")[y](" + v + ")", None)], r"\[x](" + u + r")\[y](" + v + ")"),
            ("an escaped bracket in plain text is nothing to escape", [(r"a \[b\] \] c", None)], r"a \[b\] \] c"),
            ("text with an unfinished link", [("[x](https://e.com [y](mailto:) [](" + u + ")", None)],
             "[x](https://e.com [y](mailto:) [](" + u + ")"),
            ("a telephone", [("call", "tel:+15550100")], "[call](tel:+15550100)"),
            ("another scheme", [("x", "notion://app/y"), (" ", None), ("y", "sftp://example.com/a"), (" ", None), ("z", "linear://example.com/a")],
             "[x](<notion://app/y>) [y](<sftp://example.com/a>) [z](<linear://example.com/a>)"),
            ("an address with no scheme", [("x", "example.com"), ("y", "user@example.com"), ("z", "//example.com/x")],
             "[x](<example.com>)[y](<user@example.com>)[z](<//example.com/x>)"),
            ("an address urllib cannot read", [("x", "//[x"), ("y", "http://[x")], "[x](<//[x>)[y](http://[x)"),
            ("a scheme with nothing after it", [("x", "mailto:"), ("y", "https://")], "[x](<mailto:>)[y](<https://>)"),
            ("spaces, parentheses and backslashes between < and >", [("x", "a )(b\\"), ("y", "<z>")], r"[x](<a\ \)\(b\\>)[y](<<z>>)"),
            ("a path inside Notion", [("page", "/" + hex32(WIKI)), (" ", None), ("block", "/" + hex32(WIKI) + "#" + hex32(PAGE))],
             "[page](https://app.notion.com/" + hex32(WIKI) + ") [block](https://app.notion.com/" + hex32(WIKI) + "#" + hex32(PAGE) + ")"),
            ("the full address of the same page", [("page", "https://app.notion.com/" + hex32(WIKI)), ("p", page_url(WIKI))],
             "[page](<https://app.notion.com/" + hex32(WIKI) + ">)[p](" + page_url(WIKI) + ")"),
        ]
        for name, spec, printed in table:
            with self.subTest(name):
                runs = [run(said, address) for said, address in spec]
                self.page["properties"]["Notes"]["rich_text"] = runs
                code, out, err = self.run_cli("fetch", PAGE, "--props-only")
                self.assertEqual(code, 0, err)
                value = self.props_of(out)["Notes"]
                self.assertEqual(value, printed)
                self.page["properties"]["Notes"]["rich_text"] = []
                code, out, err = self.run_cli("update", PAGE, "--set", "Notes=" + value)
                self.assertEqual(code, 0, err)
                stored = self.page["properties"]["Notes"]["rich_text"]
                self.assertEqual([(r["plain_text"], r["href"]) for r in stored], spec)

    def test_every_list_of_runs_survives_printing_and_reading(self):
        # A fuzz that favours brackets, parentheses and backslashes next to links, and whole links as plain text.
        dice = random.Random(20261125)
        bits = ["[", "]", "(", ")", "\\", "\\\\", "[", "](", ")", "<", ">", " ", "x", "é", "\n", "](https://e.com/", "https://",
                "mailto:", "tel:", "[a](https://e.com/b)", "](<", ">)", "/" + hex32(WIKI), "https://app.notion.com/" + hex32(WIKI)]
        starts = ["https://e.com/", "http://", "mailto:", "tel:", "notion://", "/", "//", "", "/" + hex32(WIKI), "https://app.notion.com/"]

        def made(limit):
            return "".join(dice.choice(bits) for _ in range(dice.randint(1, limit)))

        def merged(runs):
            out = []
            for said, url in runs:
                if out and out[-1][1] == url:
                    out[-1] = (out[-1][0] + said, url)
                else:
                    out.append((said, url))
            return out

        def writable(url):  # the one change: a path the API refuses is the full address of the same page
            path = url and url.startswith("/") and not url.startswith("//")
            return "https://app.notion.com" + url if path and not re.fullmatch(r"/[0-9a-f]{32}(#[0-9a-f]{32})?", url) else url

        escaped = 0
        for number in range(6000):
            spec = [(made(6), None) if dice.random() < 0.5 else (made(4), dice.choice(starts) + made(3)) for _ in range(dice.randint(1, 5))]
            runs = merged([(said, url or None) for said, url in spec])
            printed = self.n.linked([run(said, url) for said, url in runs])
            read = merged([(r["text"]["content"], (r["text"].get("link") or {}).get("url")) for r in self.n.linked_text(printed)])
            self.assertEqual(read, merged([(said, writable(url)) for said, url in runs]), (number, runs, printed))
            if [url for _, url in runs] == [None]:  # plain text alone: escaped only where something in it looks like a link
                if not re.search(r"\[[\s\S]+\]\((?:https?://|mailto:|tel:|<)", runs[0][0]):
                    self.assertEqual(printed, runs[0][0])
                escaped += printed != runs[0][0]
        self.assertGreater(escaped, 20, "the fuzz never met plain text that looks like a link")

    def test_a_long_value_is_read_and_printed_in_linear_time(self):
        size = 200000
        shapes = {"\\[": "\\[", "[": "[", "]": "]", "[[]": "[[]", "backslashes": "\\", "\\[\\": "\\[\\", "](": "](", "[](": "[](",
                  "[a](": "[a](", "[a](https://": "[a](https://", "[a](https://e.com/(": "[a](https://e.com/(", "(": "(", ")": ")",
                  "[a](<": "[a](<", "[a](https://e.com/b)": "[a](https://e.com/b)", "\\[a](https://e.com/b)": "\\[a](https://e.com/b)",
                  "words": "some words ", "[a] ": "[a] ", "[a](https://e.com/\\ ": "[a](https://e.com/\\ ", "](https://e.com)": "](https://e.com)"}
        for name, shape in shapes.items():
            value = "[a](https://e.com/b) " + (shape * (size // len(shape) + 1))[:size] + "[a](https://e.com/b)"
            with self.subTest(shape=name):
                began = time.process_time()  # the process's own time: the machine's load does not count
                runs = self.n.linked_text(value)
                printed = self.n.linked([run(r["text"]["content"], (r["text"].get("link") or {}).get("url")) for r in runs])
                spent = time.process_time() - began
                self.assertLess(spent, 5, "the scan is not linear")
                again = self.n.linked_text(printed)
                self.assertEqual([(r["text"]["content"], r["text"].get("link")) for r in again],
                                 [(r["text"]["content"], r["text"].get("link")) for r in self.joined(runs)])

    def joined(self, runs):
        """The runs as one reading gives them: neighbours of one address together, in pieces of 2,000."""
        out = []
        for r in runs:
            url = (r["text"].get("link") or {}).get("url")
            if out and out[-1][1] == url:
                out[-1][0] += r["text"]["content"]
            else:
                out.append([r["text"]["content"], url])
        return [piece for said, url in out for piece in self.n.rich_text(said, url)]

    def test_reading_never_fails_on_what_a_card_holds(self):
        addresses = ["//[x", "http://[x", "https://[::1", "//", "/", "?", "#", "[", "](", ")", "(", "\\", " ", "<", "<>", "::", "%", "https://a:b/",
                     "javascript:x", "data:,x", "mailto:", "tel:", "\u0000", "\n"]
        for address in addresses:
            with self.subTest(address=address):
                self.page["properties"]["Notes"]["rich_text"] = [run("before "), run("label", address), run(" after")]
                for verb in (("fetch", PAGE), ("query", "Tasks", "--select", "Notes"), ("query", "Tasks", "--json")):
                    code, out, err = self.run_cli(*verb)
                    self.assertEqual(code, 0, err)
                    self.assertIn("label", out)

    def test_a_written_link_becomes_a_linked_run_in_update_create_and_a_pages_file(self):
        link = {"text": {"content": "docs", "link": {"url": "https://example.com/docs"}}}
        value = "A [docs](https://example.com/docs), [x] (y) [z](relative) **b**"
        expected = [{"text": {"content": "A "}}, link, {"text": {"content": ", [x] (y) [z](relative) **b**"}}]
        code, out, err = self.run_cli("update", PAGE, "--set", "Notes=" + value)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"]["Notes"], {"rich_text": expected})
        code, out, err = self.run_cli("create", "--parent", "Tasks", "--set", "title=" + value)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.sent("POST", r"/v1/pages")[-1].json["properties"]["Task name"], {"title": expected})
        pages = self.tmp / "pages.json"
        pages.write_text(json.dumps([{"properties": {"Task name": "One", "Notes": value}}]))
        code, out, err = self.run_cli("create", "--parent", "Tasks", "--pages-file", pages)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.sent("POST", r"/v1/pages")[-1].json["properties"]["Notes"], {"rich_text": expected})
        long = "a" * 2500
        code, out, err = self.run_cli("update", PAGE, "--set", f"Notes=[{long}](https://example.com/l)")
        sent = self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"]["Notes"]["rich_text"]
        self.assertEqual([(len(r["text"]["content"]), r["text"]["link"]["url"]) for r in sent],
                         [(2000, "https://example.com/l"), (500, "https://example.com/l")])

    def test_the_client_itself_uses_titles_as_plain_text(self):
        self.fake.data_sources[DS_PROJECTS]["title"] = [run("Pro"), run("jects", "https://example.com/p")]
        code, out, err = self.run_cli("fetch", "projects")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines()[0], "data source: Projects")

        def lands_then_503(request):
            self.fake.create_page(request.json)
            return error(503, "service_unavailable", "Try later.")
        self.fake.on("POST", r"/v1/pages", lands_then_503)
        code, out, err = self.run_cli("create", "--parent", "Tasks", "--set", "title=Read [docs](https://example.com/docs)")
        self.assertEqual(code, 0, err)
        self.assertIn("found by its title", out)
        looked = self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")[-1].json["filter"]["and"][0]
        self.assertEqual(looked, {"property": "Task name", "title": {"equals": "Read docs"}})
        self.page["properties"]["Notes"]["rich_text"] = [run("split "), run("needle", "https://example.com/haystack"), run(" here")]
        code, out, err = self.run_cli("search", "split needle here")
        self.assertIn(f"{self.page['url']} | Tasks | matched: Notes", out)


class CreateTest(ClientTestCase):
    def test_create_in_data_source_one_request(self):
        body = self.tmp / "card.md"
        body.write_text("## Context\n\nA new card.\n")
        code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS,
                                      "--set", "Task name=Archive old invoices", "--set", "Status=Not started",
                                      "--set", "Tags=Backend", "--body-file", body, "--icon", "🧾")
        self.assertEqual(code, 0, err)
        posts = self.fake.sent("POST", r"/v1/pages")
        self.assertEqual(len(posts), 1)
        sent = posts[0].json
        self.assertEqual(sent["parent"], {"data_source_id": DS_TASKS})
        self.assertEqual(sent["properties"]["Task name"], {"title": [{"text": {"content": "Archive old invoices"}}]})
        self.assertEqual(sent["properties"]["Status"], {"status": {"name": "Not started"}})
        self.assertEqual(sent["markdown"], "## Context\n\nA new card.\n")
        self.assertEqual(sent["markdown_version"], "v2")
        self.assertEqual(sent["icon"], {"type": "emoji", "emoji": "🧾"})
        created = [pg for pg in self.fake.pages.values() if self.fake.title_of(pg) == "Archive old invoices"][0]
        self.assertIn(created["url"], out)
        self.assertIn(key(200), out)

    def test_create_child_page_with_title(self):
        code, out, err = self.run_cli("create", "--parent", page_url(PROJECT), "--set", "title=Approved plan")
        self.assertEqual(code, 0, err)
        sent = self.fake.sent("POST", r"/v1/pages")[-1].json
        self.assertEqual(sent["parent"], {"page_id": PROJECT})
        self.assertEqual(sent["properties"], {"title": {"title": [{"text": {"content": "Approved plan"}}]}})
        self.assertIn("created ", out)

    def test_create_says_which_heading_notion_left_out(self):
        # The API drops a body's only level-1 heading when it is the first line, title given or not.
        cases = [("# Only\n\nText.\n", "'# Only'"), ("\n# Only\n## Sub\n\n```\n# code\n```\n", "'# Only'"),
                 ("# One\n\nText.\n\n# Two\n", None), ("Intro.\n\n# Mid\n", None), ("## Sub\n\nText.\n", None),
                 ("```\n# code\n```\n", None), ("#tag text\n", None), ("", None),
                 ("# Only\n\n```\na\n```js\n# in code\n```\n", "'# Only'"), ("# Only\n\n~~~\n# in code\n~~~\n", "'# Only'"),
                 ("# Only\n\n> ```\n> # in code\n> ```\n\ntext\n", "'# Only'"), ("# Only\n\n~~~\na\n```\n# in code\n~~~\n", "'# Only'"),
                 ("~~~\n# code\n~~~\n", None), ("```code``` text\n\n# Mid\n", None), ("# One\n\n```code``` text\n\n# Two\n", None),
                 ("Title\n=====\n\nText.\n", None), ("> # quoted\n\nText.\n", None)]
        body = self.tmp / "body.md"
        for markdown, heading in cases:
            with self.subTest(markdown=markdown):
                body.write_text(markdown)
                code, out, err = self.run_cli("create", "--parent", "Tasks", "--set", "title=A card", "--body-file", body)
                self.assertEqual(code, 0, err)
                url = re.search(r"created (\S+)", out).group(1)
                if heading:
                    self.assertEqual(len(err.splitlines()), 1)
                    self.assertIn(f"{heading} was left out of {url}", err)
                    self.assertIn("--prepend-file", err)
                else:
                    self.assertEqual(err, "")

    def test_create_pages_file_three_pages(self):
        pages = self.tmp / "pages.json"
        pages.write_text(json.dumps([
            {"properties": {"Task name": f"Step {i}", "Status": "Not started"}, "content": f"Body {i}"} for i in range(3)
        ]))
        code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--pages-file", pages)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 3)
        lines = [line for line in out.splitlines() if line.startswith("created ")]
        self.assertEqual(len(lines), 3)
        for i, line in enumerate(lines):
            self.assertIn(key(200 + i), line)

    def test_local_checks_fail_before_any_write(self):
        pages = self.tmp / "pages.json"
        cases = [
            [{"properties": {"Task name": "Step 0"}}, {"properties": {"Task name": "Step 1"}},
             {"properties": {"Task name": "Step 2", "Status": "Finished"}}],
            [{"properties": {"Task name": "Step 0"}}, "not a page"],
            [{"properties": {"Task name": "Step 0"}}, {"properties": {"Task name": "Step 1"}, "content": ["a list"]}],
        ]
        for entries in cases:
            with self.subTest(pages=entries):
                pages.write_text(json.dumps(entries))
                code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--pages-file", pages)
                self.assertEqual(code, 2, err)
                self.assertIn("nothing was sent", err)
        code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--set", "Task name=A",
                                      "--body-file", self.tmp / "missing.md")
        self.assertEqual(code, 2, err)
        code, out, err = self.run_cli("update", PAGE, "--set", "Status=Rollout", "--append-file", self.tmp / "missing.md")
        self.assertEqual(code, 2, err)
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.fake.title_of(self.page), "Export invoices")
        self.assertEqual(self.page["properties"]["Status"]["status"]["name"], "Done")

    def test_a_write_that_lands_in_part_exits_4_naming_what_landed(self):
        note = self.tmp / "note.md"
        note.write_text("Shipped.\n")
        self.fake.on("PATCH", rf"/v1/pages/{PAGE}/markdown", lambda r: error(400, "validation_error", "Bad markdown."))
        code, out, err = self.run_cli("update", PAGE, "--set", "Status=Rollout", "--append-file", note)
        self.assertEqual(code, 4, err)
        self.assertEqual(self.page["properties"]["Status"]["status"]["name"], "Rollout")
        self.assertRegex(err, r"written: properties Status\b")
        self.assertRegex(err, r"Not written: body added at the end \(.*400")
        self.fake.overrides.clear()

        pages = self.tmp / "pages.json"
        pages.write_text(json.dumps([{"properties": {"Task name": f"Step {i}"}} for i in range(3)]))
        posts = []

        def second_refused(r):
            posts.append(r)
            return error(400, "validation_error", "Refused.") if len(posts) == 2 else None

        self.fake.on("POST", r"/v1/pages", second_refused)
        code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--pages-file", pages)
        self.assertEqual(code, 4, err)
        self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 2)
        first = [pg for pg in self.fake.pages.values() if self.fake.title_of(pg) == "Step 0"]
        self.assertEqual(len(first), 1)
        self.assertIn(first[0]["url"], out)
        self.assertIn("created 1 of 3: " + first[0]["url"], err)
        self.assertIn("Not created: 'Step 1'", err)
        self.assertIn("not sent: 'Step 2'", err)

    def test_a_later_write_in_doubt_is_reported_in_doubt_not_unwritten(self):
        note = self.tmp / "note.md"
        note.write_text("Shipped.\n")

        def answer(status):
            def handler(r):
                if status == "timeout":
                    raise TimeoutError("timed out")
                return error(status, "service_unavailable", "Try again later.")
            return handler

        for status in (502, 503, 504, "timeout"):
            with self.subTest(status=status):
                self.fake.overrides.clear()
                self.fake.calls.clear()
                self.fake.on("PATCH", rf"/v1/pages/{PAGE}/markdown", answer(status))
                code, out, err = self.run_cli("update", PAGE, "--set", "Status=Rollout", "--append-file", note)
                self.assertEqual(code, 4, err)
                self.assertEqual(self.page["properties"]["Status"]["status"]["name"], "Rollout")
                self.assertEqual(len(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}/markdown")), 1)
                self.assertRegex(err, r"written: properties Status\b")
                self.assertIn("In doubt: body added at the end", err)
                self.assertIn("fetch the page and check", err)
                self.assertNotIn("Not written", err)
                self.assertNotIn("Rerun only what was not written", err)

        self.fake.overrides.clear()
        self.fake.on("PATCH", rf"/v1/pages/{PAGE}/markdown", answer(503))
        code, out, err = self.run_cli("update", PAGE, "--set", "Status=Done", "--edit", "by hand", "manually",
                                      "--append-file", note)
        self.assertEqual(code, 4, err)
        self.assertIn("In doubt: body edits 1", err)
        self.assertIn("not sent: body added at the end", err)
        self.assertIn("Rerun only what was not sent", err)
        self.assertNotIn("Not written", err)

        self.fake.overrides.clear()
        self.fake.on("PATCH", rf"/v1/pages/{PAGE}/markdown", lambda r: error(400, "validation_error", "Bad markdown."))
        code, out, err = self.run_cli("update", PAGE, "--set", "Status=Rollout", "--append-file", note)
        self.assertEqual(code, 4, err)
        self.assertRegex(err, r"Not written: body added at the end \(.*400.*\): Notion refused it\. ")
        self.assertNotIn("nothing changed", err)  # the properties were written
        self.assertIn("Rerun only what was not written", err)
        self.assertNotIn("In doubt", err)

    def test_create_after_503_finds_the_page_and_does_not_resend(self):
        for status in (502, 503, 504):
            with self.subTest(status=status):
                self.fake.calls.clear()
                title = f"Card after {status}"

                def fail_after_writing(r, status=status):
                    self.fake.create_page(r.json)
                    return error(status, "service_unavailable", "Try again later.")

                self.fake.on("POST", r"/v1/pages", fail_after_writing)
                other = task_page(uid(0x4000 + status), 150, title, created_by=ANA)
                self.fake.add_page(other)
                code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--set", f"Task name={title}")
                self.assertEqual(code, 0, err)
                self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 1)
                mine = [pg for pg in self.fake.pages.values()
                        if self.fake.title_of(pg) == title and pg["created_by"]["id"] == BOT][0]
                self.assertIn(mine["url"], out)
                self.assertNotIn(other["url"], out)
                self.fake.overrides.clear()

    def test_a_page_found_after_a_create_in_doubt_is_marked_to_check(self):
        def fail_after_writing(r):
            self.fake.create_page(r.json)
            return error(503, "service_unavailable", "Try again later.")

        self.fake.on("POST", r"/v1/pages", fail_after_writing)
        code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--set", "Task name=Found later")
        self.assertEqual(code, 0, err)
        found = [pg for pg in self.fake.pages.values() if self.fake.title_of(pg) == "Found later"][0]
        line = [line for line in out.splitlines() if line.startswith("created ")][0]
        self.assertTrue(line.startswith(f"created {found['url']} {key(200)} "), line)  # where a caller reads them
        self.assertNotIn("the page was created", line)
        for words in ("503", "found by its title", "not sent again", "check"):
            self.assertIn(words, line)
        for name in ("SKILL.md", "references/api-limits.md"):
            with self.subTest(file=name):
                said = " ".join((SKILL_DIR / name).read_text(encoding="utf-8").split())
                self.assertRegex(said, r"`created_time` to the minute")
                self.assertRegex(said, r"same title made earlier in that minute")
                self.assertRegex(said, r"[Rr]ead the page found .{0,40}before treating it as the new one")

    def test_create_after_503_ignores_an_older_page_with_the_same_title(self):
        title = "Weekly sync"
        older = self.fake.add_page(task_page(uid(0x4100), 151, title, created_by=BOT,
                                             created_time="2026-01-01T08:00:00.000Z"))
        just_before = self.fake.add_page(task_page(uid(0x4101), 152, title, created_by=BOT,
                                                   created_time="2026-11-22T09:29:00.000Z"))
        child = self.fake.add_page(child_page(uid(0x4102), title, PROJECT))
        child["created_time"] = "2026-01-01T08:00:00.000Z"
        # The fake applies no created_time condition, so only the client's own check keeps these out.
        self.fake.on("POST", r"/v1/pages", lambda r: error(503, "service_unavailable", "Try again later."))
        for parent, setting in ((COLLECTION + DS_TASKS, "Task name=" + title), (page_url(PROJECT), "title=" + title)):
            with self.subTest(parent=parent):
                self.fake.calls.clear()
                code, out, err = self.run_cli("create", "--parent", parent, "--set", setting)
                self.assertEqual(code, 1, out + err)
                self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 1)
                for page in (older, just_before, child):
                    self.assertNotIn(page["url"], out + err)
                self.assertNotIn("created ", out)
                lookups = [c.json for c in self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")]
                if parent.startswith(COLLECTION):
                    self.assertIn({"timestamp": "created_time", "created_time": {"on_or_after": "2026-11-22T09:30:00.000Z"}},
                                  lookups[-1]["filter"]["and"])

    def test_pages_file_with_a_repeated_title_never_takes_a_page_of_this_run(self):
        pages = self.tmp / "pages.json"
        parents = ((COLLECTION + DS_TASKS, "Task name"), (page_url(PROJECT), "title"))

        def titled(title):
            return [pg for pg in self.fake.pages.values() if self.fake.title_of(pg) == title]

        for parent, title_key in parents:
            for status in (503, 504):
                for repeats in (2, 3):
                    title = f"Same {title_key} {status} x{repeats}"
                    with self.subTest(parent=parent, status=status, repeats=repeats, landed=False):
                        self.fake.overrides.clear()
                        posts = []

                        def doubt_on_second(r, status=status):
                            posts.append(r)
                            return error(status, "service_unavailable", "Try again later.") if len(posts) == 2 else None

                        self.fake.on("POST", r"/v1/pages", doubt_on_second)
                        pages.write_text(json.dumps([{"properties": {title_key: title}}] * repeats))
                        code, out, err = self.run_cli("create", "--parent", parent, "--pages-file", pages)
                        self.assertEqual(code, 4, out + err)
                        self.assertEqual(len(posts), 2)  # the one in doubt is not sent again, the rest not at all
                        created = titled(title)
                        self.assertEqual(len(created), 1)
                        self.assertEqual(out.count(created[0]["url"]), 1, out)
                        self.assertEqual(err.count(created[0]["url"]), 1, err)
                        self.assertIn(f"created 1 of {repeats}: " + created[0]["url"], err)
                        self.assertIn(f"In doubt: {title!r}", err)
                        self.assertNotIn("Not created", err)
                        if repeats == 3:
                            self.assertIn(f"not sent: {title!r}", err)

                    title = f"Same {title_key} {status} landed x{repeats}"
                    with self.subTest(parent=parent, status=status, repeats=repeats, landed=True):
                        self.fake.overrides.clear()
                        posts = []

                        def lands_then_doubt(r, status=status):
                            posts.append(r)
                            if len(posts) == 2:
                                self.fake.create_page(r.json)
                                return error(status, "service_unavailable", "Try again later.")
                            return None

                        self.fake.on("POST", r"/v1/pages", lands_then_doubt)
                        pages.write_text(json.dumps([{"properties": {title_key: title}}] * repeats))
                        code, out, err = self.run_cli("create", "--parent", parent, "--pages-file", pages)
                        self.assertEqual(code, 0, out + err)
                        self.assertEqual(len(posts), repeats)
                        created = titled(title)
                        self.assertEqual(len(created), repeats)
                        lines = [line for line in out.splitlines() if line.startswith("created ")]
                        self.assertEqual(len(lines), repeats)
                        for page, line in zip(created, lines):
                            self.assertEqual(out.count(page["url"]), 1, out)
                            self.assertTrue(line.startswith("created " + page["url"]), line)
                        self.assertIn(str(status), lines[1])

        self.fake.overrides.clear()
        self.fake.on("POST", r"/v1/pages", lambda r: error(503, "service_unavailable", "Try again later."))
        pages.write_text(json.dumps([{"properties": {"Task name": "Same first"}}] * 2))
        self.fake.calls.clear()
        code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--pages-file", pages)
        self.assertEqual(code, 1, out + err)  # the first page in doubt: what a single page gives
        self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 1)
        self.assertNotIn("created ", out)

    def test_create_after_timeout_without_page_exits_1_sent_once(self):
        def timeout(r):
            raise TimeoutError("timed out")

        self.fake.on("POST", r"/v1/pages", timeout)
        code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--set", "Task name=Never arrived")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 1)
        self.assertIn("Never arrived", err)


WRITE_OUTCOMES = {  # how a write's request ends -> which of the three cases the client must say it is
    "400": "refused", "429": "refused", "500": "in doubt", "502": "in doubt", "503": "in doubt",
    "504": "in doubt", "529": "in doubt", "timeout": "in doubt", "reset": "in doubt", "unreachable": "not sent",
    "302": "in doubt", "200 not json": "in doubt", "200 cut": "in doubt", "200 empty": "in doubt", "200 scalar": "in doubt",
    "tls eof": "in doubt", "tls other": "in doubt", "incomplete": "in doubt", "disconnected": "in doubt",
    "broken answer": "in doubt", "pipe": "in doubt", "os error": "in doubt", "any other": "in doubt",
}
LOST = {  # how a connection that was established fails before its answer is whole
    "timeout": TimeoutError("timed out"),
    "reset": ConnectionResetError(104, "Connection reset by peer"),
    "tls eof": ssl.SSLEOFError(8, "EOF occurred in violation of protocol"),
    "tls other": ssl.SSLError(1, "[SSL: BAD_RECORD_MAC] bad record mac"),
    "incomplete": http.client.IncompleteRead(b"{", 40),
    "disconnected": http.client.RemoteDisconnected("Remote end closed connection without response"),
    "broken answer": http.client.BadStatusLine("garbage"),
    "pipe": BrokenPipeError(32, "Broken pipe"),
    "os error": OSError(5, "Input/output error"),
    "any other": ValueError("a chunk that is not a number"),
}
UNREADABLE = {  # a success whose body is not the API's answer
    "200 not json": b"<html>Sign in to the network</html>", "200 cut": b'{"object": "page", "id"', "200 empty": b"", "200 scalar": b'"ok"',
}


def ends_in(outcome):
    """A fake answer for a write: a status, a success that cannot be read, a connection lost after the request
    left, or no connection."""
    def handler(r):
        if outcome in LOST:
            raise LOST[outcome]
        if outcome in UNREADABLE:
            return 200, UNREADABLE[outcome]
        if outcome == "unreachable":
            raise ConnectionRefusedError(111, "Connection refused")
        status = int(outcome)
        if status == 429:
            return 429, {"object": "error", "status": 429, "code": "rate_limited", "message": "slow down"}, {"Retry-After": "0"}
        return error(status, "synthetic_failure", "Synthetic failure.")
    return handler


class WriteOutcomeTest(ClientTestCase):
    """One rule for every write that does not come back with a success: refused, not sent or in doubt."""

    def assert_case(self, case, err, landed=False):
        if landed:  # once a write of the command landed, no line says that nothing changed
            self.assertNotRegex(err, r"(?i)nothing changed|nothing was made|never left this machine")
        if case == "refused":
            self.assertRegex(err, r"Notion refused it" + ("" if landed else r" and nothing (changed|was made)"))
            self.assertNotRegex(err, r"(?i)in doubt|may have been|never left")
        elif case == "not sent":
            self.assertRegex(err, r"Not sent: " if landed else r"the request never left this machine, so nothing (changed|was made)")
            self.assertNotRegex(err, r"(?i)in doubt|may have been|refused it")
        else:
            self.assertRegex(err, r"(?i)\bin doubt\b")
            self.assertRegex(err, r"may have been (applied|created)")
            self.assertNotRegex(err, r"(?i)nothing changed|nothing was made|not written|not created|refused it|never left")

    def test_every_write_verb_says_refused_not_sent_or_in_doubt(self):
        self.settings(me="ana@example.com")
        mine = {"object": "comment", "id": uid(0xCB), "discussion_id": uid(0xCA),
                "created_by": {"object": "user", "id": BOT}, "rich_text": text("Mine")}
        self.fake.comments[PAGE] = [mine]
        shot = self.tmp / "screen.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\nfake image")
        pages = self.tmp / "pages.json"
        pages.write_text(json.dumps([{"properties": {"Task name": "Outcome first"}},
                                     {"properties": {"Task name": "Outcome second"}}]))
        verbs = [  # name, arguments, the write that fails, its exit code on 400 (else 1)
            ("update", ("update", PAGE, "--set", "Status=Rollout"), "PATCH", rf"/v1/pages/{PAGE}", 2),
            ("create", ("create", "--parent", COLLECTION + DS_TASKS, "--set", "Task name=Outcome card"),
             "POST", r"/v1/pages", 2),
            ("create --pages-file", ("create", "--parent", COLLECTION + DS_TASKS, "--pages-file", pages),
             "POST", r"/v1/pages", 4),
            ("comments add", ("comments", "add", PAGE, "--body", "Ready"), "POST", r"/v1/comments", 2),
            ("comments reply", ("comments", "reply", mine["discussion_id"], "--body", "Ready"), "POST", r"/v1/comments", 2),
            ("comments edit", ("comments", "edit", mine["id"], "--body", "Changed"), "PATCH", rf"/v1/comments/{mine['id']}", 2),
            ("upload", ("upload", shot), "POST", r"/v1/file_uploads", 1),
            ("trash", ("trash", PAGE, "--confirm"), "PATCH", rf"/v1/pages/{PAGE}", 2),
            ("api", ("api", "POST", "/v1/comments", "--data", json.dumps({"parent": {"page_id": PAGE}, "markdown": "x"})),
             "POST", r"/v1/comments", 1),
        ]
        for name, args, method, path, on_400 in verbs:
            for outcome, case in WRITE_OUTCOMES.items():
                with self.subTest(verb=name, outcome=outcome):
                    self.fake.overrides.clear()
                    self.fake.calls.clear()
                    failing = ends_in(outcome)
                    sends = []

                    def fail(r, name=name, failing=failing):
                        sends.append(r)
                        if name == "create --pages-file" and len(self.fake.sent("POST", r"/v1/pages")) == 1:
                            return None  # the first page lands, the second fails
                        return failing(r)

                    self.fake.on(method, path, fail)
                    code, out, err = self.run_cli(*args)
                    expected = 4 if name == "create --pages-file" else (on_400 if outcome == "400" else 1)
                    self.assertEqual(code, expected, err)
                    self.assert_case(case, err, landed=name == "create --pages-file")
                    first = 1 if name == "create --pages-file" else 0
                    self.assertEqual(len(sends), first + (6 if outcome == "429" else 1), "a write is never resent blindly")
        for doc in ("SKILL.md", "references/api-limits.md"):
            with self.subTest(doc=doc):
                said = " ".join((SKILL_DIR / doc).read_text(encoding="utf-8").split())
                for words in ("Notion refused it and nothing changed" if doc == "SKILL.md" else "refused",
                              "never left", "in doubt", "any 5xx", "a timeout", "after the request left"):
                    self.assertIn(words.casefold(), said.casefold())

    def serve_once(self, answer, reset=False):
        """A local server that reads one request, sends `answer` and closes, with a reset when asked to: its port,
        and the list of the requests it read."""
        listener, read = socket.socket(), []
        listener.bind(("127.0.0.1", 0))
        listener.listen(5)
        listener.settimeout(30)
        self.addCleanup(listener.close)

        def serve():
            try:
                while True:
                    conn, _ = listener.accept()
                    conn.settimeout(10)
                    read.append(conn.recv(65536))  # the request left and arrived
                    if reset:
                        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    if answer:
                        conn.sendall(answer)
                    conn.close()
            except OSError:
                pass
        threading.Thread(target=serve, daemon=True).start()
        return listener.getsockname()[1], read

    def test_the_real_transport_tells_a_lost_connection_from_one_never_made(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        refused_port = closed.getsockname()[1]
        closed.close()  # nobody listens there: the connection is refused before anything is sent
        bypass = mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"})
        bypass.start()
        self.addCleanup(bypass.stop)
        self.settings(me="ana@example.com")
        self.fake.comments[PAGE] = []
        eof = LOST["tls eof"]

        def ok(body, length=None):
            return (f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {length or len(body)}\r\n\r\n"
                    + body).encode()

        def raising(target, error):
            return lambda: mock.patch.object(*target, side_effect=error)

        reading, beginning = (http.client.HTTPResponse, "read"), (http.client.HTTPResponse, "begin")
        table = [  # name, what the server sends, reset, what is patched, scheme, the case of a write
            ("closes without an answer", b"", False, None, "http", "in doubt"),
            ("resets without an answer", b"", True, None, "http", "in doubt"),
            ("a body cut short", ok("{", 40), False, None, "http", "in doubt"),
            ("not http at all", b"garbage\r\n\r\n", False, None, "http", "in doubt"),
            ("a broken chunk", b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n", False, None, "http", "in doubt"),
            ("a page that is not JSON", ok("<html></html>"), False, None, "http", "in doubt"),
            ("an empty answer", b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", False, None, "http", "in doubt"),
            ("a redirect", b"HTTP/1.1 302 Found\r\nLocation: /v1/elsewhere\r\nContent-Length: 0\r\n\r\n", False, None, "http", "in doubt"),
            ("a 503 whose body is cut", b"HTTP/1.1 503 Busy\r\nContent-Length: 40\r\n\r\n{", False, None, "http", "in doubt"),
            ("a 400 whose body is cut", b"HTTP/1.1 400 Bad\r\nContent-Length: 40\r\n\r\n{", False, None, "http", "refused"),
            ("a TLS error while the status is read", ok("{}"), False, raising(beginning, eof), "http", "in doubt"),
            ("a TLS error while the body is read", ok("{}"), False, raising(reading, eof), "http", "in doubt"),
            ("a reset while the body is read", ok("{}"), False, raising(reading, LOST["reset"]), "http", "in doubt"),
            ("a timeout while the body is read", ok("{}"), False, raising(reading, LOST["timeout"]), "http", "in doubt"),
            ("a TLS error while sending", ok("{}"), False, raising((http.client.HTTPConnection, "send"), eof), "http", "in doubt"),
            ("a TLS handshake that fails", b"plain text, no TLS here", False, None, "https", "not sent"),
            ("the name does not resolve", None, False, raising((socket, "create_connection"), socket.gaierror(-2, "Name unknown")),
             "http", "not sent"),
            ("no route to the host", None, False, raising((socket, "create_connection"), OSError(113, "No route to host")), "http", "not sent"),
            ("connecting times out", None, False, raising((socket, "create_connection"), TimeoutError("timed out")), "http", "not sent"),
            ("the connection is refused", None, False, None, "http", "not sent"),
        ]
        for name, answer, reset, patched, scheme, case in table:
            for method, path, verb in (("POST", "/v1/comments", ("comments", "add", PAGE, "--body", "Ready")),
                                       ("GET", "/v1/comments", ("comments", "list", PAGE))):
                with self.subTest(name, method=method):
                    port, read = self.serve_once(answer, reset) if answer is not None else (refused_port, [])
                    local = f"{scheme}://127.0.0.1:{port}"

                    def transport(wanted, url, headers, body=None, timeout=None):
                        if (wanted, urlsplit(url).path) == (method, path):
                            with (patched or contextlib.nullcontext)():
                                return self.n.urllib_transport(wanted, url.replace(API, local), headers, body, 5)
                        return self.fake(wanted, url, headers, body, timeout)

                    self.n.TRANSPORT = transport
                    code, out, err = self.run_cli(*verb)
                    if method == "POST":
                        self.assertEqual(code, 2 if case == "refused" else 1, err)
                        self.assert_case(case, err)
                        self.assertLessEqual(len(read), 1, "a write is never sent again")
                    else:  # the same failures of a read: one line that says so, and never the words of a write
                        self.assertEqual(code, 2 if case == "refused" else 1, err)
                        self.assertNotRegex(err, r"(?i)in doubt|may have been|nothing changed|never left")
                        self.assertRegex(err, r"could not reach|did not answer|not JSON|Notion answered (302|400|503)")
                        self.assertEqual(len(err.splitlines()), 1, err)

    def test_the_transport_raises_only_its_own_failures(self):
        # download and send read them: Unsent, a timeout or a ConnectionError, whatever the standard library raised.
        bypass = mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"})
        bypass.start()
        self.addCleanup(bypass.stop)
        port, _ = self.serve_once(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
        for kind, error_ in LOST.items():
            if kind == "any other":
                continue
            for target in ("begin", "read"):
                with self.subTest(kind=kind, target=target), mock.patch.object(http.client.HTTPResponse, target, side_effect=error_):
                    with self.assertRaises(TimeoutError if kind == "timeout" else ConnectionError) as raised:
                        self.n.urllib_transport("GET", f"http://127.0.0.1:{port}/x", {}, None, 5)
                    self.assertNotIsInstance(raised.exception, self.n.Unsent)

    def test_a_lost_connection_after_a_write_left_is_in_doubt(self):
        note = self.tmp / "note.md"
        note.write_text("Shipped.\n")
        before = self.fake.markdown[PAGE]
        lost = {kind: ends_in(kind) for kind in (*LOST, *UNREADABLE)}
        for kind, fails in lost.items():
            with self.subTest(update=kind):
                self.fake.overrides.clear()
                self.fake.calls.clear()
                self.fake.markdown[PAGE] = before

                def applied_then_lost(r, fails=fails):
                    self.fake.patch_markdown(PAGE, r.json)
                    return fails(r)

                self.fake.on("PATCH", rf"/v1/pages/{PAGE}/markdown", applied_then_lost)
                code, out, err = self.run_cli("update", PAGE, "--set", "Status=Rollout", "--append-file", note)
                self.assertEqual(code, 4, err)
                self.assertIn("Shipped.", self.fake.markdown[PAGE])
                self.assertEqual(len(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}/markdown")), 1)
                self.assertRegex(err, r"written: properties Status\b")
                self.assertIn("In doubt: body added at the end", err)
                self.assertNotIn("Not written", err)
                self.assertNotIn("nothing changed", err)
            for landed in (True, False):
                with self.subTest(create=kind, landed=landed):
                    self.fake.overrides.clear()
                    self.fake.calls.clear()
                    title = f"Lost {kind} {landed}"

                    def made_then_lost(r, fails=fails, landed=landed):
                        if landed:
                            self.fake.create_page(r.json)
                        return fails(r)

                    self.fake.on("POST", r"/v1/pages", made_then_lost)
                    code, out, err = self.run_cli("create", "--parent", "Tasks", "--set", f"title={title}")
                    self.assertEqual(code, 0 if landed else 1, out + err)
                    self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 1)
                    self.assertIn("found by its title" if landed else f"In doubt: {title!r}", out + err)

        for kind in (*LOST, *UNREADABLE):
            with self.subTest(read=kind):
                self.fake.overrides.clear()
                self.fake.on("GET", rf"/v1/pages/{PAGE}", ends_in(kind))
                if kind == "any other":
                    continue  # not a failure of the connection: the last-resort handler names it
                code, out, err = self.run_cli("fetch", PAGE)
                self.assertEqual(code, 1, err)
                self.assertRegex(err, r"could not reach api\.notion\.com|did not answer|with a body that is not JSON")
                self.assertNotRegex(err, r"(?i)in doubt|may have been|nothing changed")

        pages = self.tmp / "pages.json"
        for landed in (True, False):
            with self.subTest(second_page_landed=landed):
                self.fake.overrides.clear()
                self.fake.calls.clear()
                title = f"Reset landed {landed}"
                pages.write_text(json.dumps([{"properties": {"Task name": title}}] * 3))

                def reset_on_second(r, landed=landed):
                    if len(self.fake.sent("POST", r"/v1/pages")) != 2:
                        return None
                    if landed:
                        self.fake.create_page(r.json)
                    raise ConnectionResetError(104, "Connection reset by peer")

                self.fake.on("POST", r"/v1/pages", reset_on_second)
                code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--pages-file", pages)
                made = [pg for pg in self.fake.pages.values() if self.fake.title_of(pg) == title]
                self.assertNotIn("Not created", err)
                self.assertNotIn("nothing was made", err)
                if landed:  # found by its title, not sent again, and the third page goes on
                    self.assertEqual(code, 0, err)
                    self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 3)
                    self.assertEqual(len(made), 3)
                    self.assertIn("found by its title", out)
                else:
                    self.assertEqual(code, 4, err)
                    self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 2)
                    self.assertEqual(len(made), 1)
                    self.assertIn(f"In doubt: {title!r}", err)
                    self.assertIn(f"not sent: {title!r}", err)


    def test_a_first_write_in_doubt_names_it_and_what_was_never_sent(self):
        note = self.tmp / "note.md"
        note.write_text("Shipped.\n")
        before = self.fake.markdown[PAGE]
        self.fake.on("PATCH", rf"/v1/pages/{PAGE}/markdown", ends_in("504"))
        code, out, err = self.run_cli("update", PAGE, "--edit", "by hand", "manually", "--append-file", note)
        self.assertEqual(code, 1, err)
        self.assertEqual(len(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}/markdown")), 1)
        self.assertEqual(self.fake.markdown[PAGE], before)
        self.assertIn("In doubt: body edits 1 (", err)
        self.assertIn("504", err)
        self.assertIn("fetch the page and check", err)
        self.assertIn("not sent: body added at the end", err)
        self.assertIn("Rerun only what was not sent", err)
        self.assertNotIn("Not written", err)
        self.assertNotIn("updated", out)

        self.fake.overrides.clear()
        self.fake.calls.clear()
        self.fake.on("PATCH", rf"/v1/pages/{PAGE}", ends_in("503"))
        code, out, err = self.run_cli("update", PAGE, "--set", "Status=Rollout", "--prepend-file", note, "--append-file", note)
        self.assertEqual(code, 1, err)
        self.assertIn("In doubt: properties Status (", err)
        self.assertIn("not sent: body added at the start; body added at the end", err)
        self.assertEqual(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}/markdown"), [])

        self.fake.overrides.clear()
        self.fake.calls.clear()
        pages = self.tmp / "pages.json"
        pages.write_text(json.dumps([{"properties": {"Task name": f"First doubt {i}"}} for i in range(3)]))
        self.fake.on("POST", r"/v1/pages", ends_in("503"))
        code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--pages-file", pages)
        self.assertEqual(code, 1, err)
        self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 1)
        self.assertIn("In doubt: 'First doubt 0' (", err)
        self.assertIn("may still appear", err)
        self.assertIn(f"look for a page titled 'First doubt 0' in data source Tasks ({COLLECTION}{DS_TASKS})", err)
        self.assertIn("not sent: 'First doubt 1', 'First doubt 2'", err)
        self.assertIn("Rerun with only the pages not sent", err)
        self.assertNotIn("Not created", err)
        self.assertNotIn("Run the command again", err)


    def test_a_lookup_that_fails_after_a_create_in_doubt_keeps_it_in_doubt(self):
        pages = self.tmp / "pages.json"
        lookups = {"timeout": "did not answer", "reset": "reset", "429": "429"}
        positions = (("alone", 0, 1), ("first of 3", 0, 1), ("second of 3", 1, 4))  # which create is in doubt, exit
        parents = ((COLLECTION + DS_TASKS, "Task name", "POST", rf"/v1/data_sources/{DS_TASKS}/query",
                    f"data source Tasks ({COLLECTION}{DS_TASKS})"),
                   (page_url(PROJECT), "title", "POST", r"/v1/search", f"page {page_url(PROJECT)}"))
        for parent, title_key, method, lookup_path, where in parents:
            for lookup, words in lookups.items():
                for position, doubtful, exit_code in positions:
                    title = f"Lookup {title_key} {lookup} {position}"
                    with self.subTest(parent=title_key, lookup=lookup, position=position):
                        self.fake.overrides.clear()
                        self.fake.calls.clear()
                        posts = []

                        def landed_in_doubt(r, doubtful=doubtful):
                            posts.append(r)
                            if len(posts) - 1 != doubtful:
                                return None
                            self.fake.create_page(r.json)  # it landed: only the answer was lost
                            return error(503, "service_unavailable", "Try again later.")

                        def lookup_fails(r, lookup=lookup):
                            if r.json and r.json.get("filter", {}).get("value") == "data_source":
                                return None  # resolving the parent is not the lookup
                            return ends_in(lookup)(r)

                        self.fake.on("POST", r"/v1/pages", landed_in_doubt)
                        self.fake.on(method, lookup_path, lookup_fails)
                        if position == "alone":
                            args = ("--set", f"{title_key}={title}")
                        else:
                            pages.write_text(json.dumps([{"properties": {title_key: title}}] * 3))
                            args = ("--pages-file", pages)
                        code, out, err = self.run_cli("create", "--parent", parent, *args)
                        self.assertEqual(code, exit_code, err)
                        self.assertEqual(len(posts), doubtful + 1, "the create in doubt is never sent again")
                        self.assertTrue(self.fake.sent(method, lookup_path), "the page was looked for")
                        self.assertIn(f"In doubt: {title!r} (", err)
                        self.assertIn("could not be looked for", err)
                        self.assertIn(words, err)
                        self.assertIn(f"look for a page titled {title!r} in {where} before creating it again", err)
                        for wrong in ("Not created", "nothing was made", "nothing changed", "Run the command again"):
                            self.assertNotIn(wrong, err)
                        if position != "alone":
                            self.assertIn(f"not sent: {title!r}", err)
        for doc in ("SKILL.md", "references/api-limits.md"):
            with self.subTest(doc=doc):
                said = " ".join((SKILL_DIR / doc).read_text(encoding="utf-8").split())
                self.assertRegex(said, r"cannot look \(the search fails, times out or keeps answering 429\), the create "
                                       r"stays `?[Ii]n doubt`?")
                self.assertIn("look for a page with that title in that parent before creating it again", said)


class TransportTest(ClientTestCase):
    def test_429_waits_retry_after_then_succeeds(self):
        answers = [(429, {"object": "error", "status": 429, "code": "rate_limited", "message": "slow down"}, {"Retry-After": "2"}),
                   (429, {"object": "error", "status": 429, "code": "rate_limited", "message": "slow down"}, {"Retry-After": "3"})]
        self.fake.on("GET", r"/v1/users/me", lambda r: answers.pop(0) if answers else None)
        code, out, err = self.run_cli("api", "GET", "/v1/users/me")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.sleeps, [2, 3])
        self.assertEqual(json.loads(out)["id"], BOT)

    def test_429_six_times_exits_1_after_5_retries(self):
        self.fake.on("GET", r"/v1/users/me",
                     lambda r: (429, {"object": "error", "status": 429, "code": "rate_limited", "message": "slow down"}, {"Retry-After": "1"}))
        code, out, err = self.run_cli("api", "GET", "/v1/users/me")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.sleeps), 5)
        self.assertEqual(len(self.fake.sent("GET", r"/v1/users/me")), 6)

    def test_token_only_sent_to_the_api_host(self):
        self.settings(me="ana@example.com")
        self.fake.blocks[uid(0xF1)] = {"object": "block", "id": uid(0xF1), "type": "file",
                                      "file": {"type": "file", "file": {"url": "https://files.example.com/a/report.pdf?sig=1"}, "caption": [], "name": "report.pdf"}}
        self.fake.files["https://files.example.com/a/report.pdf?sig=1"] = b"%PDF-1.4"
        for args in (("fetch", PAGE, "--discussions"), ("query", "Tasks", "--where", "Assignee has me"),
                     ("search", "invoice"), ("whoami",), ("download", uid(0xF1), "-o", self.tmp)):
            code, out, err = self.run_cli(*args)
            self.assertEqual(code, 0, f"{args}: {err}")
        carrying = [c for c in self.fake.calls if "authorization" in c.headers]
        self.assertTrue(carrying)
        for call in carrying:
            self.assertTrue(call.url.startswith(API + "/v1/"), call.url)
            self.assertEqual(call.headers["authorization"], "Bearer " + TOKEN)
            self.assertEqual(call.headers["notion-version"], "2026-03-11")
        self.assertTrue([c for c in self.fake.calls if c.host == "files.example.com"])


class RedirectTest(ClientTestCase):
    """The real transport (urllib_transport and its redirect handler) against two local servers."""

    def serve(self, answer):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
                status, headers, body = answer(self.path)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return "127.0.0.1:%d" % server.server_address[1], seen

    def test_redirect_to_another_host_drops_the_token(self):
        me = json.dumps({"object": "user", "id": BOT, "type": "bot", "name": "Card bot"}).encode()
        other, other_seen = self.serve(lambda path: (200, {"Content-Type": "application/json"}, me))

        def api(path):
            if path == "/v1/users/me":
                return 307, {"Location": f"http://{other}/v1/users/me"}, b""
            if path == "/v1/users/same":
                return 302, {"Location": "/v1/users/landed"}, b""
            return 200, {"Content-Type": "application/json"}, me

        api_host, api_seen = self.serve(api)
        self.n.API_HOST, self.n.API_ROOT = api_host, f"http://{api_host}"
        # The module's own _OPENER, untouched: only the environment keeps a proxy away from 127.0.0.1.
        bypass = mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"})
        bypass.start()
        self.addCleanup(bypass.stop)
        self.n.TRANSPORT = self.n.urllib_transport
        code, out, err = self.run_cli("api", "GET", "/v1/users/me")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["id"], BOT)
        self.assertEqual(api_seen[0][1].get("authorization"), "Bearer " + TOKEN)
        self.assertEqual([path for path, _ in other_seen], ["/v1/users/me"])
        self.assertNotIn("authorization", other_seen[0][1])
        code, out, err = self.run_cli("api", "GET", "/v1/users/same")
        self.assertEqual(code, 0, err)
        landed = [headers for path, headers in api_seen if path == "/v1/users/landed"]
        self.assertEqual(landed[0].get("authorization"), "Bearer " + TOKEN)

    def test_a_redirect_that_changes_the_scheme_drops_the_token(self):
        # Same host and port, another scheme: the token stays behind, both ways. The module's own _OPENER and
        # its redirect handler run; only its HTTPS connection is replaced, since no local server speaks TLS.
        import http.client
        import urllib.request
        import urllib.response

        me = json.dumps({"object": "user", "id": BOT, "type": "bot", "name": "Card bot"}).encode()
        holder = []
        api_host, api_seen = self.serve(lambda path: (302, {"Location": f"https://{holder[0]}/v1/users/landed"}, b"")
                                        if path == "/v1/users/up" else (200, {"Content-Type": "application/json"}, me))
        holder.append(api_host)
        over_tls = []

        def https_open(req):
            over_tls.append((urlsplit(req.full_url).path, {k.lower(): v for k, v in req.header_items()}))
            if urlsplit(req.full_url).path == "/v1/users/down":
                code, headers, body = 302, {"Location": f"http://{api_host}/v1/users/landed"}, b""
            else:
                code, headers, body = 200, {"Content-Type": "application/json"}, me
            message = http.client.HTTPMessage()
            for name, value in headers.items():
                message[name] = value
            answer = urllib.response.addinfourl(io.BytesIO(body), message, req.full_url, code)
            answer.msg = "OK" if code == 200 else "Found"
            return answer

        tls = [h for h in self.n._OPENER.handlers if isinstance(h, urllib.request.HTTPSHandler)][0]
        patcher = mock.patch.object(tls, "https_open", https_open)
        patcher.start()
        self.addCleanup(patcher.stop)
        bypass = mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"})
        bypass.start()
        self.addCleanup(bypass.stop)
        self.n.TRANSPORT = self.n.urllib_transport
        self.n.API_HOST = api_host

        self.n.API_ROOT = f"https://{api_host}"  # https -> http on the same host and port
        code, out, err = self.run_cli("api", "GET", "/v1/users/down")
        self.assertEqual(code, 0, err)
        self.assertEqual(over_tls[0][1].get("authorization"), "Bearer " + TOKEN)
        self.assertEqual([path for path, _ in api_seen], ["/v1/users/landed"])
        self.assertNotIn("authorization", api_seen[0][1])

        over_tls.clear()
        self.n.API_ROOT = f"http://{api_host}"  # http -> https on the same host and port
        code, out, err = self.run_cli("api", "GET", "/v1/users/up")
        self.assertEqual(code, 0, err)
        self.assertEqual(api_seen[-1][0], "/v1/users/up")
        self.assertEqual(api_seen[-1][1].get("authorization"), "Bearer " + TOKEN)
        self.assertEqual([path for path, _ in over_tls], ["/v1/users/landed"])
        self.assertNotIn("authorization", over_tls[0][1])


class QueryTest(ClientTestCase):
    def last_filter(self):
        return self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")[-1].json.get("filter")

    def test_where_compiles_each_example(self):
        self.settings(me="ana@example.com")
        status_done = {"property": "Status", "status": {"equals": "Done"}}
        examples = [
            ("Status = 'Done'", status_done),
            ("Tags has 'Helpdesk'", {"property": "Tags", "multi_select": {"contains": "Helpdesk"}}),
            ("created >= 2026-11-01", {"timestamp": "created_time", "created_time": {"on_or_after": "2026-11-01"}}),
            ("Project has " + page_url(PROJECT), {"property": "Project", "relation": {"contains": PROJECT}}),
            ("\"Task name\" contains 'token'", {"property": "Task name", "title": {"contains": "token"}}),
            ("id in (120, 121)", {"or": [{"property": "Task ID", "unique_id": {"equals": 120}},
                                         {"property": "Task ID", "unique_id": {"equals": 121}}]}),
            ("id = " + key(120), {"property": "Task ID", "unique_id": {"equals": 120}}),
            ("Assignee has me", {"property": "Assignee", "people": {"contains": ANA}}),
            ("\"Done at\" is empty", {"property": "Done at", "date": {"is_empty": True}}),
            ("(Estimate = 1 OR Estimate = 2) AND Status = 'Done'",
             {"and": [{"or": [{"property": "Estimate", "number": {"equals": 1}},
                              {"property": "Estimate", "number": {"equals": 2}}]}, status_done]}),
        ]
        self.assertEqual(len(examples), 10)
        for expression, expected in examples:
            with self.subTest(where=expression):
                code, out, err = self.run_cli("query", COLLECTION + DS_TASKS, "--where", expression)
                self.assertEqual(code, 0, err)
                self.assertEqual(self.last_filter(), expected)

    def test_where_sends_a_date_as_it_was_written(self):
        # Notion reads a date-only value as a UTC day and an instant by its offset: neither is changed on the way.
        for value in ("2026-11-03", "2026-11-03T00:00:00-03:00", "2026-11-03T00:00:00Z", "one_week_ago"):
            with self.subTest(value=value):
                code, out, err = self.run_cli("query", "Tasks", "--where", f"created >= {value} AND \"Done at\" < {value}")
                self.assertEqual(code, 0, err)
                self.assertEqual(self.last_filter(), {"and": [
                    {"timestamp": "created_time", "created_time": {"on_or_after": value}},
                    {"property": "Done at", "date": {"before": value}}]})

    def test_query_sends_the_compiled_filter(self):
        code, out, err = self.run_cli("query", "Tasks", "--where",
                                      "Status = 'Done' AND Tags has 'Helpdesk' AND created >= 2026-11-01")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.last_filter(), {"and": [
            {"property": "Status", "status": {"equals": "Done"}},
            {"property": "Tags", "multi_select": {"contains": "Helpdesk"}},
            {"timestamp": "created_time", "created_time": {"on_or_after": "2026-11-01"}},
        ]})
        self.assertIn("Export invoices", out)

    def test_where_in_compiles_to_an_or_of_single_values(self):
        properties = self.fake.data_sources[DS_TASKS]["properties"]
        properties["Kind"] = {"id": "kd", "name": "Kind", "type": "select",
                              "select": {"options": [option("Bug", 0), option("Feature", 1)]}}
        properties["Score"] = {"id": "sc", "name": "Score", "type": "formula", "formula": {"expression": "1"}}

        def any_of(name, kind, op, values):
            return {"or": [{"property": name, kind: {op: v}} for v in values]}

        examples = [
            ("Status in ('Done', 'Rollout')", any_of("Status", "status", "equals", ["Done", "Rollout"])),
            ("Kind in ('Bug', 'Feature')", any_of("Kind", "select", "equals", ["Bug", "Feature"])),
            ("Tags in ('Backend', 'Helpdesk')", any_of("Tags", "multi_select", "contains", ["Backend", "Helpdesk"])),
            ("Estimate in (1, 2, 3)", any_of("Estimate", "number", "equals", [1, 2, 3])),
            ("Assignee in (user://" + ANA + ", user://" + BRUNO + ")", any_of("Assignee", "people", "contains", [ANA, BRUNO])),
            ("Project in (" + page_url(PROJECT) + ", " + page_url(WIKI) + ")",
             any_of("Project", "relation", "contains", [PROJECT, WIKI])),
            ("Status in ('Done')", {"property": "Status", "status": {"equals": "Done"}}),
            ("Status in ('Done', 'Rollout') AND Tags has 'Backend'",
             {"and": [any_of("Status", "status", "equals", ["Done", "Rollout"]),
                      {"property": "Tags", "multi_select": {"contains": "Backend"}}]}),
            ("Status in ('Done', 'Rollout') OR Estimate = 1",
             {"or": [{"property": "Status", "status": {"equals": "Done"}},
                     {"property": "Status", "status": {"equals": "Rollout"}},
                     {"property": "Estimate", "number": {"equals": 1}}]}),
        ]
        for expression, expected in examples:
            with self.subTest(where=expression):
                code, out, err = self.run_cli("query", COLLECTION + DS_TASKS, "--where", expression)
                self.assertEqual(code, 0, err)
                self.assertEqual(self.last_filter(), expected)
        self.fake.calls.clear()
        refused = [
            ("(Estimate = 1 AND Status in ('Done', 'Rollout')) OR Notes contains 'x'", "Status in ('Done', 'Rollout')"),
            ("Score in (1, 2)", "Score"),
        ]
        for expression, named in refused:
            with self.subTest(refused=expression):
                code, out, err = self.run_cli("query", COLLECTION + DS_TASKS, "--where", expression)
                self.assertEqual(code, 2, err)
                self.assertIn(named, err)
        self.assertEqual(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query"), [])

    def test_where_errors_exit_2_and_send_nothing(self):
        cases = [
            ("Stauts = 'Done'", "Stauts"),
            ("Tags > 3", ">"),
            ("((Estimate = 1 OR Estimate = 2) AND Status = 'Done') OR Notes contains 'x'", "nest"),
            ("Status = ", "Status"),
        ]
        for expression, named in cases:
            with self.subTest(where=expression):
                code, out, err = self.run_cli("query", "Tasks", "--where", expression)
                self.assertEqual(code, 2)
                self.assertIn(named, err)
        self.assertEqual(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query"), [])

    def test_where_refuses_a_type_the_api_cannot_filter(self):
        # A type with no filter (a place) is refused here: the API answers a page of alternatives that name none.
        self.fake.data_sources[DS_TASKS]["properties"]["Where"] = {"id": "pl", "name": "Where", "type": "place", "place": {}}
        for where in ("Where is empty", "Where is not empty", "Where = 'x'"):
            with self.subTest(where=where):
                code, out, err = self.run_cli("query", "Tasks", "--where", where)
                self.assertEqual(code, 2)
                self.assertIn("Where is a place property, which the", err)
        self.assertEqual(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query"), [])

    def rows(self, statuses):
        for i, status in enumerate(statuses):
            self.fake.add_page(task_page(uid(0x10000 + i), 1000 + i, f"Row {i}", status=status))

    def test_query_count_pages_through_250_rows(self):
        self.fake.pages.clear()
        self.rows(["Done"] * 250)
        code, out, err = self.run_cli("query", "Tasks", "--count")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "250")
        self.assertEqual(len(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")), 3)

    def test_query_group_by_counts_largest_first(self):
        self.fake.pages.clear()
        self.rows(["In progress"] * 20 + ["Done"] * 180 + ["Rollout"] * 50)
        code, out, err = self.run_cli("query", "Tasks", "--group-by", "Status")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip().splitlines(), ["Done 180", "Rollout 50", "In progress 20"])

    def test_query_prints_50_rows_and_says_how_many_more(self):
        self.fake.pages.clear()
        self.rows(["Done"] * 120)
        code, out, err = self.run_cli("query", "Tasks")
        self.assertEqual(code, 0, err)
        self.assertEqual(sum(1 for line in out.splitlines() if "https://" in line), 50)
        self.assertIn("70 more", out)
        code, out, err = self.run_cli("query", "Tasks", "--limit", "5")
        self.assertEqual(sum(1 for line in out.splitlines() if "https://" in line), 5)
        self.assertIn("115 more", out)

    def test_query_stops_at_2000_rows_unless_max_rows(self):
        endless = [task_page(uid(0x20000 + i), 3000 + i, f"Row {i}") for i in range(100)]
        self.fake.on("POST", rf"/v1/data_sources/{DS_TASKS}/query",
                     lambda r: (200, {"object": "list", "results": endless, "has_more": True, "next_cursor": "more"}))
        code, out, err = self.run_cli("query", "Tasks", "--count")
        self.assertEqual(code, 0, err)
        self.assertIn("2000", out)
        self.assertIn("stopped paging at 2000 rows", out + err)
        self.assertEqual(len(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")), 20)
        self.fake.calls.clear()
        code, out, err = self.run_cli("query", "Tasks", "--count", "--max-rows", "2500")
        self.assertIn("2500", out)
        self.assertEqual(len(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")), 25)

    def test_query_order_and_select(self):
        code, out, err = self.run_cli("query", "Tasks", "--order", "Estimate desc", "--select", "Status,Tags")
        self.assertEqual(code, 0, err)
        sent = self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")[-1].json
        self.assertEqual(sent["sorts"], [{"property": "Estimate", "direction": "descending"}])
        lines = out.splitlines()
        self.assertEqual(lines[0], "Status | Tags | url")
        self.assertIn("Done | Backend | " + self.page["url"], lines)
        self.assertNotIn("Export invoices", out)
        self.run_cli("query", "Tasks", "--order", "created desc")
        sent = self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")[-1].json
        self.assertEqual(sent["sorts"], [{"timestamp": "created_time", "direction": "descending"}])

    def test_select_takes_every_name_where_and_order_take(self):
        # Every built-in name --where and --order accept is a --select column too and prints the page's own value.
        self.page["last_edited_time"] = "2026-11-21T08:15:00.000Z"
        made, edited = self.page["created_time"], self.page["last_edited_time"]
        table = [("created", "created_time", made), ("Created", "created_time", made),
                 ("created_time", "created_time", made), ("edited", "last_edited_time", edited),
                 ("last_edited", "last_edited_time", edited), ("last_edited_time", "last_edited_time", edited),
                 ("updated", "last_edited_time", edited), ("Updated", "last_edited_time", edited),
                 ("id", "Task ID", key(120)), ("key", "Task ID", key(120)),
                 ("title", "Task name", "Export invoices"), ("name", "Task name", "Export invoices")]
        for wanted, label, value in table:
            with self.subTest(select=wanted):
                if label.endswith("_time"):  # --where and --order take it, so --select does
                    code, out, err = self.run_cli("query", "Tasks", "--where", f"{wanted} >= 2026-01-01", "--order", f"{wanted} desc")
                    self.assertEqual(code, 0, err)
                code, out, err = self.run_cli("query", "Tasks", "--select", wanted)
                self.assertEqual(code, 0, err)
                self.assertEqual(out.splitlines()[:2], [f"{label} | url", f"{value} | {self.page['url']}"])
                code, out, err = self.run_cli("query", "Tasks", "--select", wanted, "--json")
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)[0]["properties"], {label: value})

    def test_select_prefers_a_property_of_the_same_name_as_where_does(self):
        self.page["last_edited_time"] = "2026-11-21T08:15:00.000Z"
        self.fake.data_sources[DS_TASKS]["properties"]["Updated"] = {"id": "up", "name": "Updated", "type": "rich_text", "rich_text": {}}
        self.page["properties"]["Updated"] = {"id": "up", "type": "rich_text", "rich_text": text("by hand")}
        for wanted in ("updated", "Updated"):
            with self.subTest(select=wanted):
                code, out, err = self.run_cli("query", "Tasks", "--select", wanted)
                self.assertEqual(code, 0, err)
                self.assertEqual(out.splitlines()[:2], ["Updated | url", f"by hand | {self.page['url']}"])
                code, out, err = self.run_cli("query", "Tasks", "--where", f"{wanted} contains hand")
                self.assertEqual(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")[-1].json["filter"],
                                 {"property": "Updated", "rich_text": {"contains": "hand"}})
        code, out, err = self.run_cli("query", "Tasks", "--select", "edited")  # no property of that name: the page's value
        self.assertEqual(out.splitlines()[:2], ["last_edited_time | url", f"2026-11-21T08:15:00.000Z | {self.page['url']}"])


class JsonOutputTest(ClientTestCase):
    def test_json_stdout_is_one_document_for_every_verb_that_takes_json(self):
        # Over every verb whose parser has --json: stdout parses as one JSON document, notes go to stderr.
        for i in range(60):
            self.fake.add_page(task_page(uid(0x10000 + i), 1000 + i, f"Row {i}", status="Rollout"))
        self.fake.on("POST", rf"/v1/data_sources/{DS_PROJECTS}/query",
                     lambda r: (200, {"object": "list", "results": [], "has_more": False, "next_cursor": None}))
        rows = [
            (("fetch", PAGE), dict, ""),
            (("fetch", PAGE, "--discussions"), dict, ""),
            (("fetch", PAGE, "--props-only"), dict, ""),
            (("fetch", "Tasks"), dict, ""),
            (("query", "Tasks"), list, "11 more rows matched"),
            (("query", "Tasks", "--limit", "5"), list, "56 more rows matched"),
            (("query", "Tasks", "--limit", "0"), list, "61 more rows matched"),
            (("query", "Tasks", "--max-rows", "20"), list, "stopped paging at 20 rows"),
            (("query", "Projects"), list, "no row matched"),
            (("query", "Tasks", "--count"), int, ""),
            (("query", "Tasks", "--count", "--max-rows", "20"), int, "stopped paging at 20 rows"),
            (("query", "Projects", "--count"), int, ""),
            (("query", "Tasks", "--group-by", "Status"), dict, ""),
            (("query", "Tasks", "--group-by", "Status", "--max-rows", "20"), dict, "stopped paging at 20 rows"),
            (("query", "Projects", "--group-by", "Project ID"), dict, ""),
        ]
        sub = next(a for a in self.n.build_parser()._actions if hasattr(a, "choices") and isinstance(a.choices, dict))
        takes_json = {name for name, p in sub.choices.items() if "--json" in p._option_string_actions}
        self.assertEqual({args[0] for args, *_ in rows}, takes_json)
        for args, kind, note in rows:
            with self.subTest(args=args):
                code, out, err = self.run_cli(*args, "--json")
                self.assertEqual(code, 0, err)
                self.assertIsInstance(json.loads(out), kind)
                self.assertIn(note, err)
                if not note:
                    self.assertEqual(err, "")
                plain_code, plain_out, plain_err = self.run_cli(*args)
                self.assertEqual((plain_code, plain_err), (0, ""))
                self.assertIn(note, plain_out)
        code, out, err = self.run_cli("query", "Tasks", "--group-by", "Status", "--json")
        self.assertEqual(list(json.loads(out).items()), [("Rollout", 60), ("Done", 1)])
        code, out, err = self.run_cli("fetch", uid(0xDEAD), "--json")
        self.assertEqual((code, out), (1, ""))


class SearchTest(ClientTestCase):
    def setUp(self):
        super().setUp()
        self.noted = self.fake.add_page(task_page(uid(0x121), 121, "Close the month", notes="Check every invoice twice"))
        self.wiki = self.fake.add_page(child_page(uid(0x7002), "Invoice glossary", WIKI))
        rows = {DS_TASKS: [self.page, self.noted], DS_PROJECTS: []}
        self.fake.on("POST", r"/v1/data_sources/([^/]+)/query",
                     lambda r: (200, {"object": "list", "results": rows[r.path.split("/")[3]], "has_more": False, "next_cursor": None})
                     if "unique_id" not in json.dumps((r.json or {}).get("filter")) else None)

    def hits(self, out):
        return [line for line in out.splitlines() if "https://" in line]

    def test_search_merges_title_and_rows_deduplicated(self):
        code, out, err = self.run_cli("search", "invoice")
        self.assertEqual(code, 0, err)
        hits = self.hits(out)
        self.assertEqual(len(hits), 3)
        self.assertEqual(len([h for h in hits if self.page["url"] in h]), 1)
        noted = [h for h in hits if self.noted["url"] in h][0]
        self.assertIn("matched: Notes", noted)
        self.assertIn("Tasks", noted)
        wiki = [h for h in hits if self.wiki["url"] in h][0]
        self.assertIn("matched: title", wiki)

    def test_search_says_when_a_title_only_resembles_the_words(self):
        # The API's search ranks by likeness: it returns titles that hold none of the words as written.
        self.fake.on("POST", r"/v1/search", lambda r: (200, {"object": "list", "results": [self.wiki, self.noted],
                                                             "has_more": False, "next_cursor": None})
                     if (r.json or {}).get("query") else None)
        code, out, err = self.run_cli("search", "invoice glossary")
        self.assertEqual(code, 0, err)
        by_url = {url: line for line in self.hits(out) for url in (self.wiki["url"], self.noted["url"]) if url in line}
        self.assertTrue(by_url[self.wiki["url"]].endswith("matched: title"))
        self.assertTrue(by_url[self.noted["url"]].endswith("matched: similar title"))

    def test_search_says_at_least_when_a_source_was_cut_short(self):
        def tasks_answer(rows, more=False):
            def answer(r):
                tasks = r.path.split("/")[3] == DS_TASKS
                return 200, {"object": "list", "results": rows if tasks else [],
                             "has_more": more and tasks, "next_cursor": "next" if more and tasks else None}
            self.fake.on("POST", r"/v1/data_sources/([^/]+)/query", answer)

        code, out, err = self.run_cli("search", "invoice", "--limit", "2")  # every source gave all it has: the count is exact
        self.assertEqual(code, 0, err)
        self.assertIn("… 1 more hits (--limit N shows them)", out.splitlines())
        third = self.fake.add_page(task_page(uid(0x122), 122, "Invoice backlog"))
        cuts = {"a source answered more rows than --limit": (lambda: tasks_answer([self.page, self.noted, third])),
                "a source has more pages": (lambda: tasks_answer([self.page, self.noted], more=True))}
        for name, cut in cuts.items():
            with self.subTest(name):
                cut()
                code, out, err = self.run_cli("search", "invoice", "--limit", "2")
                self.assertEqual(code, 0, err)
                self.assertIn("… at least 1 more hits (--limit N shows them)", out.splitlines())

    def test_search_key_first_and_page_url(self):
        code, out, err = self.run_cli("search", key(121))
        self.assertEqual(code, 0, err)
        self.assertIn(self.noted["url"], self.hits(out)[0])
        code, out, err = self.run_cli("search", page_url(PAGE))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.hits(out)), 1)
        self.assertIn(self.page["url"], self.hits(out)[0])

    def test_search_in_data_source_only(self):
        code, out, err = self.run_cli("search", "invoice", "--in", COLLECTION + DS_TASKS)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.sent("POST", r"/v1/search"), [])
        hits = self.hits(out)
        self.assertEqual(len(hits), 2)
        self.assertFalse([h for h in hits if self.wiki["url"] in h])
        code, out, err = self.run_cli("search", "nothing matches this")
        self.assertEqual(code, 0)


class CommentsTest(ClientTestCase):
    def test_comments_add_and_reply(self):
        self.settings(me="ana@example.com")
        code, out, err = self.run_cli("comments", "add", page_url(PAGE), "--body", "Ready for review")
        self.assertEqual(code, 0, err)
        sent = self.fake.sent("POST", r"/v1/comments")[-1].json
        self.assertEqual(sent["parent"], {"page_id": PAGE})
        self.assertEqual(sent["markdown"], "Ready for review")
        self.assertEqual(sent["markdown_version"], "v2")
        created = self.fake.comments[PAGE][-1]
        self.assertIn(created["id"], out)
        body = self.tmp / "reply.md"
        body.write_text("Merged **today**")
        code, out, err = self.run_cli("comments", "reply", created["discussion_id"], "--body-file", body)
        self.assertEqual(code, 0, err)
        sent = self.fake.sent("POST", r"/v1/comments")[-1].json
        self.assertEqual(sent["discussion_id"], created["discussion_id"])
        self.assertNotIn("parent", sent)
        self.assertEqual(sent["markdown"], "Merged **today**")

    def test_a_link_in_a_comment_is_printed_as_text_properties_print_it(self):
        discussion = uid(0xC0)
        runs = [run("see "), run("the ", "https://example.com/a"), run("runbook", "https://example.com/a", bold=True),
                run(" or "), run("write", "mailto:ana@example.com"), run(" now")]
        printed = "see [the runbook](https://example.com/a) or [write](mailto:ana@example.com) now"
        self.fake.comments[PAGE] = [{"object": "comment", "id": uid(0xC1), "discussion_id": discussion,
                                     "created_by": {"object": "user", "id": ANA}, "rich_text": runs}]
        self.assertEqual(self.n.linked(runs), printed)  # the one renderer text properties use
        code, out, err = self.run_cli("comments", "list", PAGE)
        self.assertEqual(code, 0, err)
        self.assertIn(f"  Ana Lima [{uid(0xC1)}]: {printed}", out.splitlines())
        code, out, err = self.run_cli("fetch", PAGE, "--discussions")
        self.assertEqual(code, 0, err)
        self.assertIn(f"  Ana Lima: {printed}", out.splitlines())
        code, out, err = self.run_cli("fetch", PAGE, "--discussions", "--json")
        self.assertEqual(json.loads(out)["discussions"][discussion][0]["rich_text"], runs)  # the raw runs keep their address

    def test_a_comment_added_with_a_link_reads_back_in_the_same_form(self):
        said = "Docs are at [the runbook](https://example.com/runbook) now"
        code, out, err = self.run_cli("comments", "add", PAGE, "--body", said)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.comments[PAGE][-1]["rich_text"][1]["text"]["link"], {"url": "https://example.com/runbook"})
        for command in (("comments", "list", PAGE), ("fetch", PAGE, "--discussions")):
            with self.subTest(command=command):
                code, out, err = self.run_cli(*command)
                self.assertEqual(code, 0, err)
                self.assertTrue(any(line.endswith(": " + said) for line in out.splitlines()), out)

    def test_an_empty_comment_is_refused_and_not_sent(self):
        # The API accepts an empty comment and posts it, so the client does not send one.
        blank = self.tmp / "blank.md"
        blank.write_text(" \n")
        for action, target in (("add", PAGE), ("reply", uid(0xCA)), ("edit", uid(0xC9))):
            for body in (("--body", ""), ("--body", "  "), ("--body-file", blank)):
                with self.subTest(action=action, body=body):
                    code, out, err = self.run_cli("comments", action, target, *body)
                    self.assertEqual(code, 2)
                    self.assertIn("nothing was sent", err)
        self.assertEqual(self.writes(), [])

    def test_comment_display_name_by_token_kind(self):
        self.settings(me="ana@example.com")
        self.run_cli("comments", "add", PAGE, "--body", "one")
        self.assertEqual(self.fake.sent("POST", r"/v1/comments")[-1].json["display_name"],
                         {"type": "custom", "custom": {"name": "Ana Lima"}})
        self.fake.me = {"object": "user", "id": BOT, "type": "bot", "name": "Ana's token",
                        "bot": {"owner": {"type": "user", "user": USERS[ANA]}, "workspace_name": None}}
        shutil.rmtree(self.home / ".cache", ignore_errors=True)
        self.run_cli("comments", "add", PAGE, "--body", "two")
        self.assertNotIn("display_name", self.fake.sent("POST", r"/v1/comments")[-1].json)
        self.fake.me = FakeNotion().me
        shutil.rmtree(self.home / ".cache", ignore_errors=True)
        self.settings(me="ana@example.com", stamp_comments="off")
        self.run_cli("comments", "add", PAGE, "--body", "three")
        self.assertNotIn("display_name", self.fake.sent("POST", r"/v1/comments")[-1].json)

    def test_comments_edit_other_author_exits_1(self):
        theirs = {"object": "comment", "id": uid(0xC9), "discussion_id": uid(0xCA),
                  "created_by": {"object": "user", "id": ANA}, "rich_text": text("Written by a person")}
        self.fake.comments[PAGE] = [theirs]
        code, out, err = self.run_cli("comments", "edit", theirs["id"], "--body", "changed")
        self.assertEqual(code, 1)
        self.assertIn("own comments", err)
        self.assertEqual(self.fake.sent("PATCH", r"/v1/comments/.*"), [])
        mine = dict(theirs, id=uid(0xCB), created_by={"object": "user", "id": BOT})
        self.fake.comments[PAGE].append(mine)
        code, out, err = self.run_cli("comments", "edit", mine["id"], "--body", "changed")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.sent("PATCH", r"/v1/comments/.*")[-1].json["markdown"], "changed")


class FilesTest(ClientTestCase):
    def test_upload_prints_markdown_line(self):
        shot = self.tmp / "screen.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\nfake image")
        code, out, err = self.run_cli("upload", shot)
        self.assertEqual(code, 0, err)
        created = self.fake.sent("POST", r"/v1/file_uploads")[-1]
        self.assertEqual(created.json["filename"], "screen.png")
        self.assertEqual(created.json["content_type"], "image/png")
        upload_id = created.path and self.fake.sent("POST", r"/v1/file_uploads/[^/]+/send")[-1].path.split("/")[3]
        sent = self.fake.sent("POST", r"/v1/file_uploads/[^/]+/send")[-1]
        self.assertTrue(sent.headers["content-type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b"fake image", sent.raw)
        self.assertIn(b'name="file"; filename="screen.png"', sent.raw)
        self.assertIn(f"![screen.png](file-upload://{upload_id})", out)
        for odd in ("a]b[c.png", "a`b.png", "a`b].txt", "x<y>.txt", "[[.png", "a (1) é.png"):  # the printed line is always a file
            with self.subTest(name=odd):
                (self.tmp / odd).write_bytes(b"x")
                code, out, err = self.run_cli("upload", self.tmp / odd)
                line = next(line for line in out.splitlines() if line.startswith(("!", "<")))
                got, files = self.n.hold_files("a ` b\n\n```\ncode\n```\n\n" + line, "body.md")
                self.assertEqual(len(files), 1, line)

    def placed(self, page_id):
        """(type, uploaded or external address) of each media block of a page, in its toggles too."""
        found = []
        for block in self.fake.children.get(page_id, []):
            content = block[block["type"]]
            if block["type"] in self.n.MEDIA:
                found.append((block["type"], content[content["type"]]["url"].split("?")[0]))
            found += self.placed(block["id"])
        return found

    def test_the_line_upload_prints_places_the_file_in_a_body(self):
        # The markdown endpoints store file-upload:// as an empty block: the client gives the block its file.
        image, note = self.tmp / "screen.png", self.tmp / "note.txt"
        image.write_bytes(b"png")
        note.write_bytes(b"text")
        lines = {}
        for path in (image, note):
            code, out, err = self.run_cli("upload", path)
            lines[path.name] = next(line for line in out.splitlines() if line.startswith(("!", "<")))
        ids = {name: re.search(r"file-upload://([0-9a-f-]+)", line).group(1) for name, line in lines.items()}
        hosted = {name: "https://files.example.com/" + i for name, i in ids.items()}
        body = self.tmp / "body.md"
        body.write_text("Shot:\n\n" + lines["screen.png"] + "\n\n<toggle>\nMore\n\n" + lines["note.txt"] + "\n</toggle>\n\n"
                        "```\n" + lines["screen.png"] + "\n```\n\n![out](https://example.com/out.png)\n")
        expected = [("image", hosted["screen.png"]), ("file", hosted["note.txt"]), ("image", "https://example.com/out.png")]
        for verb in (("update", PAGE, "--replace-file", body), ("create", "--parent", "Tasks", "--set", "title=With files",
                                                                  "--body-file", body)):
            with self.subTest(verb=verb[0]):
                self.fake.calls.clear()
                code, out, err = self.run_cli(*verb)
                self.assertEqual(code, 0, err)
                self.assertIn("uploaded files placed: 2", out)
                page = PAGE if verb[0] == "update" else list(self.fake.pages)[-1]
                placed = self.placed(page)
                self.assertEqual(sorted(p for p in placed if p != ("image", "")), sorted(expected))
                sent = [c.json for c in self.fake.sent("PATCH", r"/v1/blocks/[^/]+")]
                self.assertEqual(sent, [{"image": {"file_upload": {"id": ids["screen.png"]}}},
                                        {"file": {"file_upload": {"id": ids["note.txt"]}}}])
        (self.tmp / "plain.md").write_text("One line")
        self.run_cli("update", PAGE, "--replace-file", self.tmp / "plain.md")
        code, out, err = self.run_cli("update", PAGE, "--edit", "One line", lines["screen.png"])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.placed(PAGE), [("image", hosted["screen.png"])])
        self.fake.calls.clear()
        code, out, err = self.run_cli("update", PAGE, "--replace-file", self.tmp / "plain.md")
        self.assertEqual(self.fake.sent("GET", r"/v1/blocks/.*"), [])  # no upload, no extra read

    def test_an_upload_that_cannot_be_placed_exits_4_saying_what_landed(self):
        # Three files; the request that places the 1st, the 2nd or the 3rd ends in each way a write can end. Whatever
        # lands is named as written, the failing one is in its own case, the later ones were not sent, and the
        # commands of the message finish the job.
        names = {uid(0xA001): "one.png", uid(0xA002): "two.txt", uid(0xA003): "three.png"}
        text_ = ("\n\n".join(f"![{name}](file-upload://{i})" if name.endswith("png") else f'<file source="file-upload://{i}">{name}</file>'
                             for i, name in names.items()))
        body, pages = self.tmp / "body.md", self.tmp / "pages.json"
        body.write_text(text_)
        pages.write_text(json.dumps([{"properties": {"Task name": "First"}, "content": text_}, {"properties": {"Task name": "Second"}}]))
        verbs = {  # name -> arguments, what was written before the files
            "replace": (("update", PAGE, "--set", "Status=Rollout", "--replace-file", body), "written: properties Status; body replaced"),
            "append": (("update", PAGE, "--append-file", body), "written: body added at the end"),
            "prepend": (("update", PAGE, "--prepend-file", body), "written: body added at the start"),
            "edit": (("update", PAGE, "--edit", "by hand", "by hand.\n\n" + text_ + "\n\n"), "written: body edits 1"),
            "create": (("create", "--parent", "Tasks", "--set", "title=With files", "--body-file", body), "written: created "),
            "pages": (("create", "--parent", "Tasks", "--pages-file", pages), "written: created "),
        }
        for verb, (args, before) in verbs.items():
            for failing in (1, 2, 3):
                for outcome, case in dict(WRITE_OUTCOMES, **{"401": "refused"}).items():
                    with self.subTest(verb=verb, failing=failing, outcome=outcome):
                        self.fake.overrides.clear()
                        self.fake.calls.clear()
                        self.fake.markdown[PAGE] = "## Context\n\nThe finance team exports invoices by hand.\n"
                        state, fails = {"sent": 0}, ends_in(outcome)

                        def place(r, state=state, fails=fails, failing=failing):
                            state["sent"] += 1
                            return fails(r) if state["sent"] >= failing else None

                        self.fake.on("PATCH", r"/v1/blocks/[^/]+", place)
                        code, out, err = self.run_cli(*args)
                        self.assertEqual(code, 4, err)
                        self.assertIn(before, err)
                        self.assertNotRegex(err, r"nothing changed|never left this machine|nothing was made")
                        page = PAGE if verb not in ("create", "pages") else list(self.fake.pages)[-1]
                        blocks = {b["id"]: b for b in self.fake.children[page]}
                        label = {"refused": "Not written", "not sent": "Not sent", "in doubt": "In doubt"}[case]
                        for place_, (upload, name) in enumerate(names.items(), 1):
                            said = f"file '{name}' ({upload})"
                            if place_ < failing:
                                self.assertRegex(err, rf"written: .*{re.escape(said)} placed in block .*\. {label}: ")
                            elif place_ == failing:
                                self.assertRegex(err, rf"{label}: {re.escape(said)} in block ")
                                self.assertNotIn(f"{said} placed", err)
                            else:
                                self.assertRegex(err, rf"not sent: .*{re.escape(said)} in block ")
                                self.assertNotIn(f"{said} placed", err)
                        self.assertTrue(blocks)
                        if verb == "pages":
                            self.assertIn("the create of 'Second'", err)
                            self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 1)
                        commands = self.commands(err)
                        self.assertEqual([c[-1] for c in commands], [f"file-upload://{u}" for u in list(names)[failing - 1:]])
                        self.fake.overrides.clear()
                        for command in commands:
                            code, out, err = self.run_cli(*command)
                            self.assertEqual(code, 0, err)
                            self.assertIn("uploaded files placed: 1", out)
                        self.assert_all_placed(page, names)
                        for command in commands:  # safe to run again: there is nothing left to place
                            code, out, err = self.run_cli(*command)
                            self.assertEqual(code, 1, err)
                            self.assertIn("no edit matched the body, so nothing was changed", err)

    def test_files_that_cannot_be_read_back_are_named_with_the_command_that_places_them(self):
        upload, body = uid(0xF11E), self.tmp / "body.md"
        body.write_text(f"![a](file-upload://{upload})")
        for status in (403, 404, "timeout", "tls eof"):
            for when in ("to place", "to confirm"):
                with self.subTest(status=status, when=when):
                    self.fake.overrides.clear()
                    self.fake.calls.clear()
                    reads, fails = [], (ends_in(status) if isinstance(status, str) else lambda r, s=status: error(s, "restricted_resource", "No."))

                    def read(r, reads=reads, fails=fails, when=when):
                        reads.append(r)
                        return fails(r) if when == "to place" or len(reads) > 1 else None

                    self.fake.on("GET", rf"/v1/blocks/{PAGE}/children", read)
                    code, out, err = self.run_cli("update", PAGE, "--set", "Status=Rollout", "--replace-file", body)
                    self.assertEqual(code, 4, err)
                    self.assertNotRegex(err, r"nothing changed|never left this machine")
                    placed = self.fake.sent("PATCH", r"/v1/blocks/[^/]+")
                    if when == "to place":
                        self.assertEqual(placed, [])
                        self.assertIn(f"Not sent: file 'a' ({upload}) (the page could not be read to place them", err)
                        self.assertIn("The page still holds the placeholder", err)
                        self.assertEqual(self.commands(err), [["update", self.page["url"], "--edit",
                                                               f"https://file-upload.invalid/{upload}", f"file-upload://{upload}"]])
                    else:
                        self.assertEqual(len(placed), 1)
                        self.assertIn(f"file 'a' ({upload}) placed in block", err)
                        self.assertIn("Not confirmed: the page could not be read again", err)
                    self.assertNotIn("uploaded files placed", out)

    def test_a_placeholder_left_after_placing_exits_4_naming_the_file_and_the_command(self):
        one, two = uid(0xF11E), uid(0xF12E)
        body = self.tmp / "body.md"
        # a block that took its file and still holds the placeholder
        body.write_text(f"![a](file-upload://{one})\n\n![b](file-upload://{two})\n")
        self.fake.on("PATCH", r"/v1/blocks/[^/]+", lambda r: (200, {}) if two in json.dumps(r.json) else None)
        code, out, err = self.run_cli("update", PAGE, "--replace-file", body)
        self.assertEqual(code, 4, err)
        self.assertIn(f"file 'a' ({one}) placed in block", err)
        self.assertRegex(err, rf"In doubt: file 'b' \({two}\) in block .*still holds the placeholder")
        self.assertEqual([c[-1] for c in self.commands(err)], [f"file-upload://{two}"])
        self.fake.overrides.clear()
        # a reference that lands where no block is made of it: the new text of an edit, inside a fence of the page
        self.fake.markdown[PAGE] = "Intro\n\n```\nHERE\n```\n"
        for first in (True, False):  # with a file that can be placed, and alone
            with self.subTest(with_another=first):
                self.fake.calls.clear()
                args = ("--prepend-file", body) if first else ()
                body.write_text(f"![a](file-upload://{one})\n")
                code, out, err = self.run_cli("update", PAGE, *args, "--edit", "HERE" if first else "Intro", f"![b](file-upload://{two})"
                                              if first else f"text\n\n```\n![b](file-upload://{two})\n```")
                if not first:
                    self.assertEqual(code, 0, err)  # in code: text, and no file of this command
                    continue
                self.assertEqual(code, 4, err)
                self.assertIn("written: body edits 1", err)
                self.assertRegex(err, rf"Not sent: file 'b' \({two}\) \(.*stands in a code block")
                self.assertIn(f"![b](file-upload://{two})", err)
                self.assertIn("--append-file", err)
                self.assertIn("not sent: body added at the start", err)
                self.assertNotRegex(err, r"nothing changed|never left this machine")
        # a file no block was made of at all
        self.fake.store_blocks = lambda identifier, markdown: self.fake.children.__setitem__(identifier, [])
        body.write_text(f"![a](file-upload://{one})\n")
        code, out, err = self.run_cli("update", PAGE, "--replace-file", body)
        self.assertEqual(code, 4, err)
        self.assertIn(f"Not sent: file 'a' ({one}) (no block of the page holds file 'a' ({one}))", err)

    def test_a_rerun_never_leaves_a_placeholder_nor_takes_one_for_another_file(self):
        one, two = uid(0xF11E), uid(0xF12E)
        start, note, other = "## Context\n", self.tmp / "note.md", self.tmp / "other.md"
        note.write_text(f"![a](file-upload://{one})\n")
        other.write_text(f"![b](file-upload://{two})\n")

        def lost_placement():
            self.fake.overrides.clear()
            self.fake.on("PATCH", r"/v1/blocks/[^/]+", ends_in("503"))

        # append, its placement lost, then the same append again
        self.fake.markdown[PAGE] = start
        lost_placement()
        code, out, err = self.run_cli("update", PAGE, "--append-file", note)
        self.assertEqual(code, 4, err)
        self.fake.overrides.clear()
        code, out, err = self.run_cli("update", PAGE, "--append-file", note)
        self.assertEqual(code, 0, err)
        self.assert_all_placed(PAGE, {one: 2})
        self.assertEqual(err, "")

        # the placeholder of another upload is never given this command's file, and it is named
        self.fake.markdown[PAGE] = start
        lost_placement()
        self.run_cli("update", PAGE, "--append-file", note)
        self.fake.overrides.clear()
        code, out, err = self.run_cli("update", PAGE, "--append-file", other)
        self.assertEqual(code, 0, err)
        left = [b for b in self.fake.children[PAGE] if b["type"] == "image" and b["image"]["type"] == "external"]
        self.assertEqual([b["image"]["external"]["url"] for b in left], [f"https://file-upload.invalid/{one}"])
        self.assertEqual(self.placed(PAGE)[1], ("image", "https://files.example.com/" + two))
        self.assertIn(f"warning: block {left[0]['id']} of {self.page['url']} holds the placeholder of another upload ({one})", err)
        self.assertIn(f"--edit 'https://file-upload.invalid/{one}' 'file-upload://<new id>'", err)
        three = uid(0xF13E)  # the upload expired: a new one takes its place
        code, out, err = self.run_cli("update", PAGE, "--edit", f"https://file-upload.invalid/{one}", f"file-upload://{three}")
        self.assertEqual(code, 0, err)
        self.assert_all_placed(PAGE, {two: 1, three: 1})

        # prepend lands with its file, the append of the same file is refused; only what was not written is run again
        self.fake.markdown[PAGE] = start
        self.fake.calls.clear()
        self.fake.on("PATCH", rf"/v1/pages/{PAGE}/markdown", lambda r: error(400, "validation_error", "No.")
                     if r.json["insert_content"]["position"]["type"] == "end" else None)
        code, out, err = self.run_cli("update", PAGE, "--prepend-file", note, "--append-file", note)
        self.assertEqual(code, 4, err)
        self.assertRegex(err, rf"written: body added at the start; file 'a' \({one}\) placed in block \S+\. Not written: body added at the end")
        self.assertIn(f"not sent: file 'a' ({one})", err)
        self.assertIn("Rerun only what was not written or not sent", err)
        self.assertNotIn("nothing changed", err)
        self.assert_all_placed(PAGE, {one: 1})
        self.fake.overrides.clear()
        code, out, err = self.run_cli("update", PAGE, "--append-file", note)
        self.assertEqual(code, 0, err)
        self.assert_all_placed(PAGE, {one: 2})

        # the body write itself in doubt: the file was not sent, and the message says how to place it if it landed
        self.fake.markdown[PAGE] = start

        def landed_then_lost(r):
            self.fake.patch_markdown(PAGE, r.json)
            return ends_in("tls eof")(r)

        self.fake.on("PATCH", rf"/v1/pages/{PAGE}/markdown", landed_then_lost)
        code, out, err = self.run_cli("update", PAGE, "--append-file", note)
        self.assertEqual(code, 1, err)
        self.assertIn("In doubt: body added at the end", err)
        self.assertIn(f"not sent: file 'a' ({one})", err)
        self.fake.overrides.clear()
        for command in self.commands(err):
            code, out, err = self.run_cli(*command)
            self.assertEqual(code, 0, err)
        self.assert_all_placed(PAGE, {one: 1})

        # a create in doubt that landed is found by its title and its file is placed in it; not found, it is named
        def made_then_lost(r):
            self.fake.create_page(r.json)
            return ends_in("tls eof")(r)

        self.fake.on("POST", r"/v1/pages", made_then_lost)
        code, out, err = self.run_cli("create", "--parent", "Tasks", "--set", "title=Found later", "--body-file", note)
        self.assertEqual(code, 0, err)
        self.assert_all_placed(list(self.fake.pages)[-1], {one: 1})
        self.fake.overrides.clear()
        self.fake.on("POST", r"/v1/pages", ends_in("tls eof"))
        code, out, err = self.run_cli("create", "--parent", "Tasks", "--set", "title=Never found", "--body-file", note)
        self.assertEqual(code, 1, err)
        self.assertIn("In doubt: 'Never found'", err)
        self.assertIn(f"`notion update <its url> --edit 'https://file-upload.invalid/{one}' 'file-upload://{one}'`", err)

    def test_a_body_that_holds_a_placeholder_is_refused_unless_the_command_supplies_its_file(self):
        one, two = uid(0xF11E), uid(0xF12E)
        stale, body, pages = f"https://file-upload.invalid/{one}", self.tmp / "body.md", self.tmp / "pages.json"
        self.fake.markdown[PAGE] = f"![a]({stale})\n"
        forms = [f"![a]({stale})", f"Intro\n\n> ![a]({stale})", f'<file source="{stale}">\na\n</file>', f"<toggle>\nT\n\n![a]({stale})\n</toggle>"]
        for form in forms:
            body.write_text(form)
            pages.write_text(json.dumps([{"properties": {"Task name": "One"}, "content": form}]))
            for verb in (("update", PAGE, "--set", "Status=Rollout", "--replace-file", body), ("update", PAGE, "--append-file", body),
                         ("update", PAGE, "--prepend-file", body), ("update", PAGE, "--edit", "![a]", form + "\n\n![a]"),
                         ("create", "--parent", "Tasks", "--set", "title=x", "--body-file", body),
                         ("create", "--parent", "Tasks", "--pages-file", pages)):
                with self.subTest(form=form, verb=verb[:3]):
                    self.fake.calls.clear()
                    code, out, err = self.run_cli(*verb)
                    self.assertEqual(code, 2, err)
                    self.assertIn(stale, err)
                    self.assertIn(f"Write file-upload://{one} in its place", err)
                    self.assertIn("nothing was sent", err)
                    self.assertEqual(self.writes(), [])
        # the same command supplies the file, or the placeholder stands in code: it is written
        for form, wanted in ((f"![a]({stale})\n\n![b](file-upload://{one})", {one: 2}), (f"`{stale}`\n\n```\n![a]({stale})\n```\n", {})):
            with self.subTest(form=form):
                body.write_text(form)
                code, out, err = self.run_cli("update", PAGE, "--replace-file", body)
                self.assertEqual(code, 0, err)
                self.assert_all_placed(PAGE, wanted)
        # the other file of the command is not its file
        body.write_text(f"![a]({stale})\n\n![b](file-upload://{two})")
        code, out, err = self.run_cli("update", PAGE, "--replace-file", body)
        self.assertEqual(code, 2, err)

    def test_a_file_is_placed_wherever_a_block_can_hold_it(self):
        one, two = uid(0xF11E), uid(0xF12E)
        image, tag = f"![a](file-upload://{one})", f'<file source="file-upload://{two}">b.txt</file>'
        bodies = {  # name -> (body, the files it places)
            "one file": (image, {one: 1}),
            "two files": (f"{image}\n\n{tag}", {one: 1, two: 1}),
            "the same file twice": (f"{image}\n\n{image}", {one: 2}),
            "the same file as an image and as a file": (image + f'\n\n<file source="file-upload://{one}">x</file>', {one: 2}),
            "in a toggle": (f"<toggle>\nMore\n\n{image}\n\n{tag}\n</toggle>", {one: 1, two: 1}),
            "in a toggle in a toggle": (f"<toggle>\nMore\n\n<toggle>\nDeep\n\n{image}\n</toggle>\n</toggle>", {one: 1}),
            "in columns": (f"<columns>\n<column>\n{image}\n</column>\n<column>\n{tag}\n</column>\n</columns>", {one: 1, two: 1}),
            "in a callout": (f'<callout icon="⚡">\nTitle\n\n{image}\n</callout>', {one: 1}),
            "in a quote": (f"> {image}", {one: 1}),
            "beside code that shows one": (f"```\n{image}\n```\n\n{tag}", {two: 1}),
            "an upper-case id": (f"![a](file-upload://{one.upper()})", {one: 1}),
        }
        pages, body = self.tmp / "pages.json", self.tmp / "body.md"
        for name, (markdown, wanted) in bodies.items():
            body.write_text(markdown)
            pages.write_text(json.dumps([{"properties": {"Task name": "One"}, "content": markdown}]))
            for verb, args in {"replace": ("update", PAGE, "--replace-file", body), "append": ("update", PAGE, "--append-file", body),
                               "prepend": ("update", PAGE, "--prepend-file", body), "edit": ("update", PAGE, "--edit", "HERE", markdown),
                               "create": ("create", "--parent", "Tasks", "--set", "title=x", "--body-file", body),
                               "pages": ("create", "--parent", "Tasks", "--pages-file", pages)}.items():
                with self.subTest(body=name, verb=verb):
                    self.fake.calls.clear()
                    self.fake.markdown[PAGE] = "Start\n\nHERE\n\nEnd\n"
                    code, out, err = self.run_cli(*args)
                    self.assertEqual(code, 0, err)
                    self.assertEqual(err, "")
                    page = PAGE if args[0] == "update" else list(self.fake.pages)[-1]
                    self.assert_all_placed(page, wanted)
                    self.assertIn(f"uploaded files placed: {sum(wanted.values())}", out)
                    sent = self.fake.sent("PATCH", r"/v1/blocks/[^/]+")
                    self.assertEqual(len(sent), sum(wanted.values()))
                    self.assertGreater(self.fake.calls.index(self.fake.sent("GET", rf"/v1/blocks/{page}/children")[-1]),
                                       self.fake.calls.index(sent[-1]), "the page is read again after the last file")
                    for call in self.writes():
                        self.assertFalse(re.search(r"!\[[^]]*\]\(file-upload|source=.file-upload", re.sub(r"```.*?```", "",
                                                   json.dumps(call.json or {}), flags=re.S)), "an address the API does not know was sent")

    def test_every_form_of_a_file_is_recognised_and_nothing_inside_code(self):
        one, two = uid(0xF11E), uid(0xF12E)
        u, held = f"file-upload://{one}", f"https://file-upload.invalid/{one}"
        v, held_v = f"file-upload://{two}", f"https://file-upload.invalid/{two}"
        recognised = [  # what is written -> what is sent
            (f"![c]({u})", f"![c]({held})"), (f"![]({u})", f"![]({held})"), (f'![c]({u} "a title")', f'![c]({held} "a title")'),
            (f"![c]({u} 'a title')", f"![c]({held} 'a title')"), (f"![c]({u} (a title))", f"![c]({held} (a title))"),
            (f"![c]( {u} )", f"![c]( {held} )"), (f"![c](<{u}>)", f"![c](<{held}>)"), (f"![a [x] b]({u})", f"![a [x] b]({held})"),
            (f"![a \\] b]({u})", f"![a \\] b]({held})"), (f"![a `x` b]({u})", f"![a `x` b]({held})"), (f"  ![c]({u})  ", f"  ![c]({held})  "),
            (f"\t![c]({u})", f"\t![c]({held})"), (f"> ![c]({u})", f"> ![c]({held})"), (f"> > ![c]({u})", f"> > ![c]({held})"),
            (f"![c]({u})\r", f"![c]({held})\r"), (f"![c](FILE-UPLOAD://{one})", f"![c]({held})"),
            (f'<file source="{u}">c</file>', f'<file source="{held}">c</file>'), (f"<file source='{u}'>c</file>", f'<file source="{held}">c</file>'),
            (f'<file source = "{u}" >c</file>', f'<file source = "{held}" >c</file>'), (f'<file source=" {u} ">c</file>', f'<file source="{held}">c</file>'),
            (f'<file color="red" source="{u}">c</file>', f'<file color="red" source="{held}">c</file>'),
            (f'<file source="{u}" color="red">c</file>', f'<file source="{held}" color="red">c</file>'),
            (f'<file source="{u}" />', f'<file source="{held}" />'), (f'<file source="{u}">\nc\n</file>', f'<file source="{held}">\nc\n</file>'),
            (f'<image src="{u}">c</image>', f'<image src="{held}">c</image>'), (f'<pdf source="{u}"></pdf>', f'<pdf source="{held}"></pdf>'),
            (f'<audio source="{u}">c</audio>', f'<audio source="{held}">c</audio>'), (f'<video source="{u}">c</video>', f'<video source="{held}">c</video>'),
            (f'- <file source="{u}">c</file>', f'- <file source="{held}">c</file>'), (f'- item\n\t<file source="{u}">c</file>', f'- item\n\t<file source="{held}">c</file>'),
            (f'text\n<file source="{u}">c</file>\ntext', f'text\n<file source="{held}">c</file>\ntext'),
        ]
        for written, sent in recognised:
            with self.subTest(recognised=written):
                got, files = self.n.hold_files(written, "body.md")
                self.assertEqual((got, [f.id for f in files]), (sent, [one]))
        fenced = [  # code: text as it is; the file after it is a file
            "```\n{}\n```", "````\n```\n{}\n```\n````", "~~~\n{}\n~~~", "~~~~\n~~~\n{}\n~~~~", "```js\n{}\n``` js\n{}\n```", "~~~ a`b\n{}\n~~~",
            "~~~\na\n```\n{}\n~~~", "```\na\n    ```\n{}\n```", "```\n{}\n   ```", "```\n{}\n``````", "> ```\n> {}\n> ```", "> ~~~\n>{}\n> ~~~",
            "> > ```\n> > {}\n> > ```", "- item\n\t```\n\t{}\n\t```", "- ```\n  {}\n  ```", "1. ```\n   {}\n   ```", "- a\n\t- b\n\t\t```\n\t\t{}\n\t\t```",
            "text\n```\n{}\n```", "<toggle>\nT\n\n```\n{}\n```\n</toggle>", "$$\n{}\n$$", "$$\nx\n\n{}\n$$", "```\n\n{}\n\n```", "    ```\n    `{}`\n    ```",
            "`{}`", "`` {} ``", "```{}```", "text `{}` text", "<code>{}</code>", "a `x` and `{}` b", "`a\n{} b`", "> ```\n> code\n",
            "> ```\n> code", "- item\n\t```\n\tcode\n", "- ```\n", "```code``` text", "~~~not closed by ticks~~~ {}\n~~~", "text ```code``` text",
            "```\na\n```\n\n``` js\n{}\n```", "# a\n\n`x`", "a ` b", "\\`", "~~", "``` a`b",
        ]
        for shape in fenced:
            for example in (f"![c]({u})", f'<file source="{u}">c</file>'):
                with self.subTest(code=shape, example=example):
                    code = shape.replace("{}", example)
                    if shape in ("text `{}` text", "a `x` and `{}` b", "`{}`", "`` {} ``", "```{}```", "<code>{}</code>", "`a\n{} b`"):
                        code = shape.replace("{}", example + " ")
                    got, files = self.n.hold_files(f"{code}\n\n![d]({v})", "body.md")
                    self.assertEqual((got, [f.id for f in files]), (f"{code}\n\n![d]({held_v})", [two]))
        refused = [  # (body, the line it names): outside code and not a block of its own, or code nothing closes
            (f"Before ![c]({u}) after", 1), (f"Before ![c]({u})", 1), (f"![c]({u}) after", 1), (f"a\n\n- item ![c]({u})", 3), (f"- ![c]({u})", 1),
            (f"## Heading ![c]({u})", 1), (f"## ![c]({u})", 1), (f"| a | b |\n| --- | --- |\n| ![c]({u}) | x |", 3),
            (f"<table>\n<tr><td>![c]({u})</td></tr>\n</table>", 2), (f'<table>\n<tr>\n<td>\n<file source="{u}">c</file>\n</td>\n</tr>\n</table>', 4),
            (f"<table>\n<tr>\n<td>\n![c]({u})\n</td>\n</tr>\n</table>", 4), (f"![a]({u}) ![b]({v})", 1), (f"[![c]({u})](https://example.com/)", 1),
            (f"[c]({u})", 1), (f"see {u} there", 1), (f"<{u}>", 1), (f"![c][r]\n\n[r]: {u}", 3), (f"\\![c]({u})", 1), (f'\\<file source="{u}">c</file>', 1),
            (f'Text <file source="{u}">c</file>', 1), (f'<file source="{u}">c</file> text', 1), (f'<file source="{u}">c</file> <file source="{v}">d</file>', 1),
            (f'## <file source="{u}">c</file>', 1), (f'<embed source="{u}" />', 1), (f'<bookmark source="{u}" />', 1), (f"<file source={u}>c</file>", 1),
            (f'<FILE SOURCE="{u}">c</FILE>', 1), (f"<!-- ![c]({u}) -->", 1), (f"\\`![c]({u})\\`", 1), (f"a $![c]({u})$ b", 1), (f"![a\nb]({u})", 2),
            (f"![c `]({u})\n\n` d", 1), (f"a ` b\n\n![c]({u})\n\nc ` d", 3), (f"a ` b\n![c]({u})\nc ` d", 2), (f"```\ncode\n\n![c]({u})", 4),
            (f"~~~\n![c]({u})\n```\n", 2), (f"![c]({u}) {{color=\"red\"}}", 1), ("![c](file-upload://not-an-id)", 1), ("<file source='file-upload://<id>'>c</file>", 1),
            (f"![c]({u}?x=1)", 1),
        ]
        for markdown, line in refused:
            with self.subTest(refused=markdown):
                with self.assertRaises(self.n.Fail) as raised:
                    self.n.hold_files(markdown, "body.md")
                self.assertEqual(raised.exception.code, 2)
                self.assertTrue(raised.exception.message.startswith(f"body.md, line {line}: "), raised.exception.message)
                self.assertIn("nothing was sent", raised.exception.message)
                body = self.tmp / "refused.md"
                body.write_text(markdown)
                for verb in (("update", PAGE, "--set", "Status=Rollout", "--append-file", body),
                             ("create", "--parent", "Tasks", "--set", "title=x", "--body-file", body)):
                    code, out, err = self.run_cli(*verb)
                    self.assertEqual(code, 2, err)
        self.assertEqual(self.writes(), [])
        documented = re.findall(r"`([!<][^`]*file-upload://<id>[^`]*)`", (SKILL_DIR / "references" / "notion-markdown.md").read_text(encoding="utf-8"))
        self.assertGreater(len(documented), 5)
        for form in documented:
            with self.subTest(documented=form):
                self.assertEqual([f.id for f in self.n.hold_files(form.replace("<id>", one), "body.md")[1]], [one])
        for untouched in ("no file here", "", "a `file-upload://<id>` in words", "file-upload:// is the scheme", "![c](https://example.com/x.png)"):
            self.assertEqual(self.n.hold_files(untouched, "body.md"), (untouched, []))

    def test_the_walk_of_a_long_body_is_linear(self):
        line = f"![c](file-upload://{uid(0xF11E)})"
        for shape in ("`", "``` ", "\\`", "> ", "- ", "\n", "$$\n", "```\n", "~~~\n", "[", "![", "![a](", "<file ", "<file source=", "<code>", "a ` b\n", "\t- x\n"):
            with self.subTest(shape=shape):
                body = line + "\n\n" + (shape * (60000 // len(shape))) + "\n"
                began = time.process_time()
                try:
                    self.n.hold_files(body, "body.md")
                except self.n.Fail:
                    pass
                self.assertLess(time.process_time() - began, 5)

    def commands(self, err):
        """The commands a message gives to place files, each as the client's arguments."""
        return [shlex.split(found) for found in re.findall(r"`notion (update \S+ --edit '[^']+' '[^']+')`", err)]

    def assert_all_placed(self, page, wanted):
        """No placeholder is left on the page, in any block, and each upload is in as many blocks as wanted."""
        wanted = {upload: count if isinstance(count, int) else 1 for upload, count in wanted.items()}
        held = collections.Counter(url.rsplit("/", 1)[1] for _, url in self.placed(page) if url.startswith("https://files.example.com/"))
        self.assertEqual(held, collections.Counter(wanted))

        def every(identifier):
            for block in self.fake.children.get(identifier, []):
                yield block
                yield from every(block["id"])

        for block in every(page):
            if block["type"] != "code" and "`" not in json.dumps(block[block["type"]]):
                self.assertNotIn("file-upload.invalid", json.dumps(block))

    def test_download_saves_the_file_without_the_token(self):
        block = uid(0xF2)
        url = "https://files.example.com/b/screen.png?X-Signature=abc"
        self.fake.blocks[block] = {"object": "block", "id": block, "type": "image",
                                   "image": {"type": "file", "file": {"url": url, "expiry_time": "2026-11-22T12:00:00.000Z"}, "caption": []}}
        self.fake.files[url] = b"image bytes"
        out_dir = self.tmp / "downloads"
        code, out, err = self.run_cli("download", block, "-o", out_dir)
        self.assertEqual(code, 0, err)
        saved = out_dir / "screen.png"
        self.assertEqual(saved.read_bytes(), b"image bytes")
        self.assertIn(str(saved), out)
        fetched = [c for c in self.fake.calls if c.host == "files.example.com"][0]
        self.assertNotIn("authorization", fetched.headers)
        code, out, err = self.run_cli("download", url, "-o", out_dir)
        self.assertEqual(code, 0, err)

    def test_download_never_replaces_a_file_of_the_same_name(self):
        url = "https://files.example.com/signed/README.md?X-Signature=abc"
        self.fake.files[url] = b"bytes from the attachment"
        out_dir = self.tmp / "work"
        out_dir.mkdir()
        (out_dir / "README.md").write_text("my local work")
        for wanted in ("README (1).md", "README (2).md"):
            with self.subTest(wanted=wanted):
                code, out, err = self.run_cli("download", url, "-o", out_dir)
                self.assertEqual(code, 0, err)
                self.assertEqual((out_dir / "README.md").read_text(), "my local work")
                self.assertEqual((out_dir / wanted).read_bytes(), b"bytes from the attachment")
                self.assertIn(str(out_dir / wanted), out)


class PeopleTest(ClientTestCase):
    def test_users_find_includes_people_seen_in_rows(self):
        code, out, err = self.run_cli("users", "find", "joana")
        self.assertEqual(code, 1)
        self.page["properties"]["Assignee"]["people"] = [GUEST]
        code, out, err = self.run_cli("fetch", PAGE)
        self.assertEqual(code, 0, err)
        code, out, err = self.run_cli("users", "find", "joana")
        self.assertEqual(code, 0, err)
        self.assertIn("user://" + JOANA, out)
        self.assertIn("Joana Araújo", out)

    def test_users_find_ignores_case_and_accents(self):
        self.page["properties"]["Assignee"]["people"] = [GUEST]
        self.run_cli("fetch", PAGE)
        for needle, who in (("BRUNO", BRUNO), ("araujo", JOANA), ("BRUNO@example.com", BRUNO), ("lima", ANA)):
            with self.subTest(needle=needle):
                code, out, err = self.run_cli("users", "find", needle)
                self.assertEqual(code, 0, err)
                self.assertIn("user://" + who, out)

    def test_person_by_name_is_resolved_over_listed_users_and_cache(self):
        souza = uid(0xA4)
        # Ana Lima reaches the cache from a row read; Ana Souza is only in the API's user list.
        code, out, err = self.run_cli("fetch", PAGE)
        self.assertEqual(code, 0, err)
        self.fake.users = {souza: person(souza, "Ana Souza", "ana.souza@example.com")}
        self.fake.calls.clear()
        for args in (("update", PAGE, "--set", "Assignee=Ana"), ("query", "Tasks", "--where", "Assignee has Ana")):
            with self.subTest(ambiguous=args):
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 2, err)
                for shown in ("Ana Lima", "ana@example.com", "user://" + ANA,
                              "Ana Souza", "ana.souza@example.com", "user://" + souza):
                    self.assertIn(shown, err)
                self.assertTrue(self.fake.sent("GET", r"/v1/users"))
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query"), [])
        code, out, err = self.run_cli("users", "find", "ana")
        self.assertEqual(code, 0, err)
        self.assertIn("user://" + ANA, out)
        self.assertIn("user://" + souza, out)
        code, out, err = self.run_cli("update", PAGE, "--set", "Assignee=Zed")
        self.assertEqual(code, 2)
        self.assertIn("nobody matches", err)
        self.assertEqual(self.writes(), [])
        for value, wanted in (("ana@example.com", ANA), ("Ana Souza", souza), ("user://" + ANA, ANA)):
            with self.subTest(unique=value):
                code, out, err = self.run_cli("update", PAGE, "--set", "Assignee=" + value)
                self.assertEqual(code, 0, err)
                self.assertEqual(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"]["Assignee"],
                                 {"people": [{"id": wanted}]})

    def test_unreadable_user_list_warns_once_and_still_resolves(self):
        self.fake.data_sources[DS_TASKS]["properties"]["Reviewer"] = {
            "id": "rv", "name": "Reviewer", "type": "people", "people": {}}
        code, out, err = self.run_cli("fetch", PAGE)  # Ana Lima reaches the cache from the row read
        self.assertEqual(code, 0, err)

        def doubt_lines(err):
            return [line for line in err.splitlines() if "only over the people seen in pages read" in line]

        code, out, err = self.run_cli("update", PAGE, "--set", "Assignee=Ana", "--set", "Reviewer=Ana Lima")
        self.assertEqual(code, 0, err)
        self.assertEqual(doubt_lines(err), [])
        self.assertNotIn("warning", err)
        for status in (403, 500):
            with self.subTest(status=status):
                self.fake.users_status = status
                self.fake.calls.clear()
                code, out, err = self.run_cli("update", PAGE, "--set", "Assignee=Ana", "--set", "Reviewer=ana@example.com")
                self.assertEqual(code, 0, err)
                self.assertEqual(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"],
                                 {"Assignee": {"people": [{"id": ANA}]}, "Reviewer": {"people": [{"id": ANA}]}})
                self.assertIn("Ana Lima", out)
                lines = doubt_lines(err)
                self.assertEqual(len(lines), 1, err)
                for words in (f"{status} restricted_resource", "Insufficient permissions for this endpoint.",
                              "user://<uuid>", "user information capability"):
                    self.assertIn(words, lines[0])
                code, out, err = self.run_cli("users", "find", "ana")
                self.assertEqual(code, 0, err)
                self.assertIn("user://" + ANA, out)
                self.assertEqual(len(doubt_lines(err)), 1, err)
        self.fake.users_status = 200
        code, out, err = self.run_cli("users", "find", "ana")
        self.assertEqual(code, 0, err)
        self.assertEqual(doubt_lines(err), [])

    def test_a_user_list_that_fails_on_a_later_page_keeps_the_people_read(self):
        souza = uid(0xA4)
        failures = {"403": ("403 restricted_resource", "Insufficient permissions"),
                    "500": ("500 internal_server_error", "Something went wrong"), "timeout": ("in time",)}

        def fresh(failure):
            """Ana Lima in the cache from a row read; Ana Souza only on page 1 of the list; page 2 fails."""
            shutil.rmtree(self.home / ".cache", ignore_errors=True)
            self.fake.overrides.clear()
            self.page["properties"]["Assignee"]["people"] = [USERS[ANA]]
            code, out, err = self.run_cli("fetch", PAGE)
            self.assertEqual(code, 0, err)

            def listing(r, failure=failure):
                if not r.query.get("start_cursor"):
                    return 200, {"object": "list", "results": [person(souza, "Ana Souza", "ana.souza@example.com")],
                                 "has_more": True, "next_cursor": "page-2"}
                if failure == "timeout":
                    raise TimeoutError("timed out")
                if failure == "500":
                    return error(500, "internal_server_error", "Something went wrong.")
                return error(403, "restricted_resource", "Insufficient permissions for this endpoint.")

            self.fake.on("GET", r"/v1/users", listing)
            self.fake.calls.clear()

        for failure, reason in failures.items():
            for args in (("update", PAGE, "--set", "Assignee=Ana"), ("query", "Tasks", "--where", "Assignee has Ana")):
                with self.subTest(failure=failure, ambiguous=args[0]):
                    fresh(failure)
                    code, out, err = self.run_cli(*args)
                    self.assertEqual(code, 2, err)
                    for shown in ("Ana Lima", "user://" + ANA, "Ana Souza", "user://" + souza):
                        self.assertIn(shown, err)
                    self.assertEqual(self.writes(), [])
                    self.assertEqual(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query"), [])
                    self.assertEqual(len(self.fake.sent("GET", r"/v1/users")) >= 2, True, "page 2 was asked for")
            with self.subTest(failure=failure, unique="Ana Souza"):
                fresh(failure)
                code, out, err = self.run_cli("update", PAGE, "--set", "Assignee=Ana Souza")
                self.assertEqual(code, 0, err)
                self.assertEqual(self.fake.sent("PATCH", rf"/v1/pages/{PAGE}")[-1].json["properties"]["Assignee"],
                                 {"people": [{"id": souza}]})
                warning = [line for line in err.splitlines() if line.startswith("warning:")]
                self.assertEqual(len(warning), 1, err)
                self.assertIn("incomplete", warning[0])
                self.assertIn("page 2", warning[0])
                for words in reason:
                    self.assertIn(words, warning[0])

    def test_whoami_from_settings_then_git(self):
        self.settings(me="ana@example.com")
        code, out, err = self.run_cli("whoami")
        self.assertEqual(code, 0, err)
        self.assertIn("Ana Lima", out)
        self.assertIn("user://" + ANA, out)
        self.settings()
        self.n.git_email = lambda: "bruno@example.com"
        code, out, err = self.run_cli("whoami")
        self.assertEqual(code, 0, err)
        self.assertIn("Bruno Costa", out)

    def test_me_names_the_reason_when_the_user_list_cannot_be_read(self):
        self.settings(me="bruno@example.com")  # right, but Bruno is in no row read, so only the list knows him
        for status in (500, 403):
            with self.subTest(status=status):
                self.fake.users_status = status
                self.fake.calls.clear()
                for args in (("whoami",), ("update", PAGE, "--set", "Assignee=me")):
                    code, out, err = self.run_cli(*args)
                    self.assertEqual(code, 1, err)
                    for words in (f"{status} restricted_resource", "Insufficient permissions for this endpoint.",
                                  "could not be read", "bruno@example.com", "config.json"):
                        self.assertIn(words, err)
                    self.assertNotIn("nobody the integration can see", err)
                self.assertEqual(self.writes(), [])
                code, out, err = self.run_cli("comments", "add", PAGE, "--body", "Ready")
                self.assertEqual(code, 0, err)
                self.assertIn("shown as the integration", err)
                self.assertIn(f"{status} restricted_resource", err)
        self.fake.users_status = 200
        self.settings(me="nobody@example.com")
        code, out, err = self.run_cli("whoami")
        self.assertEqual(code, 1)
        self.assertIn("nobody the integration can see has the e-mail nobody@example.com", err)
        self.assertNotIn("could not be read", err)
        self.settings(me="bruno@example.com")
        code, out, err = self.run_cli("whoami")
        self.assertEqual(code, 0, err)
        self.assertIn("Bruno Costa", out)

    def test_whoami_nobody_exits_1(self):
        self.n.git_email = lambda: "nobody@example.com"
        code, out, err = self.run_cli("whoami")
        self.assertEqual(code, 1)
        self.assertIn("me", err)
        self.assertIn("config.json", err)


class TokenTest(ClientTestCase):
    def bearer(self):
        return [c.headers.get("authorization") for c in self.fake.calls if c.host == "api.notion.com"][-1]

    def test_token_order_env_keyring_file(self):
        self.keyring = "ntn_keyring_value_000000000000000000000"
        code, out, err = self.run_cli("auth", "status")
        self.assertEqual(code, 0, err)
        self.assertIn("NOTION_API_TOKEN", out)
        self.assertEqual(self.bearer(), "Bearer " + TOKEN)
        os.environ.pop("NOTION_API_TOKEN")
        code, out, err = self.run_cli("auth", "status")
        self.assertEqual(code, 0, err)
        self.assertIn("keyring", out)
        self.assertEqual(self.bearer(), "Bearer ntn_keyring_value_000000000000000000000")
        self.assertIn((("lookup", "service", "notion-api"), None), self.keyring_calls)
        self.keyring = None
        credentials = self.home / ".config" / "notion" / "credentials"
        credentials.parent.mkdir(parents=True)
        credentials.write_text("ntn_file_value_00000000000000000000000\n")
        credentials.chmod(0o600)
        code, out, err = self.run_cli("auth", "status")
        self.assertEqual(code, 0, err)
        self.assertIn("credentials", out)
        self.assertEqual(self.bearer(), "Bearer ntn_file_value_00000000000000000000000")

    def test_token_order_with_every_source_present(self):
        keyring_token = "ntn_keyring_value_111111111111111111111"
        file_token = "ntn_file_value_22222222222222222222222"
        credentials = self.home / ".config" / "notion" / "credentials"
        credentials.parent.mkdir(parents=True)
        credentials.write_text(file_token + "\n")
        credentials.chmod(0o600)
        self.keyring = keyring_token
        for env, wanted, source in ((TOKEN, TOKEN, "NOTION_API_TOKEN"), (None, keyring_token, "keyring")):
            with self.subTest(env=bool(env)):
                if env:
                    os.environ["NOTION_API_TOKEN"] = env
                else:
                    os.environ.pop("NOTION_API_TOKEN", None)
                code, out, err = self.run_cli("auth", "status")
                self.assertEqual(code, 0, err)
                self.assertIn(source, out)
                self.assertEqual(self.bearer(), "Bearer " + wanted)
        self.keyring = None
        code, out, err = self.run_cli("auth", "status")
        self.assertEqual(code, 0, err)
        self.assertIn("credentials", out)
        self.assertEqual(self.bearer(), "Bearer " + file_token)

    def test_credentials_file_open_to_others_warns_once_and_works(self):
        os.environ.pop("NOTION_API_TOKEN")
        file_token = "ntn_file_value_33333333333333333333333"
        credentials = self.home / ".config" / "notion" / "credentials"
        credentials.parent.mkdir(parents=True)
        credentials.write_text(file_token + "\n")
        for mode in (0o644, 0o640):
            with self.subTest(mode=oct(mode)):
                credentials.chmod(mode)
                code, out, err = self.run_cli("auth", "status")
                self.assertEqual(code, 0, err)
                self.assertEqual(self.bearer(), "Bearer " + file_token)
                warnings = [line for line in err.splitlines() if "chmod 600" in line]
                self.assertEqual(len(warnings), 1, err)
                self.assertIn(str(credentials), warnings[0])
                self.assertIn(f"chmod 600 {credentials}", warnings[0])
        credentials.chmod(0o600)
        code, out, err = self.run_cli("auth", "status")
        self.assertEqual(code, 0, err)
        self.assertNotIn("chmod", err)

    def test_token_never_printed(self):
        self.fake.on("GET", rf"/v1/pages/{PAGE}/markdown",
                     lambda r: error(400, "validation_error", "bad header " + r.headers["authorization"]))
        outputs = []
        for args in (("fetch", PAGE), ("fetch", PAGE, "--json"), ("auth", "status"), ("doctor",),
                     ("api", "GET", f"/v1/pages/{PAGE}/markdown")):
            code, out, err = self.run_cli(*args)
            outputs.append(out + err)
        joined = "\n".join(outputs)
        self.assertIn("bad header", joined)
        self.assertNotIn(TOKEN, joined)
        self.assertNotIn(TOKEN[4:20], joined)

    def test_token_with_a_character_that_is_not_plain_ascii_exits_3(self):
        for name, odd in (("zero-width space", chr(0x200B)), ("byte-order mark", chr(0xFEFF)), ("ellipsis", chr(0x2026)),
                          ("accent", chr(0xE9)), ("no-break space", chr(0xA0)), ("a control character", chr(7))):
            for source in ("env", "prompt"):
                with self.subTest(odd=name, source=source):
                    self.fake.calls.clear()
                    os.environ.pop("NOTION_API_TOKEN", None)
                    if source == "env":
                        os.environ["NOTION_API_TOKEN"] = TOKEN[:20] + odd + TOKEN[20:]
                        code, out, err = self.run_cli("fetch", PAGE)
                    else:
                        self.n.STDIN_IS_TTY = lambda: True
                        self.n.GETPASS = lambda prompt, odd=odd: TOKEN[:20] + odd + TOKEN[20:]
                        code, out, err = self.run_cli("auth", "login")
                    self.assertEqual(code, 3, err)
                    self.assertIn("malformed", err)
                    self.assertNotIn(TOKEN[4:20], out + err)
                    self.assertEqual(self.fake.calls, [])

    def test_token_with_a_line_break_inside_exits_3_and_is_never_printed(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        self.n.API_HOST = "127.0.0.1:%d" % closed.getsockname()[1]
        closed.close()  # the real transport is installed below: nothing it might send can reach the real host
        self.n.API_ROOT = "http://" + self.n.API_HOST
        credentials = self.home / ".config" / "notion" / "credentials"
        credentials.parent.mkdir(parents=True)
        credentials.write_text(TOKEN + " " + TOKEN + "\n")
        credentials.chmod(0o600)
        for source in ("env", "keyring", "file"):
            with self.subTest(source=source):
                os.environ.pop("NOTION_API_TOKEN", None)
                self.keyring = None
                # the real transport refuses a line break in the header before any connection is made; the
                # fake one stands in where a space would be a legal header and the request must never be built
                self.n.TRANSPORT = self.n.urllib_transport if source != "file" else self.fake
                self.fake.calls.clear()
                if source == "env":
                    os.environ["NOTION_API_TOKEN"] = TOKEN + "\n" + TOKEN
                elif source == "keyring":
                    self.keyring = TOKEN + "\n" + TOKEN + "\n"
                code, out, err = self.run_cli("fetch", PAGE)
                self.assertEqual(code, 3, err)
                self.assertIn("malformed", err)
                self.assertIn("notion auth login", err)
                self.assertNotIn("ntn_", out + err)
                self.assertNotIn(TOKEN[4:20], out + err)
                self.assertEqual(self.fake.calls, [])

    def test_an_uncaught_error_prints_its_name_and_never_the_token(self):
        def boom(client, args):
            raise ValueError("Invalid header value b'Bearer " + TOKEN + "'")

        self.n.cmd_whoami = boom
        code, out, err = self.run_cli("whoami")
        self.assertEqual(code, 1)
        self.assertIn("ValueError", err)
        self.assertNotIn(TOKEN, out + err)

    def test_no_token_or_401_exits_3_for_every_verb(self):
        upload = self.tmp / "a.txt"
        upload.write_text("x")
        verbs = [
            ("fetch", PAGE), ("update", PAGE, "--set", "Status=Done"), ("create", "--parent", PAGE, "--set", "title=x"),
            ("query", "Tasks"), ("search", "invoice"), ("comments", "list", PAGE), ("comments", "add", PAGE, "--body", "x"),
            ("upload", upload), ("download", uid(0xF1)), ("users", "find", "ana"), ("whoami",),
            ("trash", PAGE, "--confirm"), ("api", "GET", "/v1/users/me"), ("doctor",), ("auth", "status"),
        ]
        os.environ.pop("NOTION_API_TOKEN")
        for args in verbs:
            with self.subTest(no_token=args):
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 3, err)
                self.assertIn("notion auth login", err)
        os.environ["NOTION_API_TOKEN"] = TOKEN
        rejected = (401, {"object": "error", "status": 401, "code": "unauthorized", "message": "API token is invalid."})
        for method in ("GET", "POST", "PATCH"):
            self.fake.on(method, r"/v1/.*", lambda r: rejected)
        for args in verbs:
            with self.subTest(rejected=args):
                shutil.rmtree(self.home / ".cache", ignore_errors=True)
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 3, err)
                self.assertIn("notion auth login", err)

    def test_auth_login_refuses_without_a_terminal(self):
        prompted = []
        self.n.STDIN_IS_TTY = lambda: False
        self.n.GETPASS = lambda prompt: prompted.append(prompt) or TOKEN
        code, out, err = self.run_cli("auth", "login")
        self.assertEqual(code, 2)
        self.assertIn("terminal", err)
        self.assertEqual(prompted, [])
        self.assertEqual(self.fake.calls, [])

    def test_auth_login_stores_in_keyring_or_file_600(self):
        os.environ.pop("NOTION_API_TOKEN")
        self.n.STDIN_IS_TTY = lambda: True
        self.n.GETPASS = lambda prompt: TOKEN
        self.keyring = ""
        code, out, err = self.run_cli("auth", "login")
        self.assertEqual(code, 0, err)
        stores = [call for call in self.keyring_calls if call[0][0] == "store"]
        self.assertEqual(len(stores), 1)
        self.assertIn("service", stores[0][0])
        self.assertIn("notion-api", stores[0][0])
        self.assertEqual(stores[0][1], TOKEN)
        self.assertEqual(self.bearer(), "Bearer " + TOKEN)
        self.assertNotIn(TOKEN, out + err)
        self.keyring = None
        code, out, err = self.run_cli("auth", "login")
        self.assertEqual(code, 0, err)
        credentials = self.home / ".config" / "notion" / "credentials"
        self.assertEqual(credentials.read_text().strip(), TOKEN)
        self.assertEqual(stat.S_IMODE(credentials.stat().st_mode), 0o600)


class DoctorTest(ClientTestCase):
    def test_doctor_reports_owner_capabilities_and_data_sources(self):
        code, out, err = self.run_cli("doctor")
        self.assertEqual(code, 0, out + err)
        lines = out.splitlines()
        self.assertTrue(any(line.startswith("token:") and "workspace" in line for line in lines))
        for capability, state in (("read content", "present"), ("update content", "not probed"),
                                  ("insert content", "not probed"), ("read comments", "present"),
                                  ("insert comments", "not probed"), ("user information", "present")):
            row = [line for line in lines if line.startswith(capability + ":")]
            self.assertEqual(len(row), 1, capability)
            self.assertIn(state, row[0])
        sources = [line for line in lines if line.startswith("data source:")]
        self.assertEqual(len(sources), 2)
        self.assertTrue(any("Tasks" in line and PREFIX in line for line in sources))
        self.assertTrue(any("Projects" in line and "PRJ" in line for line in sources))

    def test_doctor_names_an_untitled_data_source(self):
        self.fake.data_sources[DS_PROJECTS]["title"] = []
        code, out, err = self.run_cli("doctor")
        self.assertEqual(code, 0, out + err)
        self.assertIn(f"data source: (untitled), prefix PRJ, {COLLECTION}{DS_PROJECTS}", out.splitlines())
        code, out, err = self.run_cli("fetch", COLLECTION + DS_PROJECTS)
        self.assertEqual(out.splitlines()[0], "data source: (untitled)")
        code, out, err = self.run_cli("fetch", "no such title")
        self.assertEqual(code, 2)
        self.assertIn("connected data source (Tasks)", err)

    def test_doctor_missing_capability_exits_1(self):
        self.fake.on("GET", r"/v1/comments", lambda r: error(403, "restricted_resource", "Insufficient permissions."))
        self.fake.users_status = 403
        code, out, err = self.run_cli("doctor")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"(?m)^read comments: missing")
        self.assertRegex(out, r"(?m)^user information: missing")

    def test_doctor_write_check_round_trip(self):
        self.settings(test_marker="QA MARKER", me="ana@example.com")
        code, out, err = self.run_cli("doctor", "--write-check", COLLECTION + DS_TASKS)
        self.assertEqual(code, 0, out + err)
        created = [pg for pg in self.fake.pages.values() if self.fake.title_of(pg).startswith("QA MARKER")]
        self.assertEqual(len(created), 1)
        test_page = created[0]
        self.assertEqual(test_page["parent"]["data_source_id"], DS_TASKS)
        body = self.fake.sent("PATCH", rf"/v1/pages/{test_page['id']}/markdown")[-1].json["replace_content"]["new_str"]
        for tag in ("<callout", "<table", "<toggle"):
            self.assertIn(tag, body)
        self.assertTrue(self.fake.sent("PATCH", rf"/v1/pages/{test_page['id']}")[0].json.get("properties"))
        self.assertTrue([c for c in self.fake.sent("POST", r"/v1/comments") if c.json["parent"]["page_id"] == test_page["id"]])
        self.assertTrue(test_page["in_trash"])
        for step in ("create", "property", "body", "comment", "trash"):
            self.assertRegex(out, rf"(?m)^write check {step}.*: ok")
        self.assertNotIn("FAILED", out)
        self.assertIn("| Column | Value |", self.fake.page_markdown(test_page["id"])["markdown"])  # what a read gives back
        self.assertIn(f"write check create: ok ({test_page['url']})", out.splitlines())

    def test_doctor_write_check_trashes_its_card_after_a_create_in_doubt(self):
        self.settings(test_marker="QA MARKER")
        title = "QA MARKER doctor 2026-11-22 09:30:15"
        older = self.fake.add_page(task_page(uid(0x4200), 160, title, created_by=ANA))  # never another author's card
        where = f"data source Tasks ({COLLECTION}{DS_TASKS})"
        query = rf"/v1/data_sources/{DS_TASKS}/query"

        def checks(r):  # the lookups of the card; the read that samples a row for `read comments` is not one
            return "filter" in (r.json or {})

        def listed_late(r, state):
            state["lookups"] += checks(r)
            return (200, {"results": [], "has_more": False}) if checks(r) and state["lookups"] < 3 else None

        for kind in ("500", "502", "503", "504", "529", *LOST, *UNREADABLE):
            for landed, lookup in ((True, "found"), (True, "late"), (True, "403"), (True, "timeout"), (False, "found")):
                with self.subTest(create=kind, landed=landed, lookup=lookup):
                    self.fake.overrides.clear()
                    self.fake.calls.clear()
                    self.fake.pages = {PAGE: self.page, older["id"]: older}
                    fails, state = ends_in(kind), {"lookups": 0}

                    def create(r, landed=landed, fails=fails):
                        if landed:
                            self.fake.create_page(r.json)
                        return fails(r)

                    self.fake.on("POST", r"/v1/pages", create)
                    if lookup == "late":
                        self.fake.on("POST", query, lambda r, state=state: listed_late(r, state))
                    elif lookup == "403":
                        self.fake.on("POST", query, lambda r: error(403, "restricted_resource", "No.") if checks(r) else None)
                    elif lookup == "timeout":
                        self.fake.on("POST", query, lambda r: ends_in("timeout")(r) if checks(r) else None)
                    code, out, err = self.run_cli("doctor", "--write-check", COLLECTION + DS_TASKS)
                    self.assertEqual(code, 1, out + err)
                    self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 1, "the create is never sent again")
                    self.assertRegex(out, r"(?m)^write check create: FAILED \(.*in doubt")
                    self.assertFalse(older["in_trash"])
                    made = [pg for pg in self.fake.pages.values() if pg["created_by"]["id"] == BOT and self.fake.title_of(pg) == title]
                    self.assertEqual(len(made), int(landed))
                    if landed and lookup in ("found", "late"):
                        self.assertTrue(made[0]["in_trash"])
                        self.assertIn(made[0]["url"], out)
                        self.assertRegex(out, r"(?m)^write check trash: ok")
                    else:
                        self.assertRegex(out, r"(?m)^write check trash: FAILED")
                        self.assertIn(f"look for a card titled {title!r} in {where} and trash it by hand", out)

        # the card was made and answered, and the request that trashes it is lost: the card is named
        for kind in (*LOST, *UNREADABLE, "400", "503"):
            with self.subTest(trash=kind):
                self.fake.overrides.clear()
                self.fake.pages = {PAGE: self.page}
                fails = ends_in(kind)
                self.fake.on("PATCH", r"/v1/pages/[^/]+", lambda r, fails=fails: fails(r) if "in_trash" in r.json else None)
                code, out, err = self.run_cli("doctor", "--write-check", COLLECTION + DS_TASKS)
                self.assertEqual(code, 1, out + err)
                made = [pg for pg in self.fake.pages.values() if self.fake.title_of(pg) == title][0]
                self.assertIn(f"trash the card {title!r} by hand: {made['url']}", out)

        # a create Notion refused, or that was never sent, made no card: nothing to look for
        for kind in ("400", "unreachable"):
            with self.subTest(create=kind):
                self.fake.overrides.clear()
                self.fake.pages = {PAGE: self.page}
                self.fake.on("POST", r"/v1/pages", ends_in(kind))
                code, out, err = self.run_cli("doctor", "--write-check", COLLECTION + DS_TASKS)
                self.assertEqual(code, 1, out + err)
                self.assertNotIn("by hand", out)

    def test_doctor_write_check_comment_carries_a_link_and_reads_back_with_it(self):
        self.settings(test_marker="QA MARKER")
        code, out, err = self.run_cli("doctor", "--write-check", COLLECTION + DS_TASKS)
        self.assertEqual(code, 0, out + err)
        sent = self.fake.sent("POST", r"/v1/comments")[-1].json
        self.assertIn("[a link](https://example.com/)", sent["markdown"])
        self.assertRegex(out, r"(?m)^write check comment: ok")
        # a comment that comes back without its address fails the check, and the card is still trashed
        self.fake.calls.clear()
        self.fake.on("POST", r"/v1/comments", lambda r: (200, dict(
            self.fake.create_comment(dict(r.json, markdown=re.sub(r"\[(.*?)\]\(.*?\)", r"\1", r.json["markdown"])))[1])))
        code, out, err = self.run_cli("doctor", "--write-check", COLLECTION + DS_TASKS)
        self.assertEqual(code, 1, out + err)
        self.assertRegex(out, r"(?m)^write check comment: FAILED \(the comment did not read back with its link\)")
        self.assertRegex(out, r"(?m)^write check trash: ok")

    def test_doctor_write_check_mismatch_exits_1_and_trashes(self):
        # A construct stored as anything but its own block fails the check, even when the text is the same.
        self.settings(test_marker="QA MARKER")

        def as_text(value):
            return self.fake.block("paragraph", {"rich_text": text(value), "color": "default"})

        def replaced(index, value):
            return lambda blocks: blocks[:index] + [as_text(value)] + blocks[index + 1:]

        def changed(index, change):
            def apply(blocks):
                change(blocks[index])
                return blocks
            return apply

        def without_child(index, keep):
            def change(block):
                self.fake.children[block["id"]] = self.fake.children[block["id"]][:keep]
            return changed(index, change)

        cases = [
            ("callout as text", replaced(0, "Write check callout"), "stored as paragraph, table, toggle"),
            ("table as text", replaced(1, "| Column | Value |"), "stored as callout, paragraph, toggle"),
            ("toggle as text", replaced(2, "Write check toggle"), "stored as callout, table, paragraph"),
            ("everything as one text", lambda b: [as_text(self.n.WRITE_CHECK_BODY)], "stored as paragraph,"),
            ("nothing", lambda b: [], "stored as nothing"),
            ("an extra block", lambda b: b + [as_text("more")], "stored as callout, table, toggle, paragraph"),
            ("callout with other text", changed(0, lambda b: b["callout"].update(rich_text=text("x"))), "the callout holds 'x'"),
            ("no header row", changed(1, lambda b: b["table"].update(has_column_header=False)), "2 columns and no header row"),
            ("three columns", changed(1, lambda b: b["table"].update(table_width=3)), "3 columns and a header row"),
            ("one row", without_child(1, 1), "the table holds [['Column', 'Value']]"),
            ("empty toggle", without_child(2, 0), "the toggle 'Write check toggle' holds []"),
        ]
        for name, spoil, said in cases:
            with self.subTest(case=name):
                self.fake.pages = {PAGE: self.page}
                store = FakeNotion.store_blocks

                def spoiled(identifier, markdown):
                    store(self.fake, identifier, markdown)
                    self.fake.children[identifier] = spoil(self.fake.children[identifier])
                self.fake.store_blocks = spoiled
                code, out, err = self.run_cli("doctor", "--write-check", COLLECTION + DS_TASKS)
                self.assertEqual(code, 1, out)
                self.assertIn("write check body (callout, table, toggle): FAILED (", out)
                self.assertIn(said, out)
                created = [pg for pg in self.fake.pages.values() if self.fake.title_of(pg).startswith("QA MARKER")]
                self.assertEqual(len(created), 1)
                self.assertTrue(created[0]["in_trash"])


class CacheTest(ClientTestCase):
    def test_deleted_cache_rebuilds_the_same_answer(self):
        code, first, err = self.run_cli("fetch", key(120))
        self.assertEqual(code, 0, err)
        cache = self.home / ".cache" / "cdv-notion"
        self.assertTrue(cache.is_dir())
        self.fake.calls.clear()
        code, warm, err = self.run_cli("fetch", key(120))
        self.assertEqual(warm, first)
        self.assertEqual(self.fake.sent("POST", r"/v1/search"), [])
        shutil.rmtree(cache)
        code, again, err = self.run_cli("fetch", key(120))
        self.assertEqual(code, 0, err)
        self.assertEqual(again, first)
        self.assertTrue(self.fake.sent("POST", r"/v1/search"))
        self.assertTrue(cache.is_dir())


class PeopleCacheRaceTest(ClientTestCase):
    def test_two_sessions_that_loaded_the_cache_before_either_wrote_keep_both_people(self):
        first, second = self.n.Notion(), self.n.Notion()
        self.assertEqual((first.people(), second.people()), ({}, {}))  # both loaded the empty cache
        second.remember(GUEST)
        first.remember(USERS[BRUNO])
        saved = json.loads((self.home / ".cache" / "cdv-notion" / "people.json").read_text())
        self.assertEqual(sorted(saved), sorted([JOANA, BRUNO]))
        self.assertEqual(sorted(first.people()), sorted([JOANA, BRUNO]))


class StaleCacheTest(ClientTestCase):
    """What the cache holds can be older than the workspace: a read re-reads it once before it refuses."""

    DS_ROADMAP = uid(0xD53)

    def warm(self):
        """A cache built before the workspace changed."""
        shutil.rmtree(self.home / ".cache", ignore_errors=True)
        self.fake.data_sources[DS_TASKS]["properties"].pop("Priority", None)
        code, out, err = self.run_cli("fetch", key(120))
        self.assertEqual(code, 0, err)
        self.fake.data_sources[DS_TASKS]["properties"]["Priority"] = {
            "id": "pri", "name": "Priority", "type": "select",
            "select": {"options": [option("High", 1), option("Low", 2)]}}
        self.fake.calls.clear()

    def schema_reads(self):
        return self.fake.sent("GET", rf"/v1/data_sources/{DS_TASKS}")

    def list_reads(self):
        return [c for c in self.fake.sent("POST", r"/v1/search") if (c.json or {}).get("filter", {}).get("value") == "data_source"]

    def test_query_rereads_the_schema_once_for_a_name_the_cache_lacks(self):
        flags = {"--where": "Priority = 'High'", "--select": "Task name,Priority", "--order": "Priority desc",
                 "--group-by": "Priority"}
        for flag, value in flags.items():
            with self.subTest(flag=flag):
                self.warm()
                code, out, err = self.run_cli("query", COLLECTION + DS_TASKS, flag, value)
                self.assertEqual(code, 0, err)
                self.assertEqual(len(self.schema_reads()), 1)
                self.assertEqual(len(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")), 1)
        self.warm()
        code, out, err = self.run_cli("query", COLLECTION + DS_TASKS, "--where", "Priority = 'High' AND Sprint = 'x'")
        self.assertEqual(code, 2)
        self.assertIn("unknown property 'Sprint' in the condition", err)
        self.assertEqual(len(self.schema_reads()), 1)
        self.assertEqual(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query"), [])

    def test_fetch_of_a_data_source_reads_the_api_whatever_the_reference_form(self):
        outputs = []
        for form in (COLLECTION + DS_TASKS, "Tasks", DS_TASKS, hex32(DS_TASKS)):
            with self.subTest(form=form):
                self.warm()
                code, out, err = self.run_cli("fetch", form)
                self.assertEqual(code, 0, err)
                self.assertIn("Priority", out)
                self.assertEqual(len(self.schema_reads()), 1)
                self.assertIn("Priority", (self.home / ".cache" / "cdv-notion" / f"schema-{DS_TASKS}.json").read_text())
                outputs.append(out)
        self.assertEqual(len(set(outputs)), 1)

    def test_a_data_source_title_missing_from_the_cached_list_refreshes_the_list_once(self):
        self.warm()
        self.fake.data_sources[self.DS_ROADMAP] = data_source(self.DS_ROADMAP, "Roadmap", projects_schema(), uid(0xD3))
        code, out, err = self.run_cli("fetch", "Roadmap")
        self.assertEqual(code, 0, err)
        self.assertIn("data source: Roadmap", out)
        self.assertEqual(len(self.list_reads()), 1)
        self.fake.calls.clear()
        code, out, err = self.run_cli("fetch", "Nowhere")
        self.assertEqual(code, 2)
        self.assertIn("'Nowhere' is not a page id, a url, a key or the title of a connected data source", err)
        self.assertEqual(len(self.list_reads()), 1)

    def test_search_skips_a_data_source_no_longer_connected_after_one_list_refresh(self):
        gone = {"404": lambda: self.fake.data_sources.pop(DS_PROJECTS),
                "403": lambda: self.fake.on("POST", rf"/v1/data_sources/{DS_PROJECTS}/query",
                                            lambda r: error(403, "restricted_resource", "Not shared."))}
        for status, disconnect in gone.items():
            with self.subTest(status=status):
                self.fake.data_sources[DS_PROJECTS] = data_source(DS_PROJECTS, "Projects", projects_schema(), DB_PROJECTS)
                self.fake.overrides.clear()
                self.warm()
                disconnect()
                code, out, err = self.run_cli("search", "invoice")
                self.assertEqual(code, 0, err)
                self.assertIn(self.page["url"], out)
                self.assertEqual(len(self.list_reads()), 1)


class ApiTest(ClientTestCase):
    def test_api_refuses_a_path_outside_v1(self):
        for path in ("/v2/pages", "/users/me", "https://elsewhere.example.com/v1/users/me", "../v1/users/me"):
            with self.subTest(path=path):
                code, out, err = self.run_cli("api", "GET", path)
                self.assertEqual(code, 2)
                self.assertIn("/v1/", err)
        self.assertEqual(self.fake.calls, [])

    def test_api_exit_codes(self):
        code, out, err = self.run_cli("api", "GET", f"/v1/pages/{PAGE}")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["id"], PAGE)
        code, out, err = self.run_cli("api", "POST", f"/v1/data_sources/{DS_TASKS}/query", "--data", '{"page_size": 1}')
        self.assertEqual(code, 0, err)
        self.assertEqual(self.fake.sent("POST", rf"/v1/data_sources/{DS_TASKS}/query")[-1].json, {"page_size": 1})
        self.fake.on("GET", r"/v1/users/me", lambda r: error(400, "validation_error", "body of the refusal"))
        code, out, err = self.run_cli("api", "GET", "/v1/users/me")
        self.assertEqual(code, 1)
        self.assertIn("body of the refusal", out + err)
        code, out, err = self.run_cli("api", "GET", "/v1/pages/" + uid(0xDEAD))
        self.assertEqual(code, 1)
        self.assertIn("object_not_found", out + err)


def skill_table_rows(text_):
    rows = []
    for line in text_.splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


class SkillTextTest(unittest.TestCase):
    def test_skill_table_maps_each_need(self):
        rows = skill_table_rows((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
        needs = ["read a card", "find a card by key", "list a project's tasks", "move status", "write the body",
                 "comment", "attach an image", "find a person"]
        self.assertEqual(len(needs), 8)
        for need in needs:
            with self.subTest(need=need):
                found = [row for row in rows if need in row[0].lower()]
                self.assertTrue(found, need)
                self.assertRegex(found[0][1], r"`notion [a-z]")

    def test_skill_references_cover_markdown_properties_and_limits(self):
        skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        markdown = SKILL_DIR / "references" / "notion-markdown.md"
        properties = SKILL_DIR / "references" / "properties-and-filters.md"
        limits = SKILL_DIR / "references" / "api-limits.md"
        for reference in (markdown, properties, limits):
            self.assertIn("references/" + reference.name, skill)
        body = markdown.read_text(encoding="utf-8")
        for form in ("<callout icon=", "<table header-row=\"true\">", "<toggle>", "<page url=", "<mention url=", "<p />"):
            self.assertIn(form, body)
        props = properties.read_text(encoding="utf-8")
        for form in ("date:<Property>:start", "user://", "__YES__", "__NO__", "is not empty", "in (", "has", "contains"):
            self.assertIn(form, props)
        api_limits = limits.read_text(encoding="utf-8").lower()
        topics = ["resolved comments", "resolve a discussion", "page bodies", "another author's comment", "authorship"]
        self.assertEqual(len(topics), 5)
        for topic in topics:
            with self.subTest(topic=topic):
                self.assertIn(topic, api_limits)
        self.assertIn("instead", api_limits)

    def test_a_date_without_a_time_is_said_to_be_a_utc_day(self):
        properties = (SKILL_DIR / "references" / "properties-and-filters.md").read_text(encoding="utf-8")
        self.assertRegex(properties, r"A date with no time is the whole day \*\*in UTC\*\*")
        self.assertRegex(properties, r"created >= 2026-11-03T00:00:00-03:00 AND created < 2026-11-04T00:00:00-03:00")
        self.assertRegex(" ".join(load_client().__doc__.split()), r"date with no time in --where .* is the whole day in UTC")

    def test_changelog_and_catalog_list_cdv_notion(self):
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        unreleased = changelog.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
        self.assertIn("`cdv-notion`", unreleased)
        self.assertIn("cdv-notion", (REPO_ROOT / "CATALOG.md").read_text(encoding="utf-8"))
        entries = json.loads((REPO_ROOT / "registry.json").read_text(encoding="utf-8"))
        entries = entries.get("skills", entries) if isinstance(entries, dict) else entries
        self.assertIn("cdv-notion", [e["name"] for e in entries])


CORE_FILES = {
    "cdv-notion-ticket": REPO_ROOT / "skills" / "cdv-notion-ticket" / "SKILL.md",
    "cdv-open-pr": REPO_ROOT / "skills" / "cdv-open-pr" / "SKILL.md",
    "cdv-debug": REPO_ROOT / "skills" / "cdv-debug" / "SKILL.md",
    "ticket-format.md": REPO_ROOT / "skills" / "cdv-notion-ticket" / "references" / "ticket-format.md",
    "notion-ticket-template.md": REPO_ROOT / "skills" / "cdv-debug" / "references" / "notion-ticket-template.md",
}

MCP_TOOL_WORDS = [r"notion-fetch", r"notion-search", r"notion-update-page", r"notion-create-pages",
                  r"notion-create-comment", r"update_properties", r"replace_content", r"update_content",
                  r"insert_content", r"old_str", r"new_str", r"Notion MCP"]


class CoreSkillsTest(unittest.TestCase):
    def test_core_skills_name_no_mcp_tool_and_name_the_client(self):
        self.assertEqual(len(CORE_FILES), 5)
        for name, path in CORE_FILES.items():
            with self.subTest(file=name):
                body = path.read_text(encoding="utf-8")
                for word in MCP_TOOL_WORDS:
                    self.assertNotRegex(body, word)
                if name != "cdv-debug":
                    self.assertNotRegex(body, r"\bMCP\b")
                self.assertIn("cdv-notion", body)
                self.assertRegex(body, r"`notion (fetch|update|create|search|query|comments)")

    def test_edit_exit_codes_are_stated_as_the_plan_says(self):
        none_matched = r"no `--edit` matched[^.]*exits `1`[^.]*nothing (is |was )?changed"
        some_missed = r"some `--edit` matched and some did not[^.]*exits `4`"
        for path in (CORE_FILES["cdv-notion-ticket"], SKILL_DIR / "SKILL.md"):
            with self.subTest(file=path.parent.name):
                body = path.read_text(encoding="utf-8")
                self.assertRegex(body, none_matched)
                self.assertRegex(body, some_missed)
                self.assertNotRegex(body, r"`--edit` that did not match \(exit `4`\)")
                self.assertNotRegex(body, r"`4` \| done in part \(some edits did not match\)")

    def test_ticket_references_use_the_skill_markdown(self):
        reference = (SKILL_DIR / "references" / "notion-markdown.md").read_text(encoding="utf-8")
        for name in ("ticket-format.md", "notion-ticket-template.md"):
            with self.subTest(file=name):
                body = CORE_FILES[name].read_text(encoding="utf-8")
                self.assertIn("cdv-notion/references/notion-markdown.md", body)
                self.assertNotIn("enhanced markdown", body.lower())
                self.assertIn("<table header-row=\"true\">", body.replace(" fit-page-width=\"true\"", ""))
                self.assertIn("<tr><td>", body)
                for form in ("<table header-row=\"true\">", "<tr><td>", "<toggle>"):
                    self.assertIn(form, reference)
        ticket = CORE_FILES["ticket-format.md"].read_text(encoding="utf-8")
        self.assertRegex(ticket, r"<callout icon=\"[^\"]+\" color=\"blue_bg\">\n")
        self.assertIn("<callout icon=", reference)
        template = CORE_FILES["notion-ticket-template.md"].read_text(encoding="utf-8")
        self.assertIn("<toggle>", template)

    def test_the_anchored_append_writes_its_own_separator(self):
        template = CORE_FILES["notion-ticket-template.md"].read_text(encoding="utf-8")
        self.assertNotIn('"$(cat anchor.md analise-<slug>.md)"', template)
        self.assertIn("""--edit "$(cat anchor.md)" "$(cat anchor.md; printf '\\n\\n'; cat analise-<slug>.md)\"""", template)


if __name__ == "__main__":
    unittest.main()
