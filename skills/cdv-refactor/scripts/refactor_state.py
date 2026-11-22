#!/usr/bin/env python3
"""Keep the state of a refactor: its phases and slices, in one file a script owns.

    refactor_state.py --folder <state folder> init [--slug <slug>]
    refactor_state.py --folder <state folder> phase add <id> <goal ...>
    refactor_state.py --folder <state folder> phase start|done <id>
    refactor_state.py --folder <state folder> slice add <id> --phase <phase> <title ...>
    refactor_state.py --folder <state folder> slice start <id> [--child <name>] [--base <rev>]
    refactor_state.py --folder <state folder> slice built <id> --range <a>..<b>
    refactor_state.py --folder <state folder> slice landed <id> --range <a>..<b> [--evidence <path>]
    refactor_state.py --folder <state folder> slice drop <id> --reason <text ...>
    refactor_state.py --folder <state folder> where
    refactor_state.py --folder <state folder> render

`state.json` is the record; nobody edits it by hand. A slice goes `pending`, `running`, `built`
(its builder reported), `landed` (integrated, with its commit range) or `dropped`. A step out of
that order is refused (exit 3, nothing changed): a slice lands only after it started, a phase is
done only when none of its slices is still open. `where` prints one line per phase and slice.
`render` writes `LEDGER.md` whole and the block between the `refactor-state` markers of `STATE.md`,
counting commits and files from git, so that no document carries a number someone typed.

Exit 0 ok, 2 an unknown id or a bad argument, 3 refused.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # nothing written beside the vendored scripts

OK, BAD_INPUT, REFUSED = 0, 2, 3
BEGIN, END = "<!-- refactor-state:begin -->", "<!-- refactor-state:end -->"
OPEN = ("pending", "running", "built")


class Refused(Exception):
    pass


class BadInput(Exception):
    pass


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(folder):
    path = folder / "state.json"
    if not path.is_file():
        raise BadInput(f"no state.json in {folder}: run `init` first")
    return json.loads(path.read_text(encoding="utf-8"))


def save(folder, state):
    (folder / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find(items, ident, kind):
    for item in items:
        if item["id"] == ident:
            return item
    raise BadInput(f"unknown {kind}: {ident}")


def git(folder, *args):
    result = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def range_facts(folder, commit_range):
    """(commits, files, added, removed) of a range, or None when git does not know it."""
    if not commit_range or ".." not in commit_range:
        return None
    first, last = commit_range.split("..", 1)
    count = git(folder, "rev-list", "--count", f"{first}..{last}")
    stat = git(folder, "diff", "--shortstat", first, last)
    if count is None or stat is None:
        return None
    numbers = {"files": 0, "insertions": 0, "deletions": 0}
    for part in stat.split(","):
        words = part.split()
        if len(words) >= 2 and words[0].isdigit():
            for key in numbers:
                if words[1].startswith(key[:4]):
                    numbers[key] = int(words[0])
    return int(count), numbers["files"], numbers["insertions"], numbers["deletions"]


def cmd_init(folder, args):
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "state.json").exists():
        raise Refused("state.json already exists")
    save(folder, {"schema": 1, "slug": args.slug or folder.name, "created": now(), "phases": [], "slices": []})
    print(f"state.json created in {folder}")


def cmd_phase(folder, args):
    state = load(folder)
    if args.action == "add":
        if any(p["id"] == args.id for p in state["phases"]):
            raise Refused(f"phase {args.id} already exists")
        goal = " ".join(args.text).strip()
        if not goal:
            raise BadInput("a phase needs a goal")
        state["phases"].append({"id": args.id, "goal": goal, "status": "pending"})
    else:
        phase = find(state["phases"], args.id, "phase")
        if args.action == "start":
            if phase["status"] != "pending":
                raise Refused(f"phase {args.id} is {phase['status']}")
            phase.update(status="running", started=now())
        else:
            still = [s["id"] for s in state["slices"] if s["phase"] == args.id and s["status"] in OPEN]
            if still:
                raise Refused(f"phase {args.id} still has open slices: {', '.join(still)}")
            if phase["status"] == "done":
                raise Refused(f"phase {args.id} is already done")
            phase.update(status="done", done=now())
    save(folder, state)
    print(f"phase {args.id}: {args.action}")


def cmd_slice(folder, args):
    state = load(folder)
    if args.action == "add":
        find(state["phases"], args.phase, "phase")
        if any(s["id"] == args.id for s in state["slices"]):
            raise Refused(f"slice {args.id} already exists")
        title = " ".join(args.text).strip()
        if not title:
            raise BadInput("a slice needs a title")
        state["slices"].append({"id": args.id, "phase": args.phase, "title": title, "status": "pending"})
    else:
        item = find(state["slices"], args.id, "slice")
        status = item["status"]
        if args.action == "start":
            if status != "pending":
                raise Refused(f"slice {args.id} is {status}")
            item.update(status="running", started=now(), child=args.child, base=args.base)
        elif args.action == "built":
            if status != "running":
                raise Refused(f"slice {args.id} is {status}: only a running slice is built")
            item.update(status="built", built=now(), range=need_range(args))
        elif args.action == "landed":
            if status not in ("running", "built"):
                raise Refused(f"slice {args.id} is {status}: it lands only after it started")
            item.update(status="landed", landed=now(), range=need_range(args), evidence=args.evidence)
        elif args.action == "drop":
            reason = " ".join(args.reason or []).strip()
            if not reason:
                raise BadInput("a dropped slice needs --reason")
            if status == "landed":
                raise Refused(f"slice {args.id} already landed")
            item.update(status="dropped", reason=reason, dropped=now())
    save(folder, state)
    print(f"slice {args.id}: {args.action}")


def need_range(args):
    if not args.range or ".." not in args.range:
        raise BadInput("--range <first>..<last> is required")
    return args.range


def lines_where(state):
    out = []
    for phase in state["phases"]:
        own = [s for s in state["slices"] if s["phase"] == phase["id"]]
        landed = sum(1 for s in own if s["status"] == "landed")
        out.append(f"phase {phase['id']} [{phase['status']}] {phase['goal']} ({landed}/{len(own)} slices landed)")
        for item in own:
            extra = f" - {item['child']}" if item.get("child") and item["status"] == "running" else ""
            out.append(f"  {item['id']} [{item['status']}] {item['title']}{extra}")
    return out or ["no phase yet"]


def table(folder, state):
    rows = ["| Slice | Phase | Status | What | Commits | Files | Lines | Evidence |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for item in state["slices"]:
        facts = range_facts(folder, item.get("range")) if item["status"] in ("built", "landed") else None
        if facts:
            commits, files, added, removed = facts
            numbers = (str(commits), str(files), f"+{added} -{removed}")
        elif item.get("range"):
            numbers = ("range not found", "", "")
        else:
            numbers = ("", "", "")
        rows.append(
            f"| {item['id']} | {item['phase']} | {item['status']} | {item['title']} | {numbers[0]} | {numbers[1]} | {numbers[2]} | {item.get('evidence') or ''} |"
        )
    return rows


def cmd_render(folder, _args):
    state = load(folder)
    rows = table(folder, state)
    ledger = [f"# {state['slug']} - ledger", "", "Generated by `refactor_state.py render` from `state.json` and git. Do not edit.", ""]
    for phase in state["phases"]:
        ledger.append(f"- Phase {phase['id']} [{phase['status']}]: {phase['goal']}")
    ledger += ["", *rows, ""]
    for item in state["slices"]:
        if item["status"] == "landed" and item.get("range"):
            ledger.append(f"- {item['id']}: `{item['range']}`, landed {item.get('landed', '')}")
        if item["status"] == "dropped":
            ledger.append(f"- {item['id']}: dropped - {item.get('reason', '')}")
    (folder / "LEDGER.md").write_text("\n".join(ledger).rstrip("\n") + "\n", encoding="utf-8")
    state_md = folder / "STATE.md"
    block = "\n".join([BEGIN, *rows, END])
    if state_md.is_file():
        text = state_md.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            text = head + block + rest.split(END, 1)[1]
        else:
            text = text.rstrip("\n") + "\n\n## Slices\n\n" + block + "\n"
    else:
        text = f"# {state['slug']} - state\n\n## Now\n\n\n## Slices\n\n{block}\n\n## Waiting for the developer\n\n"
    state_md.write_text(text, encoding="utf-8")
    print(f"LEDGER.md and STATE.md rendered in {folder}")


def cmd_where(folder, _args):
    print("\n".join(lines_where(load(folder))))


def build_parser():
    parser = argparse.ArgumentParser(description="State of a refactor: phases and slices.")
    parser.add_argument("--folder", required=True, help="the refactor's state folder")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--slug")
    phase = commands.add_parser("phase")
    phase.add_argument("action", choices=("add", "start", "done"))
    phase.add_argument("id")
    phase.add_argument("text", nargs="*")
    piece = commands.add_parser("slice")
    piece.add_argument("action", choices=("add", "start", "built", "landed", "drop"))
    piece.add_argument("id")
    piece.add_argument("text", nargs="*")
    piece.add_argument("--phase")
    piece.add_argument("--child")
    piece.add_argument("--base")
    piece.add_argument("--range")
    piece.add_argument("--evidence")
    piece.add_argument("--reason", nargs="*")
    commands.add_parser("where")
    commands.add_parser("render")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    folder = Path(args.folder)
    handlers = {"init": cmd_init, "phase": cmd_phase, "slice": cmd_slice, "where": cmd_where, "render": cmd_render}
    try:
        if args.command == "slice" and args.action == "add" and not args.phase:
            raise BadInput("`slice add` needs --phase")
        handlers[args.command](folder, args)
    except BadInput as error:
        print(f"refactor_state: {error}", file=sys.stderr)
        return BAD_INPUT
    except Refused as error:
        print(f"refactor_state: refused - {error}", file=sys.stderr)
        return REFUSED
    return OK


if __name__ == "__main__":
    sys.exit(main())
