"""Shared facts of a kickoff run: the run profile's keys and values, the stages of the chain, the
roles, and where the run profile, its folder and the repository profile live.

Used by propose_profile.py, run_profile.py, run_status.py, role_target.py and brief.py, which sit
in the same directory. Standard library only.
"""

import re
from pathlib import Path

# Exit codes of every kickoff script (door 9).
OK, INVALID, BAD_INPUT, REFUSED = 0, 1, 2, 3

# The stages a chain may hold, in the only order they run. `investigate` is a chain of its own.
STAGES = ["research", "grilling", "plan", "build", "verify", "review", "fix", "qa", "finalize", "watch", "ticket"]
INVESTIGATE = "investigate"
ALL_STAGES = STAGES + [INVESTIGATE]

# The run profile key whose value `none` or `0` skips a stage.
STAGE_SKIP_KEY = {
    "grilling": "planning",
    "plan": "planning",
    "verify": "verify_rounds",
    "review": "review",
    "fix": "review",
    "qa": "qa",
}

# Who runs each stage. `build` runs on the run profile's `builder_role`, in the orchestrator's own
# session when `builder: inline`.
STAGE_ROLE = {
    "research": "research",
    "grilling": "orchestrator",
    "plan": "orchestrator",
    "build": None,
    "verify": "verifier",
    "review": "reviewer",
    "fix": "fixer",
    "qa": "qa",
    "finalize": "orchestrator",
    "watch": "orchestrator",
    "ticket": "orchestrator",
    "investigate": "orchestrator",
}

ROLES = ["orchestrator", "builder", "builder_risk", "verifier", "reviewer", "fixer", "qa", "research", "judge"]
EFFORTS = ["low", "medium", "high", "xhigh", "max"]

OPTIONAL_STEPS = ["slack-draft", "mock-before-after", "blind-judges", "validation-page"]
STOP_EVENTS = ["plan-approval", "external-write", "production-write", "report"]

# Door 1: the scalar keys of the run profile and their sets. A tuple is an enum.
RUN_SCALARS = {
    "schema": ("1",),
    "feature": "slug",
    "track": ("small", "medium", "big"),
    "mode": ("investigate", "plan-then-build", "autonomous", "step-by-step"),
    "planning": ("none", "tlc-spec-lean"),
    "workspace": ("main", "worktree"),
    "builder": ("inline", "child"),
    "builder_role": ("builder", "builder_risk"),
    "verify_rounds": ("0", "1"),  # the Review phase of tlc-spec-lean runs once or not at all
    "fault_injection": ("true", "false"),
    "review": ("none", "bugs-and-regressions"),
    "qa": ("none", "browser-local", "browser-external-test-records"),
    "unattended": ("own-test-records",),
}
# Door 1 lists, and `chain` (settled additively, Landing row 10).
RUN_LISTS = {
    "optional": OPTIONAL_STEPS,
    "stops": STOP_EVENTS + ALL_STAGES,
    "chain": ALL_STAGES,
}
ROLE_KEYS = ["role_" + role for role in ROLES]

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*):(?:[ ]+(.*))?$")


class ScriptError(Exception):
    def __init__(self, message, code=BAD_INPUT):
        super().__init__(message)
        self.code = code


# -- the flat profile subset -----------------------------------------------------------------


def _scalar(text):
    text = text.strip()
    if not text or text.startswith("#"):
        return None
    if text[0] in "\"'":
        quote = text[0]
        end = text.find(quote, 1)
        return text[1:end] if end > 0 else text[1:]
    return re.split(r"\s#", text, maxsplit=1)[0].rstrip()


def parse_lines(text):
    """The flat subset the repository profile uses: `key: value`, and `key:` followed by `- item`
    lines. Returns (entries, errors): entries are (line number, key, value) where value is a str or
    a list; errors are (line number, message) for lines that are neither."""
    entries, errors, current = [], [], None
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "-" or stripped.startswith("- "):
            if current is None:
                errors.append((number, f"list item outside a list: {stripped}"))
                continue
            item = _scalar(stripped[1:])
            if item:
                current.append(item)
            continue
        match = LINE_RE.match(raw.rstrip())
        if not match or raw[:1] in (" ", "\t"):
            errors.append((number, f"not a `key: value` line: {stripped}"))
            current = None
            continue
        value = _scalar(match.group(2) or "")
        if value is None:
            current = []
            entries.append((number, match.group(1), current))
        else:
            entries.append((number, match.group(1), value))
            current = None
    return entries, errors


def parse_flat(text):
    """Key -> value of the flat subset; the last line of a key wins, malformed lines are ignored."""
    entries, _errors = parse_lines(text)
    return {key: value for _number, key, value in entries}


def render(values, scalars, lists):
    """The run profile as text: the scalar keys in order, then each list."""
    lines = [f"{key}: {values[key]}" for key in scalars if key in values]
    for key in lists:
        lines.append(f"{key}:")
        lines += [f"  - {item}" for item in values.get(key, [])]
    return "\n".join(lines) + "\n"


# -- where things live -----------------------------------------------------------------------


def repo_profile(root):
    """The repository profile with the machine's local profile over it; {} when absent."""
    base = Path(root) / ".claude" / "harness" / "profile.yaml"
    values = parse_flat(base.read_text(encoding="utf-8")) if base.is_file() else {}
    local = base.with_name("profile.local.yaml")
    if local.is_file():
        values.update(parse_flat(local.read_text(encoding="utf-8")))
    return values


def setting(values, key):
    """A scalar value, or "" when the key is missing, empty or `none`."""
    value = values.get(key)
    if not isinstance(value, str) or value.strip().lower() in ("", "none"):
        return ""
    return value.strip()


def run_profiles(root):
    root = Path(root)
    found = sorted((root / ".specs" / "features").glob("*/run.yaml")) + sorted(root.glob("RUN-*.yaml"))
    return [p for p in found if p.is_file()]


def find_run_profile(root, explicit=None):
    """The run profile named by --run, or the only one under the root; ScriptError(2) otherwise."""
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = Path(root) / path
        if not path.is_file():
            raise ScriptError(f"no run profile at {explicit}")
        return path
    found = run_profiles(root)
    if not found:
        raise ScriptError(
            "no run profile: write .specs/features/<slug>/run.yaml (or RUN-<slug>.yaml at the root) with cdv-kickoff first"
        )
    if len(found) > 1:
        names = ", ".join(str(p.relative_to(root)) for p in found)
        raise ScriptError(f"several run profiles ({names}): pass --run <file>")
    return found[0]


def run_folder(root, profile_path):
    """The feature's work folder: the plan folder that holds run.yaml, or RUN-<slug>/ at the root."""
    profile_path = Path(profile_path)
    if profile_path.name == "run.yaml":
        return profile_path.parent
    return Path(root) / profile_path.stem


def load_run_profile(path):
    """The values of a run profile that `run_profile.py validate` accepts; ScriptError(2) otherwise."""
    from run_profile import validate_text  # noqa: PLC0415 - sibling module

    text = Path(path).read_text(encoding="utf-8")
    problems = validate_text(text)
    if problems:
        raise ScriptError(f"{path}: invalid run profile, run `run_profile.py validate` ({problems[0]})")
    return parse_flat(text)


def stage_role(stage, run):
    if stage == "build":
        return "orchestrator" if run.get("builder") == "inline" else run.get("builder_role", "builder")
    return STAGE_ROLE.get(stage)


def stage_skipped(stage, run):
    key = STAGE_SKIP_KEY.get(stage)
    return key is not None and str(run.get(key, "")).strip() in ("none", "0")
