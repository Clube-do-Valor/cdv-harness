"""The cdv-notion client (skills/cdv-notion/scripts/notion) against a fake Notion, and the skill text.

The client is loaded as a module and its HTTP transport is replaced by FakeNotion, which answers
from synthetic objects written from the shapes of the official API reference. Nothing here is
copied from a real workspace: ids are made up, people are "Ana Lima" and "Bruno Costa", and ticket
keys and data source references are built at runtime so the public scan never sees one."""

import contextlib
import datetime
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
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
                        comment["rich_text"] = text((r.json or {}).get("markdown", ""))
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
        match = re.fullmatch(r"/v1/blocks/([^/]+)", p)
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
        return {"object": "page_markdown", "id": identifier, "markdown": self.markdown.get(identifier, ""),
                "truncated": False, "unknown_block_ids": []}

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
            joined = "".join(part["text"]["content"] for part in written[schema_type])
            return text(joined) if joined else []
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
        self.add_page(page, body.get("markdown", ""))
        return 200, page

    def create_comment(self, body):
        comment = {
            "object": "comment",
            "id": self.new_id(),
            "discussion_id": body.get("discussion_id") or self.new_id(),
            "parent": body.get("parent") or {"type": "page_id", "page_id": PAGE},
            "created_by": {"object": "user", "id": BOT},
            "rich_text": text(body.get("markdown", "")),
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

    def test_create_after_timeout_without_page_exits_1_sent_once(self):
        def timeout(r):
            raise TimeoutError("timed out")

        self.fake.on("POST", r"/v1/pages", timeout)
        code, out, err = self.run_cli("create", "--parent", COLLECTION + DS_TASKS, "--set", "Task name=Never arrived")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.fake.sent("POST", r"/v1/pages")), 1)
        self.assertIn("Never arrived", err)


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

    def test_doctor_write_check_mismatch_exits_1_and_trashes(self):
        self.settings(test_marker="QA MARKER")
        self.fake.on("GET", r"/v1/pages/[^/]+/markdown",
                     lambda r: (200, {"object": "page_markdown", "id": r.path.split("/")[3], "markdown": "something else",
                                      "truncated": False, "unknown_block_ids": []}))
        code, out, err = self.run_cli("doctor", "--write-check", COLLECTION + DS_TASKS)
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out)
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


if __name__ == "__main__":
    unittest.main()
