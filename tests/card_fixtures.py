"""Synthetic cards for the card contract: a fake Notion with a tasks, a projects, a sprints and a wiki
data source carrying the property names of the contract's names map, page builders, and a fake
`notion` client for subprocess tests (the real client over the fake Notion, kept in a JSON file).

Nothing is copied from a real workspace: ids are made up, people are the client tests' "Ana Lima"
and "Bruno Costa", and keys are built at runtime so the public scan never sees one."""

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import signal
import sys
from pathlib import Path

from helpers import REPO_ROOT
from test_notion import FakeNotion, TOKEN, USERS, ANA, BRUNO, hex32, load_client, option, person, text, uid

CHECKER = REPO_ROOT / "skills" / "cdv-notion-ticket" / "scripts" / "card_contract.py"
CONTRACT = REPO_ROOT / "skills" / "cdv-notion-ticket" / "scripts" / "card-contract.json"
HOOK = REPO_ROOT / "hooks" / "card-check"
TESTS = Path(__file__).resolve().parent

PREFIX = "TSK"
DS_TASKS, DB_TASKS = uid(0xC51), uid(0xC1)
DS_PROJECTS, DB_PROJECTS = uid(0xC52), uid(0xC2)
DS_SPRINTS, DB_SPRINTS = uid(0xC53), uid(0xC3)
DS_WIKI, DB_WIKI = uid(0xC54), uid(0xC4)
CREATED = "2026-11-20T10:00:00.000Z"
SINCE = "2026-11-01"
ME = "ana@example.com"
NOBODY_KNOWN = {"object": "user", "id": uid(0xA9)}  # a person whose e-mail the token cannot read


@contextlib.contextmanager
def cpu_limit(seconds=20):
    """Ends a reading that takes more than this many seconds of this process's own CPU time: it cannot
    hang, and a busy machine does not change it (the wall clock does not count)."""
    def stop(*_):
        raise AssertionError(f"still reading after {seconds} s of CPU time")

    before = signal.signal(signal.SIGVTALRM, stop)
    signal.setitimer(signal.ITIMER_VIRTUAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_VIRTUAL, 0)
        signal.signal(signal.SIGVTALRM, before)


def key(number):
    return PREFIX + "-" + str(number)


def tasks_schema():
    statuses = ["Not started", "In progress", "Code Review", "Rollout", "Done", "Archived", "On Hold/Blocked", "Em revisão"]
    return {
        "Task name": {"id": "title", "name": "Task name", "type": "title", "title": {}},
        "Task ID": {"id": "tid", "name": "Task ID", "type": "unique_id", "unique_id": {"prefix": PREFIX}},
        "Status": {"id": "st", "name": "Status", "type": "status",
                   "status": {"options": [option(n, i) for i, n in enumerate(statuses)], "groups": []}},
        "Resumo": {"id": "rs", "name": "Resumo", "type": "rich_text", "rich_text": {}},
        "Requester": {"id": "rq", "name": "Requester", "type": "people", "people": {}},
        "Assignee": {"id": "as", "name": "Assignee", "type": "people", "people": {}},
        "Pull Request": {"id": "pr", "name": "Pull Request", "type": "url", "url": {}},
        "Tags": {"id": "tg", "name": "Tags", "type": "multi_select",
                 "multi_select": {"options": [option(n, i) for i, n in enumerate(["Helpdesk", "Backend"])]}},
        "Type": {"id": "ty", "name": "Type", "type": "select",
                 "select": {"options": [option(n, i) for i, n in enumerate(["Tarefa", "Bug"])]}},
        "Email": {"id": "em", "name": "Email", "type": "email", "email": {}},
        "Created time": {"id": "ct", "name": "Created time", "type": "created_time", "created_time": {}},
    }


def projects_schema():
    return {
        "Project name": {"id": "title", "name": "Project name", "type": "title", "title": {}},
        "Project ID": {"id": "pid", "name": "Project ID", "type": "unique_id", "unique_id": {"prefix": "PRJ"}},
        "Status": {"id": "st", "name": "Status", "type": "status",
                   "status": {"options": [option(n, i) for i, n in enumerate(["In progress", "Done"])], "groups": []}},
        "Executores": {"id": "ex", "name": "Executores", "type": "people", "people": {}},
        "Pontuação Total Projeto": {"id": "pt", "name": "Pontuação Total Projeto", "type": "number", "number": {}},
    }


def simple_schema():
    return {"Name": {"id": "title", "name": "Name", "type": "title", "title": {}}}


def source(identifier, title, properties, database):
    return {"object": "data_source", "id": identifier, "title": text(title),
            "parent": {"type": "database_id", "database_id": database}, "properties": properties, "in_trash": False}


class CardNotion(FakeNotion):
    """The client tests' fake Notion, with the data sources a card lives in."""

    def __init__(self):
        super().__init__()
        self.data_sources = {
            DS_TASKS: source(DS_TASKS, "Tasks", tasks_schema(), DB_TASKS),
            DS_PROJECTS: source(DS_PROJECTS, "Projects", projects_schema(), DB_PROJECTS),
            DS_SPRINTS: source(DS_SPRINTS, "Sprints", simple_schema(), DB_SPRINTS),
            DS_WIKI: source(DS_WIKI, "Wiki", simple_schema(), DB_WIKI),
        }
        self.databases = {
            db: {"object": "database", "id": db, "title": text(ds["title"][0]["plain_text"]),
                 "data_sources": [{"id": ds_id, "name": ds["title"][0]["plain_text"]}]}
            for ds_id, ds, db in ((i, d, d["parent"]["database_id"]) for i, d in self.data_sources.items())
        }
        self.cut = []  # the pages whose body a read returns in part

    def add(self, page, markdown=""):
        return self.add_page(page, markdown)

    def page_markdown(self, identifier):
        read = super().page_markdown(identifier)
        if identifier in self.cut:
            read.update(truncated=True, unknown_block_ids=[uid(0xB10C)])
        return read


def people(*who):
    return [USERS[w] if isinstance(w, str) else w for w in who]


def task(n, body="", status="In progress", assignee=(ANA,), requester=(BRUNO,), type_="Tarefa", email=None,
         pr=None, summary=None, created=CREATED, name=None):
    identifier = uid(0x7000 + n)
    name = name or f"Synthetic task {n}"
    props = {
        "Task name": {"id": "title", "type": "title", "title": text(name)},
        "Task ID": {"id": "tid", "type": "unique_id", "unique_id": {"prefix": PREFIX, "number": n}},
        "Status": {"id": "st", "type": "status", "status": {"id": "s", "name": status, "color": "default"} if status else None},
        "Resumo": {"id": "rs", "type": "rich_text", "rich_text": text(summary) if summary else []},
        "Requester": {"id": "rq", "type": "people", "people": people(*requester)},
        "Assignee": {"id": "as", "type": "people", "people": people(*assignee)},
        "Pull Request": {"id": "pr", "type": "url", "url": pr},
        "Tags": {"id": "tg", "type": "multi_select", "multi_select": []},
        "Type": {"id": "ty", "type": "select", "select": {"id": "t", "name": type_, "color": "default"} if type_ else None},
        "Email": {"id": "em", "type": "email", "email": email},
        "Created time": {"id": "ct", "type": "created_time", "created_time": created},
    }
    return {
        "object": "page", "id": identifier,
        "url": "https://www.notion.so/" + name.replace(" ", "-") + "-" + hex32(identifier),
        "parent": {"type": "data_source_id", "data_source_id": DS_TASKS, "database_id": DB_TASKS},
        "in_trash": False, "icon": None, "created_time": created,
        "created_by": {"object": "user", "id": uid(0xB07)}, "properties": props,
    }, body


def project(n, body="", executors=(ANA,), created=CREATED):
    identifier = uid(0x8000 + n)
    props = {
        "Project name": {"id": "title", "type": "title", "title": text(f"Synthetic project {n}")},
        "Project ID": {"id": "pid", "type": "unique_id", "unique_id": {"prefix": "PRJ", "number": n}},
        "Status": {"id": "st", "type": "status", "status": {"id": "s", "name": "In progress", "color": "default"}},
        "Executores": {"id": "ex", "type": "people", "people": people(*executors)},
        "Pontuação Total Projeto": {"id": "pt", "type": "number", "number": 11},
    }
    return {
        "object": "page", "id": identifier, "url": "https://www.notion.so/Synthetic-project-" + hex32(identifier),
        "parent": {"type": "data_source_id", "data_source_id": DS_PROJECTS, "database_id": DB_PROJECTS},
        "in_trash": False, "icon": None, "created_time": created,
        "created_by": {"object": "user", "id": uid(0xB07)}, "properties": props,
    }, body


def row(n, data_source, created=CREATED):
    identifier = uid(0x9000 + n)
    return {
        "object": "page", "id": identifier, "url": "https://www.notion.so/Row-" + hex32(identifier),
        "parent": {"type": "data_source_id", "data_source_id": data_source},
        "in_trash": False, "icon": None, "created_time": created,
        "created_by": {"object": "user", "id": uid(0xB07)},
        "properties": {"Name": {"id": "title", "type": "title", "title": text(f"Row {n}")}},
    }


def toggle(title, children):
    return f"<toggle>\n{title}\n\n{children.strip()}\n</toggle>"


def project_body(current="", request="O pedido como chegou: acompanhar as faturas numa tela só.", checklist="CES 11"):
    parts = [toggle("Descrição do Projeto", request)] if request is not None else []
    if current is not None:
        parts.append(toggle("Discovery & Define", current) if current.strip() else "<toggle>\nDiscovery & Define\n</toggle>")
    parts.append(toggle("Checklist de Desenvolvimento", checklist))
    return "\n\n".join(parts) + "\n"


def contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def load_checker(client_module=None):
    name = f"card_contract_{id(client_module)}_{os.getpid()}"
    loader = importlib.machinery.SourceFileLoader(name, str(CHECKER))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    writes = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    if client_module is not None:
        module._client = client_module
    return module


def run_main(module, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(argv)
    return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------------------------
# A fake `notion` client for subprocesses: the real client over a CardNotion kept in a JSON file
# ---------------------------------------------------------------------------------------------

STATE_KEYS = ("pages", "markdown", "comments", "next_id", "next_number", "cut")


def save_state(fake, path, calls=()):
    state = {k: getattr(fake, k) for k in STATE_KEYS}
    state["fail"] = getattr(fake, "fail_pages", {})
    Path(path).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def fake_from_state(path):
    fake = CardNotion()
    state = json.loads(Path(path).read_text(encoding="utf-8"))
    for name in STATE_KEYS:
        setattr(fake, name, state[name])
    fake.fail_pages = state.get("fail", {})
    for page_id, status in fake.fail_pages.items():
        fake.on("GET", f"/v1/pages/{page_id}",
                lambda r, s=status: (s, {"object": "error", "status": s, "code": "restricted_resource",
                                          "message": "synthetic refusal"}))
    return fake


def run_client(module, state_path, argv):
    """Run the real client's main over the fake kept in state_path; log each request; save writes."""
    fake = fake_from_state(state_path)
    module.TRANSPORT = fake
    code = module.main(argv)
    save_state(fake, state_path)
    with open(str(state_path) + ".calls", "a", encoding="utf-8") as log:
        for call in fake.calls:
            log.write(f"{call.method} {call.path}\n")
    return code


def real_client():
    module = load_client()
    module.secret_tool = lambda *args, **kwargs: None
    module.git_email = lambda: ""
    return module


WRAPPER = '''#!/usr/bin/env python3
"""A fake cdv-notion client for tests: the real client over a fake Notion kept in a JSON file."""
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, {tests!r})
import card_fixtures as _cf

_real = _cf.real_client()
if {home!r}:
    from pathlib import Path as _Path
    _real.home = lambda: _Path({home!r})
globals().update({{k: getattr(_real, k) for k in dir(_real) if not k.startswith("__")}})


def main(argv=None):
    return _cf.run_client(_real, {state!r}, sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
'''


def write_fake_client(path, state_path, home=None):
    """A fake client at `path`. With `home`, its settings and cache live there whatever $HOME is."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(WRAPPER.format(tests=str(TESTS), state=str(state_path), home=str(home or "")), encoding="utf-8")
    path.chmod(0o755)
    return path

