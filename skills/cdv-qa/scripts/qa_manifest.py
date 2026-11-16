#!/usr/bin/env python3
"""The records a QA run creates in external systems, so every one of them is deleted at the end.

    qa_manifest.py add --system <system> --type <type> --id <id> [--name <name>]
    qa_manifest.py done --system <system> --type <type> --id <id>
    qa_manifest.py pending
    (each also takes [--root <repo>] [--dir <folder>] [--run <run profile>])

A record is registered with `add` before it is created, with the name it will carry as its id when
the system has not given one yet; `add --id <real id> --name <that name>` then replaces the entry.
`done` closes a record once it is deleted; `pending` prints one line per record not closed
(`<system> <type> <id> [<name>]`) and nothing when there is none. The manifest is
`qa-manifest.json` in the run's work folder. Exit 0, 2 on a missing field, an unknown record or
when no work folder is found.
"""

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa_common import (  # noqa: E402
    OK,
    ScriptError,
    add_location_args,
    read_list,
    required,
    work_folder,
    write_list,
)

MANIFEST = "qa-manifest.json"
FIELDS = ["system", "type", "id"]


def key(record):
    return (record["system"], record["type"], record["id"])


def add(args, records):
    record = {"system": args.system.strip(), "type": args.type.strip(), "id": args.id.strip(), "done": False}
    if args.name:
        record["name"] = args.name.strip()
    for index, existing in enumerate(records):
        same = key(existing) == key(record)
        provisional = record.get("name") and existing["system"] == record["system"] and existing["type"] == record["type"] and existing["id"] == record["name"]
        if same or (provisional and not existing.get("done")):
            records[index] = record
            return f"registered {' '.join(key(record))}"
    records.append(record)
    return f"registered {' '.join(key(record))}"


def done(args, records):
    wanted = (args.system.strip(), args.type.strip(), args.id.strip())
    for record in records:
        if key(record) == wanted:
            record["done"] = True
            return f"done {' '.join(wanted)}"
    raise ScriptError(f"no record {' '.join(wanted)} in the manifest: register it with `add` first")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="qa_manifest.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("add", "done"):
        p = sub.add_parser(name)
        for field in FIELDS:
            p.add_argument(f"--{field}")
        if name == "add":
            p.add_argument("--name")
        add_location_args(p)
    add_location_args(sub.add_parser("pending"))
    args = parser.parse_args(argv)
    try:
        if args.command in ("add", "done"):
            required(args, FIELDS)
        path = work_folder(args.root, args.dir, args.run) / MANIFEST
        records = read_list(path)
        if args.command == "pending":
            for record in records:
                if not record.get("done"):
                    name = f" {record['name']}" if record.get("name") and record["name"] != record["id"] else ""
                    print(f"{record['system']} {record['type']} {record['id']}{name}")
            return OK
        message = (add if args.command == "add" else done)(args, records)
        write_list(path, records)
        print(message)
    except ScriptError as error:
        print(f"qa_manifest.py: {error}", file=sys.stderr)
        return error.code
    return OK


if __name__ == "__main__":
    sys.exit(main())
