"""Where a QA run keeps its files, shared by qa_report.py and qa_manifest.py.

The work folder is the kickoff run's folder (`.specs/features/<slug>/`, or `RUN-<slug>/` beside
`RUN-<slug>.yaml`), found through `cdv-kickoff/scripts/run_common.py`, which `harness sync` vendors
beside this skill; `--dir` names another folder. Standard library only.
"""

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
KICKOFF_SCRIPTS = Path(__file__).resolve().parents[2] / "cdv-kickoff" / "scripts"
sys.path.insert(0, str(KICKOFF_SCRIPTS))

from run_common import BAD_INPUT, OK, ScriptError, find_run_profile, run_folder  # noqa: E402,F401


def work_folder(root, folder=None, run=None):
    if folder:
        path = Path(folder)
        return path if path.is_absolute() else Path(root) / path
    return run_folder(root, find_run_profile(root, run))


def read_list(path):
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ScriptError(f"{path}: not a list")
    return data


def write_list(path, items):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def required(args, fields):
    """ScriptError(2) naming the first field that is missing or empty."""
    for field in fields:
        value = getattr(args, field, None)
        if value is None or not str(value).strip():
            raise ScriptError(f"missing field `{field}`: pass --{field} <value>")


def add_location_args(parser):
    parser.add_argument("--root", default=".", help="repository root (default: the current directory)")
    parser.add_argument("--dir", help="work folder (default: the folder of the run profile)")
    parser.add_argument("--run", help="run profile file, when the root holds more than one")
